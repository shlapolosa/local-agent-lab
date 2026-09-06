"""`lab.platform.streams` — how a stream is read, and how a process reads one for its lifetime.

Both existed five times over before this, and the copies had drifted in ways nobody had decided:
two readers reclaimed what a crashed consumer abandoned and two did not; three loops survived a
Redis blip and the two approval channels did not, and had no signal handler either. Testing the
mechanics ONCE is the point — every consumer inherits what is asserted here.

Offline: a fake Redis, no network. Signals are captured, never actually raised.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_streams.py
"""
import signal as signal_mod

import pytest
import redis

from fixtures.fakes import FakeRedis
from lab.platform import streams
from lab.platform.streams import StreamGroup

STREAM = "test:events"


@pytest.fixture
def r():
    return FakeRedis()


def _add(r, **fields):
    return r.xadd(STREAM, fields)


# ---------------------------------------------------------------- the group
def test_a_group_is_created_once_and_a_restart_is_not_an_error(r):
    """BUSYGROUP is the expected answer on every start after the first."""
    g = StreamGroup(STREAM, "g")
    g.ensure(r)
    g.ensure(r)
    assert g.read(client=r) == []


def test_a_real_misconfiguration_is_not_swallowed(r):
    """Anything that is NOT BUSYGROUP must reach the caller. Hiding it turns a broken key into
    "no events ever arrive", which is the hardest possible thing to diagnose."""
    class Broken(FakeRedis):
        def xgroup_create(self, *a, **kw):
            raise redis.ResponseError("WRONGTYPE Operation against a key holding the wrong kind")

    with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
        StreamGroup(STREAM, "g").ensure(Broken())


def test_where_a_group_starts_is_the_caller_s_decision(r):
    """`0` for a stream of WORK — a host coming up must run what was queued while it was down. `$`
    for a stream of RESULTS — a consumer coming up for the first time must not announce every run
    the lab ever completed. Both are right; they are different streams."""
    _add(r, request_id="before")
    StreamGroup(STREAM, "work", start_id="0").ensure(r)
    StreamGroup(STREAM, "results").ensure(r)                        # "$" is the default
    assert [f["request_id"] for _e, f in StreamGroup(STREAM, "work", start_id="0").read(client=r)] \
        == ["before"]
    assert StreamGroup(STREAM, "results").read(client=r) == []


# ---------------------------------------------------------------- reading
def test_an_entry_is_delivered_once_until_it_is_acked(r):
    g = StreamGroup(STREAM, "g", start_id="0")
    eid = _add(r, request_id="a")
    assert [e for e, _f in g.read(client=r)] == [eid]
    assert g.read(client=r) == [], "not redelivered while it is fresh"
    g.ack(eid, r)
    assert g.read(client=r) == []


def test_an_abandoned_entry_comes_back_so_a_crash_is_a_delay_not_a_loss(r, monkeypatch):
    """`>` returns only entries never delivered to the group, so one taken and not acked would sit
    in the pending list forever, visible to nobody. That is not theoretical: a channel died on its
    first start and left ten OPEN approvals stranded from the process that replaced it."""
    g = StreamGroup(STREAM, "g", start_id="0")
    eid = _add(r, request_id="a")
    assert [e for e, _f in g.read(client=r)] == [eid]               # taken, never acked
    monkeypatch.setattr(streams, "RECLAIM_IDLE_MS", 0)
    assert [e for e, _f in g.read(client=r)] == [eid], "reclaimed"


def test_a_server_without_reclaim_still_gets_what_is_new(r):
    """Best effort, deliberately: an older Redis should deliver new events, not nothing."""
    class NoReclaim(FakeRedis):
        def xautoclaim(self, *a, **kw):
            raise redis.ResponseError("ERR unknown command 'XAUTOCLAIM'")

    rr = NoReclaim()
    g = StreamGroup(STREAM, "g", start_id="0")
    eid = rr.xadd(STREAM, {"request_id": "a"})
    assert [e for e, _f in g.read(client=rr)] == [eid]


def test_pending_only_re_reads_what_this_consumer_never_acked(r):
    """The crash-hygiene pass a process does on start — its own in-flight work, not the group's."""
    g = StreamGroup(STREAM, "g", start_id="0")
    eid = _add(r, request_id="a")
    g.read(client=r)
    assert [e for e, _f in g.read(pending_only=True, client=r)] == [eid]
    g.ack(eid, r)
    assert g.read(pending_only=True, client=r) == []


def test_an_expired_block_is_no_events_rather_than_a_dead_consumer(r):
    """A block at or above the client's socket timeout races the socket read, and the escaping
    TimeoutError killed a channel within seconds of its first start. The clamp lives in
    `redis_client.blocking_read`; this is the stream reader's proof that it is applied."""
    class SlowSocket(FakeRedis):
        def xreadgroup(self, *a, **kw):
            raise redis.TimeoutError("timed out reading from socket")

    assert StreamGroup(STREAM, "g").read(block_ms=5000, client=SlowSocket()) == []


# ---------------------------------------------------------------- serving
def _stopper(monkeypatch):
    handlers = {}
    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    return handlers, (lambda: handlers[signal_mod.SIGTERM]())


def test_it_serves_until_a_signal_and_stops_cleanly(monkeypatch, capsys):
    """A container stop sets a flag rather than killing the process where it stands, so an
    in-flight delivery finishes instead of being lost."""
    handlers, stop = _stopper(monkeypatch)
    seen, passes = [], {"n": 0}

    def read():
        passes["n"] += 1
        if passes["n"] > 2:
            stop()
        return [("e1", {"id": passes["n"]})]

    streams.serve(name="demo", ready="demo ready", read=read, handle=lambda e, f: seen.append(f["id"]))
    out = capsys.readouterr().out
    assert "demo ready" in out and "demo stopped" in out
    assert seen == [1, 2, 3] and signal_mod.SIGINT in handlers


def test_a_blip_costs_a_log_line_and_a_backoff_never_the_process(monkeypatch, capsys):
    """Each of these processes is the ONLY thing doing its job — the only thing that turns an
    approved answer into the next run, the only thing telling a human an approval is waiting."""
    _handlers, stop = _stopper(monkeypatch)
    monkeypatch.setattr(streams.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("Timeout reading from 127.0.0.1:6379")
        stop()
        return []

    streams.serve(name="demo", ready="ready", read=flaky, handle=lambda *a: None)
    assert "demo loop error" in capsys.readouterr().err and calls["n"] == 2


def test_a_failing_crash_hygiene_pass_does_not_stop_the_process_starting(monkeypatch, capsys):
    """The startup pass reads Redis too. If it throws, the process must still come up — otherwise a
    blip at the wrong moment takes the mechanism down until someone notices."""
    _handlers, stop = _stopper(monkeypatch)
    streams.serve(name="demo", ready="ready",
                  on_start=lambda: (_ for _ in ()).throw(TimeoutError("redis blipped")),
                  read=lambda: (stop(), [])[1], handle=lambda *a: None)
    assert "crash-hygiene pass failed" in capsys.readouterr().err


def test_the_hygiene_pass_runs_before_the_first_read(monkeypatch):
    _handlers, stop = _stopper(monkeypatch)
    order = []
    streams.serve(name="demo", ready="ready", on_start=lambda: order.append("hygiene"),
                  read=lambda: (order.append("read"), stop(), [])[2], handle=lambda *a: None)
    assert order == ["hygiene", "read"]


def test_a_tick_runs_every_pass_for_a_consumer_that_also_listens(monkeypatch):
    """Telegram is the one that also LISTENS — it polls its own inbound commands each pass."""
    _handlers, stop = _stopper(monkeypatch)
    ticks = []
    passes = {"n": 0}

    def read():
        passes["n"] += 1
        if passes["n"] > 1:
            stop()
        return []

    streams.serve(name="demo", ready="ready", read=read, handle=lambda *a: None,
                  tick=lambda: ticks.append(1))
    assert ticks == [1, 1]


def test_once_serves_a_single_pass(monkeypatch):
    _stopper(monkeypatch)
    passes = {"n": 0}
    streams.serve(name="demo", ready="ready", once=True, handle=lambda *a: None,
                  read=lambda: passes.update(n=passes["n"] + 1) or [])
    assert passes["n"] == 1


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
