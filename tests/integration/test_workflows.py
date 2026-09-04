"""src/lab/platform/workflows.py — run requests over Redis Streams (Submit -> long-lived consumer). OFFLINE by
default via tests/_fakes.FakeRedis; one INTEGRATION test covers the crash-recovery re-read
(XREADGROUP with id "0") on the local Redis and skips cleanly when it is unreachable."""
import json
import uuid


import redis

from fixtures.fakes import FakeRedis, patched_client, run_script
from lab.platform import workflows

INPUTS = {"diagram": "art://d1/lab.vsdx", "requirements": ["art://r1/req.docx"]}


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    raise AssertionError(f"expected {exc.__name__}")


def test_request_publishes_and_status_decodes():
    with patched_client(FakeRedis()) as r:
        rid = workflows.request("visio_to_archimate", INPUTS, "socrates")
        assert rid.startswith("wfr-") and len(rid) == 16
        assert set(g for s, g in r.groups if s == workflows.REQ) == set(workflows.GROUPS)
        (eid, fields), = r.x[workflows.REQ]
        assert fields["request_id"] == rid and fields["process"] == "visio_to_archimate"
        assert json.loads(fields["inputs"]) == INPUTS and fields["status"] == "pending"
        assert r.s["workflow:pending"] == {rid}
        st = workflows.status(rid)
        assert st["inputs"] == INPUTS and st["requester"] == "socrates" and st["created_at"]
        assert workflows.status("wfr-nope") == {}
        # undecodable JSON in a decoded field is left as-is, never raises
        r.h[f"workflow:req:{rid}"]["summary"] = "not json"
        assert workflows.status(rid)["summary"] == "not json"


def test_ensure_groups_idempotent_and_other_errors_propagate():
    with patched_client(FakeRedis()) as r:
        workflows.ensure_groups(); workflows.ensure_groups()
        assert r.calls["xgroup_create"] == 2 * len(workflows.GROUPS)
        r.fail("xgroup_create", redis.ResponseError("ERR other"))
        _raises(redis.ResponseError, workflows.ensure_groups)


def test_mark_lifecycle():
    with patched_client(FakeRedis()) as r:
        rid = workflows.request("visio_to_archimate", INPUTS, "u")
        _raises(ValueError, workflows.mark, rid, "exploded")
        _raises(KeyError, workflows.mark, "wfr-missing", "running")
        upd = workflows.mark(rid, "running", consumer="wf-visio-1", trace_id="abc", nothing=None)
        assert upd["status"] == "running" and upd["started_at"] and "nothing" not in upd
        h = r.h[f"workflow:req:{rid}"]
        assert h["status"] == "running" and h["consumer"] == "wf-visio-1" and h["trace_id"] == "abc"
        assert rid in r.s["workflow:pending"], "running is still pending"
        # explicit started_at wins; dict/list fields are JSON-encoded, others stringified
        upd = workflows.mark(rid, "running", started_at="2026-01-01T00:00:00+00:00", summary={"views": 2}, n=3)
        assert upd["started_at"] == "2026-01-01T00:00:00+00:00" and upd["summary"] == '{"views": 2}' and upd["n"] == "3"
        assert workflows.status(rid)["summary"] == {"views": 2}
        upd = workflows.mark(rid, "done", approval_id="apr-1")
        assert upd["finished_at"] and r.h[f"workflow:req:{rid}"]["approval_id"] == "apr-1"
        assert rid not in r.s["workflow:pending"] and workflows.pending() == []
        rid2 = workflows.request("visio_to_archimate", INPUTS, "u")
        upd = workflows.mark(rid2, "failed", error="boom", finished_at="fixed")
        assert upd["finished_at"] == "fixed" and rid2 not in r.s["workflow:pending"]
        assert [s["request_id"] for s in workflows.recent()] == [rid2, rid], "newest first"
        assert len(workflows.recent(limit=1)) == 1


def test_channel_events_ack_and_pending_only():
    with patched_client(FakeRedis()) as r:
        g = workflows.GROUPS[0]
        assert workflows.channel_events(g) == []
        rid = workflows.request("visio_to_archimate", INPUTS, "u")
        evs = workflows.channel_events(g, consumer="7", block_ms=10)
        assert len(evs) == 1 and evs[0][1]["request_id"] == rid
        assert workflows.channel_events(g, consumer="7") == [], "'>' delivers each entry once"
        # a crashed consumer re-reads what it received but never acked
        again = workflows.channel_events(g, consumer="7", pending_only=True)
        assert [e for e, _ in again] == [evs[0][0]]
        workflows.ack(g, evs[0][0])
        assert workflows.channel_events(g, consumer="7", pending_only=True) == []
        assert r.xpending(workflows.REQ, g)["pending"] == 0


def test_cli():
    with patched_client(FakeRedis()):
        code, out, _ = run_script("src/lab/platform/workflows.py", ["request", "visio_to_archimate", "art://d/a.vsdx", "art://r/q.md"])
        rid = out.strip()
        assert code == 0 and rid.startswith("wfr-")
        st = workflows.status(rid)
        assert st["inputs"] == {"diagram": "art://d/a.vsdx", "requirements": ["art://r/q.md"]}
        code, out, _ = run_script("src/lab/platform/workflows.py", ["list"])
        assert rid in out and "art://d/a.vsdx" in out and "pending" in out
        code, out, _ = run_script("src/lab/platform/workflows.py", [])
        assert rid in out
        code, out, _ = run_script("src/lab/platform/workflows.py", ["count"])
        assert out.strip() == "1"
        code, out, _ = run_script("src/lab/platform/workflows.py", ["show", rid])
        assert json.loads(out)["request_id"] == rid
        code, _, _ = run_script("src/lab/platform/workflows.py", ["request", "only-process"])       # too few args
        assert isinstance(code, str) and "workflow:requests" in code
        code, _, _ = run_script("src/lab/platform/workflows.py", ["bogus"])
        assert isinstance(code, str)


def _live():
    try:
        r = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True,
                                 socket_connect_timeout=0.5, socket_timeout=1)
        r.ping()
        return r
    except redis.RedisError:
        return None


def test_integration_pending_only_reread():
    """Real consumer-group semantics: after a crash the SAME consumer re-reads its unacked entries
    with id "0"; a different consumer name does not see them. Test-only stream name."""
    r = _live()
    if r is None:
        print("SKIP integration: redis unreachable"); return
    tag = uuid.uuid4().hex[:8]
    req = workflows.REQ
    workflows.REQ = f"{req}:test-{tag}"
    rid, g = None, workflows.GROUPS[0]
    try:
        with patched_client(r):
            rid = workflows.request("visio_to_archimate", INPUTS, "test")
            evs = workflows.channel_events(g, consumer=tag)
            assert len(evs) == 1 and evs[0][1]["request_id"] == rid
            assert workflows.channel_events(g, consumer=tag) == []
            assert workflows.channel_events(g, consumer=tag + "-other", pending_only=True) == []
            re = workflows.channel_events(g, consumer=tag, pending_only=True)
            assert [e for e, _ in re] == [evs[0][0]]
            assert workflows.mark(rid, "running", consumer=tag)["status"] == "running"
            workflows.ack(g, evs[0][0])
            assert workflows.channel_events(g, consumer=tag, pending_only=True) == []
            assert r.xpending(workflows.REQ, g)["pending"] == 0
            workflows.mark(rid, "done")
    finally:
        workflows.REQ = req
        r.delete(f"{req}:test-{tag}")
        if rid:
            r.delete(f"workflow:req:{rid}"); r.srem("workflow:pending", rid)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
