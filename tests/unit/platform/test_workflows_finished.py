"""`workflow:finished` — the durable append that says a run ENDED.

The request stream says a run was asked for; until this existed, anything wanting to act on a RESULT
had to poll for one. Same shape as `approvals:decisions`: one append at the single place a run is
closed, so a consumer group can react without every producer knowing who is listening.

What is worth testing here is almost entirely the failure behaviour. The happy path is one XADD; the
things that cost something are the ordering (a reader woken by the event must be able to read the
run), the isolation (announcing must never be able to fail a run that succeeded), and the two
defensive branches whose whole purpose is that a blip does not kill a consumer.

Offline: a fake Redis. Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_workflows_finished.py
"""
import redis

from fixtures.fakes import FakeRedis
from lab.platform import streams, workflows
from lab.platform.contracts import WorkflowStatus

GROUP = "test-consumer"
INPUTS = {"transcript": "art://t/x.json", "speaker_map": {"S": {"tag": "x"}}}


def _finished(r, status=WorkflowStatus.DONE.value):
    rid, _ = workflows.submit("transcript_to_minutes", INPUTS, "test", client=r)
    workflows.mark(rid, status, client=r)
    return rid


# ---------------------------------------------------------------- readable before announced
class _WakesOnPublish(FakeRedis):
    """A Redis whose publish immediately runs whatever the announcement wakes — which is what a real
    consumer does: it is woken by the XADD and reads the record back at once."""

    def __init__(self, on_publish):
        super().__init__()
        self._on_publish = on_publish

    def xadd(self, stream, fields, **kw):
        eid = super().xadd(stream, fields, **kw)
        self._on_publish(stream, fields)
        return eid


def test_a_request_is_readable_before_it_is_announced():
    """SEEN LIVE: `consumer loop error: KeyError: 'unknown request wfr-584919feed1c'`, a second
    before the identical request ran fine. `submit` published to `workflow:requests` and only then
    wrote the hash, so a consumer woken by the entry read a request that did not exist yet.

    It cost nothing that time only because the workload consumer leaves a failed entry UNACKED and
    redelivery retried it. Its approvals twin acks unconditionally and lost a run outright — same
    bug, different blast radius, which is why the ordering is a rule and not a preference."""
    seen = {}

    def woken(stream, f):
        if stream == workflows.REQ:
            seen["exists"] = bool(workflows.status(f["request_id"], client=r))

    r = _WakesOnPublish(woken)
    workflows.submit("transcript_to_minutes", INPUTS, "test", client=r)
    assert seen["exists"], "a consumer woken by the request must be able to read it"


# ---------------------------------------------------------------- what mark() publishes
def test_a_finished_run_is_announced_only_after_it_can_be_read():
    """A consumer woken by the event immediately reads the request. Announcing a result that is not
    yet readable is a race nobody would want to diagnose twice."""
    r = FakeRedis()
    rid = _finished(r)
    (_eid, fields), = r.x[workflows.DONE]
    assert fields["request_id"] == rid and fields["status"] == WorkflowStatus.DONE.value
    assert fields["process"] == "transcript_to_minutes", "the event carries ids, never the outputs"
    assert workflows.status(rid, client=r)["status"] == WorkflowStatus.DONE.value


def test_a_run_that_is_still_running_announces_nothing():
    r = FakeRedis()
    rid, _ = workflows.submit("transcript_to_minutes", INPUTS, "test", client=r)
    workflows.mark(rid, WorkflowStatus.RUNNING.value, client=r)
    assert workflows.DONE not in r.x


def test_a_failed_run_is_announced_too():
    """A consumer decides what a failure means to it — the notifier stays quiet, a dashboard would
    not. Publishing only successes would make that impossible to change later."""
    r = FakeRedis()
    _finished(r, WorkflowStatus.FAILED.value)
    assert r.x[workflows.DONE][0][1]["status"] == WorkflowStatus.FAILED.value


def test_announcing_can_never_fail_a_run_that_succeeded():
    """The isolation that matters most. `consumer.handle` marks a run FAILED from the `except` around
    this call, so an unguarded XADD that raised — an OOM'd Redis, a WRONGTYPE, a blip on the second
    round trip — would record a run that had already succeeded and published its outputs as a
    failure. A missed announcement costs a message; that would cost the truth."""
    class NoFinishedStream(FakeRedis):
        def xadd(self, stream, *a, **kw):
            if stream == workflows.DONE:
                raise redis.ResponseError("OOM command not allowed when used memory > 'maxmemory'")
            return super().xadd(stream, *a, **kw)

    r = NoFinishedStream()
    rid, _ = workflows.submit("transcript_to_minutes", INPUTS, "test", client=r)
    upd = workflows.mark(rid, WorkflowStatus.DONE.value, client=r, minutes_ref="art://m/x.json")
    assert upd["status"] == WorkflowStatus.DONE.value
    assert workflows.status(rid, client=r)["minutes_ref"] == "art://m/x.json"


def test_the_stream_is_bounded_because_nothing_reads_its_history():
    """One entry per finished run, forever, on a Redis with a fixed volume. Consumers start at `$`,
    so an old entry is only cost."""
    r = FakeRedis()
    for _ in range(3):
        _finished(r)
    assert len(r.x[workflows.DONE]) == 3
    assert workflows.DONE_MAXLEN, "a bound exists at all"
    r.x[workflows.DONE] = [("old", {})] * (workflows.DONE_MAXLEN + 5)
    _finished(r)
    assert len(r.x[workflows.DONE]) <= workflows.DONE_MAXLEN


# ---------------------------------------------------------------- reading it
def test_the_group_is_idempotent_so_a_restart_is_not_an_error():
    r = FakeRedis()
    workflows.ensure_finished_group(GROUP, r)
    workflows.ensure_finished_group(GROUP, r)          # BUSYGROUP is the expected answer, not a fault
    assert workflows.finished_events(GROUP, client=r) == []


def test_a_group_creation_error_that_is_not_busygroup_is_raised():
    """A silent swallow here would hide a real misconfiguration behind "no events ever arrive"."""
    class Broken(FakeRedis):
        def xgroup_create(self, *a, **kw):
            raise redis.ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")

    try:
        workflows.ensure_finished_group(GROUP, Broken())
    except redis.ResponseError as e:
        assert "WRONGTYPE" in str(e)
    else:
        raise AssertionError("a non-BUSYGROUP error must reach the caller")


def test_an_expired_block_is_no_events_rather_than_a_dead_consumer():
    """The rule that killed the Teams channel on its first start: a block at or above the client's
    socket timeout races the socket read, and the escaping `redis.TimeoutError` ends the process. It
    lives once now, in redis_client.blocking_read, and this is the finished stream's proof of it."""
    class SlowSocket(FakeRedis):
        def xreadgroup(self, *a, **kw):
            raise redis.TimeoutError("timed out reading from socket")

    r = SlowSocket()
    workflows.ensure_finished_group(GROUP, r)
    assert workflows.finished_events(GROUP, block_ms=5000, client=r) == []


def test_an_unacked_entry_comes_back_so_a_crashed_consumer_loses_nothing(monkeypatch):
    """`>` returns only never-delivered entries, so an entry taken and not acked would otherwise sit
    in the pending list forever, visible to nobody — how a crashed channel once stranded ten open
    approvals. This is the durability Streams were chosen over pub/sub to get."""
    r = FakeRedis()
    workflows.ensure_finished_group(GROUP, r)
    rid = _finished(r)
    assert [f["request_id"] for _e, f in workflows.finished_events(GROUP, client=r)] == [rid]
    assert workflows.finished_events(GROUP, client=r) == [], "not redelivered while it is fresh"
    monkeypatch.setattr(streams, "RECLAIM_IDLE_MS", 0)
    assert [f["request_id"] for _e, f in workflows.finished_events(GROUP, client=r)] == [rid]


def test_a_server_without_reclaim_still_gets_what_is_new():
    """Best effort, and deliberately: an older Redis should deliver new events, not nothing."""
    class NoReclaim(FakeRedis):
        def xautoclaim(self, *a, **kw):
            raise redis.ResponseError("ERR unknown command 'XAUTOCLAIM'")

    r = NoReclaim()
    workflows.ensure_finished_group(GROUP, r)
    rid = _finished(r)
    assert [f["request_id"] for _e, f in workflows.finished_events(GROUP, client=r)] == [rid]


# ---------------------------------------------------------------- annotate
def test_annotate_records_a_note_without_touching_status_or_announcing_again():
    """How a consumer of a finished run leaves a trace where a person will look. Deliberately not
    `mark()`: mark re-publishes for a finished status, so a notifier using it would feed itself its
    own failure forever."""
    r = FakeRedis()
    rid = _finished(r)
    before = len(r.x[workflows.DONE])
    workflows.annotate(rid, client=r, notify_error="OSError: connection refused")
    st = workflows.status(rid, client=r)
    assert st["notify_error"] == "OSError: connection refused"
    assert st["status"] == WorkflowStatus.DONE.value
    assert len(r.x[workflows.DONE]) == before, "a note is not a second finish"
    assert workflows.annotate(rid, client=r) == {}, "nothing to write is not a write"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
