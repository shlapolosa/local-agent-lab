"""src/lab/substrate/approvals.py — the human-in-the-loop gate over Redis Streams. OFFLINE by default through
tests/_fakes.FakeRedis (routed in via lab.platform.redis_client.client); the one INTEGRATION test exercises
real XREADGROUP/XACK/XPENDING semantics against the local Redis and skips cleanly when it is
unreachable (it uses test-only stream names so the lab's real approval streams are untouched)."""
import json
import sys
import time
import uuid


import redis

from fixtures.fakes import FakeRedis, patched_client, run_script
from lab.substrate import approvals


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    raise AssertionError(f"expected {exc.__name__}")


def test_request_publishes_event_hash_and_pending():
    with patched_client(FakeRedis()) as r:
        rid = approvals.request("adoit_import", "lab model", {"xml_ref": "art://a/b.xml"}, "architect", trace_id="t-1")
        assert rid.startswith("apr-") and len(rid) == 16
        assert set(g for s, g in r.groups if s == approvals.REQ) == set(approvals.CHANNELS)
        (eid, fields), = r.x[approvals.REQ]
        assert fields["request_id"] == rid and fields["status"] == "pending" and fields["trace_id"] == "t-1"
        assert json.loads(fields["payload"]) == {"xml_ref": "art://a/b.xml"}
        h = r.h[f"approvals:req:{rid}"]
        assert h["kind"] == "adoit_import" and h["subject"] == "lab model" and h["requester"] == "architect"
        assert r.s["approvals:pending"] == {rid}
        st = approvals.status(rid)
        assert st["payload"] == {"xml_ref": "art://a/b.xml"} and st["status"] == "pending"
        # no trace -> empty string, never None (hash fields are strings)
        rid2 = approvals.request("adoit_import", "second", {}, "architect")
        assert r.h[f"approvals:req:{rid2}"]["trace_id"] == ""
        assert [s["request_id"] for s in approvals.pending()] == [rid, rid2]


def test_ensure_groups_idempotent_and_other_errors_propagate():
    with patched_client(FakeRedis()) as r:
        approvals.ensure_groups()
        approvals.ensure_groups()                                  # BUSYGROUP swallowed
        assert r.calls["xgroup_create"] == 2 * len(approvals.CHANNELS)
        r.fail("xgroup_create", redis.ResponseError("ERR something else"))
        _raises(redis.ResponseError, approvals.ensure_groups, r)


def test_decide_paths():
    with patched_client(FakeRedis()) as r:
        rid = approvals.request("adoit_import", "s", {"k": 1}, "arch")
        _raises(ValueError, approvals.decide, rid, "maybe", "me", "cli")
        _raises(KeyError, approvals.decide, "apr-nope", "approve", "me", "cli")
        # update = changes requested: recorded, still pending
        f = approvals.decide(rid, "update", "reviewer", "review-app", "rename X")
        assert f["decision"] == "update" and f["comment"] == "rename X" and f["decided_at"]
        assert approvals.status(rid)["status"] == "update" and rid in r.s["approvals:pending"]
        # approve closes it
        approvals.decide(rid, "approve", "reviewer", "telegram")
        st = approvals.status(rid)
        assert st["status"] == "approve" and st["decided_by"] == "reviewer" and st["decided_via"] == "telegram"
        assert rid not in r.s["approvals:pending"] and approvals.pending() == []
        hist = approvals.history()
        assert [h["decision"] for h in hist] == ["approve", "update"], "audit log, newest first"
        assert approvals.history(limit=1)[0]["decision"] == "approve"
        # decline also closes
        rid2 = approvals.request("adoit_import", "s2", {}, "arch")
        approvals.decide(rid2, "decline", "r", "cli")
        assert rid2 not in r.s["approvals:pending"]


def test_human_decision_is_the_validated_path_every_channel_shares():
    """approvals.decide RECORDS; human_decision VALIDATES — identified actor, legal decision, a
    request still open, and a final answer CLAIMED atomically so two channels cannot both answer."""
    with patched_client(FakeRedis()) as r:
        rid = approvals.request("adoit-import", "s", {}, "arch")
        for bad in (None, "", "   "):
            _raises(ValueError, approvals.human_decision, rid, "approve", bad, "teams")
        _raises(ValueError, approvals.human_decision, rid, "maybe", "maria", "teams")
        _raises(KeyError, approvals.human_decision, "apr-nope", "approve", "maria", "teams")
        assert approvals.status(rid)["status"] == "pending" and approvals.DEC not in r.x
        # `update` = changes requested: recorded, still claimable
        assert approvals.human_decision(rid, "update", " maria ", "teams", " rename X ") == {
            "request_id": rid, "decision": "update", "actor": "maria", "channel": "teams",
            "comment": "rename X", "decided_at": approvals.status(rid)["decided_at"]}
        assert rid in r.s["approvals:pending"]
        approvals.human_decision(rid, "approve", "maria", "teams")
        _raises(ValueError, approvals.human_decision, rid, "decline", "omar", "teams")   # final is final


def test_a_lost_claim_and_a_failed_write_leave_the_request_answerable():
    with patched_client(FakeRedis()) as r:
        rid = approvals.request("adoit-import", "s", {}, "arch")
        r.s["approvals:pending"].discard(rid)                     # another channel claimed it first
        _raises(ValueError, approvals.human_decision, rid, "approve", "omar", "cli")
        assert approvals.DEC not in r.x
        r.s["approvals:pending"].add(rid)
        r.fail("xadd")                                            # the audit append fails mid-decision
        _raises(redis.ConnectionError, approvals.human_decision, rid, "approve", "maria", "cli")
        r.fail("xadd")
        _raises(redis.ConnectionError, approvals.human_decision, rid, "update", "maria", "cli", "x")
        r.fail("xadd", False)
        assert rid in r.s["approvals:pending"], "the claim is released, not swallowed"
        assert approvals.human_decision(rid, "approve", "maria", "cli")["decision"] == "approve"


def test_channel_events_each_channel_sees_every_request_and_acks():
    with patched_client(FakeRedis()) as r:
        rid = approvals.request("adoit_import", "s", {}, "arch")
        for ch in approvals.CHANNELS:
            evs = approvals.channel_events(ch)
            assert len(evs) == 1 and evs[0][1]["request_id"] == rid, ch
            assert r.xpending(approvals.REQ, ch)["pending"] == 1
            assert approvals.channel_events(ch) == [], "delivered once per channel"
            approvals.ack(ch, evs[0][0])
            assert r.xpending(approvals.REQ, ch)["pending"] == 0
        assert approvals.channel_events("review-app", consumer="2", block_ms=5, count=5) == []


def test_await_decision():
    with patched_client(FakeRedis()):
        rid = approvals.request("adoit_import", "s", {}, "arch")
        t0 = time.time()
        st = approvals.await_decision(rid, timeout_s=0.05, poll_s=0.01)      # times out -> latest state
        assert st["status"] == "pending" and time.time() - t0 < 2
        approvals.decide(rid, "update", "r", "cli")
        assert approvals.await_decision(rid, timeout_s=0.05, poll_s=0.01)["status"] == "update"
        approvals.decide(rid, "approve", "r", "cli")
        assert approvals.await_decision(rid, timeout_s=5, poll_s=0.01)["status"] == "approve"


def test_cli():
    with patched_client(FakeRedis()):
        rid = approvals.request("adoit_import", "lab model", {"k": 1}, "arch")
        code, out, _ = run_script("src/lab/substrate/approvals.py", ["list"])
        assert code == 0 and rid in out and "pending" in out and "lab model" in out
        code, out, _ = run_script("src/lab/substrate/approvals.py", [])
        assert rid in out
        code, out, _ = run_script("src/lab/substrate/approvals.py", ["count"])
        assert out.strip() == "1"
        code, out, _ = run_script("src/lab/substrate/approvals.py", ["show", rid])
        assert json.loads(out)["payload"] == {"k": 1}
        code, out, _ = run_script("src/lab/substrate/approvals.py", ["approve", rid, "looks", "good"])
        assert code == 0 and "'comment': 'looks good'" in out and "'channel': 'cli'" in out
        assert approvals.status(rid)["status"] == "approve"
        code, out, _ = run_script("src/lab/substrate/approvals.py", ["count"])
        assert out.strip() == "0"
        code, _, _ = run_script("src/lab/substrate/approvals.py", ["bogus"])
        assert isinstance(code, str) and "approvals:requests" in code, "usage text via sys.exit(__doc__)"


def _live():
    """The local Redis, or None (INTEGRATION tests skip)."""
    try:
        r = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True,
                                 socket_connect_timeout=0.5, socket_timeout=1)
        r.ping()
        return r
    except redis.RedisError:
        return None


def test_integration_streams_semantics():
    """Real XGROUP/XREADGROUP/XACK/XPENDING on the local Redis, on TEST-ONLY stream names."""
    r = _live()
    if r is None:
        print("SKIP integration: redis unreachable"); return
    tag = uuid.uuid4().hex[:8]
    req, dec = approvals.REQ, approvals.DEC
    approvals.REQ, approvals.DEC = f"{req}:test-{tag}", f"{dec}:test-{tag}"
    rid = None
    try:
        with patched_client(r):
            rid = approvals.request("adoit_import", f"it-{tag}", {"n": 1}, "test")
            seen = {ch: approvals.channel_events(ch, consumer=tag) for ch in approvals.CHANNELS}
            assert all(len(v) == 1 and v[0][1]["request_id"] == rid for v in seen.values()), seen
            ch = approvals.CHANNELS[0]
            assert r.xpending(approvals.REQ, ch)["pending"] == 1
            assert approvals.channel_events(ch, consumer=tag) == []                  # ">" delivers once
            approvals.ack(ch, seen[ch][0][0])
            assert r.xpending(approvals.REQ, ch)["pending"] == 0
            assert approvals.decide(rid, "approve", "test", "cli")["decision"] == "approve"
            assert approvals.history(5)[0]["request_id"] == rid
    finally:
        approvals.REQ, approvals.DEC = req, dec
        r.delete(f"{req}:test-{tag}", f"{dec}:test-{tag}")
        if rid:
            r.delete(f"approvals:req:{rid}"); r.srem("approvals:pending", rid)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
