"""src/lab/platform/workflows.py — the run-request contract comes from lab.platform.contracts (statuses, the
event's field names via WorkflowRequest) and every entry point takes `client=` so a host's composition
root can hand in ITS Redis client (the container's Singleton) instead of the module reaching for the
pool. Offline: FakeRedis passed explicitly while the shared pool is a DeadRedis — any call that bypassed
the injected client would raise. (The full stream/hash behaviour is covered by tests/integration/test_workflows.py.)
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_workflows.py"""
import json

import pytest
import redis

from fixtures.fakes import DeadRedis, FakeRedis, patched_client
from lab.platform import workflows
from lab.platform.contracts import WorkflowRequest, WorkflowStatus

INPUTS = {"diagram": "art://d1/lab.vsdx", "requirements": ["art://r1/req.docx"]}


def test_statuses_are_the_contracts_values():
    assert workflows.STATUSES == tuple(s.value for s in WorkflowStatus) == ("pending", "running", "done", "failed")


def test_request_publishes_the_contracts_event_shape():
    with patched_client(FakeRedis()) as r:
        rid = workflows.request("visio_to_archimate", INPUTS, "socrates")
        (_, fields), = r.x[workflows.REQ]
        req = WorkflowRequest.from_fields(fields)                       # parses cleanly = shape is the contract's
        assert req.request_id == rid and req.process == "visio_to_archimate" and req.inputs == INPUTS
        assert req.requester == "socrates" and req.status is WorkflowStatus.PENDING
        assert set(fields) == {"request_id", "process", "inputs", "requester", "status", "created_at", "created_ts"}
        assert r.h[f"workflow:req:{rid}"] == fields


def test_every_entry_point_uses_the_injected_client_not_the_pool():
    fake = FakeRedis()
    with patched_client(DeadRedis()):                                    # the pool must never be touched
        rid = workflows.request("visio_to_archimate", INPUTS, "u", client=fake)
        assert workflows.status(rid, client=fake)["inputs"] == INPUTS
        assert [s["request_id"] for s in workflows.pending(client=fake)] == [rid]
        assert [s["request_id"] for s in workflows.recent(client=fake)] == [rid]
        upd = workflows.mark(rid, WorkflowStatus.RUNNING, consumer="1", client=fake)
        assert upd["status"] == "running" and fake.h[f"workflow:req:{rid}"]["status"] == "running"
        events = workflows.channel_events(workflows.GROUPS[0], "1", count=5, client=fake)
        assert [f["request_id"] for _, f in events] == [rid]
        workflows.ack(workflows.GROUPS[0], events[0][0], client=fake)
        assert fake.calls["xack"] == 1
        workflows.mark(rid, "done", summary={"views": 1}, client=fake)
        assert json.loads(fake.h[f"workflow:req:{rid}"]["summary"]) == {"views": 1}
        assert rid not in fake.s.get("workflow:pending", set())
        with pytest.raises(ValueError, match="one of"):
            workflows.mark(rid, "exploded", client=fake)


# ------------------------------------------------------------------ idempotency
def test_submit_without_a_key_queues_every_call_deliberately():
    """No key = no de-duplication, ON PURPOSE: re-running the SAME diagram is a legitimate act (a
    changed prompt, a re-render, a second opinion). Content-hash dedup would silently refuse it."""
    with patched_client(FakeRedis()) as r:
        a, dup_a = workflows.submit("visio_to_archimate", INPUTS, "u")
        b, dup_b = workflows.submit("visio_to_archimate", INPUTS, "u")
        assert a != b and dup_a is False and dup_b is False
        assert len(r.x[workflows.REQ]) == 2
        assert not [k for k in r.kv if k.startswith(workflows.IDEM)]     # no key, no claim


def test_the_same_idempotency_key_returns_the_first_request_and_queues_nothing():
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        first, dup1 = workflows.submit("visio_to_archimate", INPUTS, "copilot", idempotency_key="msg-7", client=fake)
        again, dup2 = workflows.submit("visio_to_archimate", INPUTS, "copilot", idempotency_key="msg-7", client=fake)
        assert again == first and dup1 is False and dup2 is True
        assert len(fake.x[workflows.REQ]) == 1                    # a retry burns no tokens
        assert fake.kv[f"{workflows.IDEM}visio_to_archimate:msg-7"] == first
        assert fake.ttl[f"{workflows.IDEM}visio_to_archimate:msg-7"] == workflows.IDEMPOTENCY_TTL


def test_the_claim_is_atomic_and_namespaced_per_process():
    """SET NX EX, never GET-then-SET: two connectors retrying at once must not each create a run.
    The FakeRedis SET honours NX, so the second caller takes the loser branch."""
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        rid, _ = workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert fake.set(f"{workflows.IDEM}visio_to_archimate:k", "other", nx=True, ex=60) is None
        # a DIFFERENT process may reuse the caller's key without colliding
        assert workflows.idempotency_key_for("other_process", "k") != workflows.idempotency_key_for("visio_to_archimate", "k")
        assert workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key=" k ", client=fake)[0] == rid


def test_an_expired_key_queues_a_new_run():
    """TTL expiry is the documented behaviour: the key is a RETRY window, not a permanent uniqueness
    constraint — after it lapses the same key is free and submits again."""
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        first, _ = workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        fake.kv.pop(f"{workflows.IDEM}visio_to_archimate:k")            # TTL lapsed
        second, dup = workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert second != first and dup is False


def test_a_failed_publish_releases_the_claim_so_the_retry_can_succeed():
    """The claim is taken BEFORE the stream write; if that write fails the key must not be left
    pointing at a run that does not exist — otherwise every retry returns a phantom request id."""
    fake = FakeRedis()
    fake.fail("xadd")
    with patched_client(DeadRedis()):
        with pytest.raises(redis.ConnectionError):
            workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert f"{workflows.IDEM}visio_to_archimate:k" not in fake.kv
        fake.fail("xadd", False)
        rid, dup = workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert rid.startswith("wfr-") and dup is False


def test_a_claim_that_expires_mid_call_is_re_taken_rather_than_lost():
    """The narrow race between SET NX and the GET that reads the winner: the key expired in between,
    so there is no first request to hand back. The claim is simply re-taken and this call is the run —
    never silently unclaimed, which would let the NEXT retry queue a second one."""
    class Expiring(FakeRedis):
        def set(self, k, v, nx=False, ex=None, **kw):
            if nx and k.startswith(workflows.IDEM):
                return None                       # someone holds it…
            return super().set(k, v, nx=nx, ex=ex, **kw)

        def get(self, k):
            return None                           # …but it lapsed before we could read it

    fake = Expiring()
    with patched_client(DeadRedis()):
        rid, dup = workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert dup is False and fake.kv[f"{workflows.IDEM}visio_to_archimate:k"] == rid
        assert len(fake.x[workflows.REQ]) == 1


def test_a_failed_publish_without_a_key_deletes_nothing():
    fake = FakeRedis()
    fake.fail("xadd")
    with patched_client(DeadRedis()):
        with pytest.raises(redis.ConnectionError):
            workflows.submit("visio_to_archimate", INPUTS, "u", client=fake)
        assert "delete" not in fake.calls


def test_a_bad_idempotency_key_is_refused_before_anything_is_written():
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        for bad in (42, "x" * 201, "a\nb"):
            with pytest.raises(ValueError, match="idempotency_key"):
                workflows.submit("visio_to_archimate", INPUTS, "u", idempotency_key=bad, client=fake)
        assert fake.x == {}


def test_request_is_the_id_only_facade_over_submit():
    """One implementation: `request()` is `submit()` for callers that only want the id."""
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        rid = workflows.request("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake)
        assert workflows.request("visio_to_archimate", INPUTS, "u", idempotency_key="k", client=fake) == rid


def test_status_decodes_whatever_mark_encoded():
    """mark() JSON-encodes any dict/list field, so status() decodes symmetrically — a new list-valued
    output (import_artifacts) needs no edit here."""
    fake = FakeRedis()
    with patched_client(DeadRedis()):
        rid = workflows.request("visio_to_archimate", INPUTS, "u", client=fake)
        workflows.mark(rid, "done", import_artifacts=[{"ref": "art://x/o.xlsx", "label": "Objects"}],
                       error="plain text", client=fake)
        st = workflows.status(rid, client=fake)
        assert st["import_artifacts"] == [{"ref": "art://x/o.xlsx", "label": "Objects"}]
        assert st["error"] == "plain text" and st["inputs"] == INPUTS


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
