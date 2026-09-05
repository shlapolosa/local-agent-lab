"""`lab.workloads.consumer` — the long-lived poll loop every business process shares.

It lived inside the first workload until a second one needed it. What is pinned here is the
behaviour that would otherwise be re-derived (and got wrong) per process: writing every DECLARED
output back, crash hygiene on restart, acking whatever happens, and stopping on a signal rather than
being killed mid-write.

Offline: fake Redis, fake container, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/test_consumer.py
"""
import signal
from types import SimpleNamespace

import pytest

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import PROCESSES, WorkflowStatus
from lab.workloads import consumer as base

PROCESS = "visio_to_archimate"
GROUP = PROCESSES[PROCESS].group


@pytest.fixture
def r():
    return FakeRedis()


def _root(r):
    return SimpleNamespace(redis=lambda: r, tracer=lambda: SimpleNamespace())


def _submit(r, **inputs):
    rid, _ = workflows.submit(PROCESS, inputs or {"diagram": "art://d/a.vsdx", "requirements": []},
                              "tester", client=r)
    return rid


def _events(r):
    return list(workflows.channel_events(GROUP, "1", block_ms=0, count=10, client=r))


async def _ok(root, req, on_trace):
    on_trace("t" * 32)
    return {"trace_id": "t" * 32, "request_id": "apr-1", "review_app": "http://r",
            "xml_ref": "art://x/m.xml", "summary": {"elements": 3}}


# ------------------------------------------------------------------ the declared-output contract
def test_every_output_the_process_declares_is_written_back(r):
    """A real bug once: a host produced artifacts the consumer never recorded, so `<process>_result`
    could not hand them back. The spec is the contract, and the loop honours all of it."""
    rid = _submit(r)
    eid, fields = _events(r)[0]
    base.handle(_root(r), eid, fields, process=PROCESS, run=_ok, group=GROUP,
                outputs=lambda out: {"approval_id": out["request_id"],
                                     "review_app": out["review_app"]})
    st = workflows.status(rid, client=r)
    assert st["status"] == WorkflowStatus.DONE.value
    assert st["approval_id"] == "apr-1" and st["xml_ref"] == "art://x/m.xml"
    assert st["trace_id"] == "t" * 32


def test_the_trace_id_is_published_while_the_run_is_still_going(r):
    """So a reviewer can open the trace and watch, rather than waiting for the run to end."""
    seen = []
    rid = _submit(r)
    eid, fields = _events(r)[0]

    async def slow(root, req, on_trace):
        on_trace("a" * 32)
        seen.append(workflows.status(rid, client=r)["trace_id"])
        return {"trace_id": "a" * 32}

    base.handle(_root(r), eid, fields, process=PROCESS, run=slow, group=GROUP)
    assert seen == ["a" * 32]


def test_another_processs_request_is_acked_and_ignored(r):
    """One shared stream, one group per process: each sees every event and discards the others."""
    ran = []
    base.handle(_root(r), "9-0", {"request_id": "x", "process": "someone_else"},
                process=PROCESS, run=lambda *a: ran.append(1), group=GROUP)
    assert ran == []


def test_a_failing_run_marks_the_request_failed_and_still_acks(r):
    """The request fails; the host keeps serving. An unacked entry would be redelivered forever."""
    rid = _submit(r)
    eid, fields = _events(r)[0]

    async def boom(root, req, on_trace):
        raise RuntimeError("the gateway said no")

    base.handle(_root(r), eid, fields, process=PROCESS, run=boom, group=GROUP)
    st = workflows.status(rid, client=r)
    assert st["status"] == WorkflowStatus.FAILED.value and "gateway said no" in st["error"]
    assert _events(r) == [], "the entry was acked despite the failure"


def test_a_malformed_event_fails_loudly_rather_than_running_something_wrong(r):
    with pytest.raises(KeyError):
        base.handle(_root(r), "1-0", {"process": PROCESS}, process=PROCESS, run=_ok, group=GROUP)


def test_the_console_line_says_what_is_running_not_just_which_process(r, capsys):
    """Three requests in flight and a process name tells an operator nothing about theirs."""
    rid = _submit(r)
    eid, fields = _events(r)[0]
    base.handle(_root(r), eid, fields, process=PROCESS, run=_ok, group=GROUP,
                describe=lambda req: f"{req.diagram} + {len(req.requirements)} doc(s)")
    assert "art://d/a.vsdx + 0 doc(s)" in capsys.readouterr().out


# ------------------------------------------------------------------ the host loop
def test_serve_does_crash_hygiene_then_stops_on_a_signal(r, monkeypatch, capsys):
    """Anything this consumer took but never acked (a crash mid-run) is marked failed and acked, so
    a request is never silently stuck pending forever."""
    rid = _submit(r)
    list(workflows.channel_events(GROUP, base.consumer_name(), block_ms=0, count=10, client=r))
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    base.serve(process=PROCESS, service="svc", run=_ok, build=lambda _s: _root(r), once=True)
    assert workflows.status(rid, client=r)["status"] == WorkflowStatus.FAILED.value
    assert "restarted mid-run" in workflows.status(rid, client=r)["error"]
    assert signal.SIGTERM in handlers and signal.SIGINT in handlers
    handlers[signal.SIGTERM]()          # the handler exists and is callable — a clean stop, not a kill


def test_serve_runs_a_requests_shutdown_hook(r, monkeypatch):
    monkeypatch.setattr(signal, "signal", lambda sig, fn: None)
    done = []
    base.serve(process=PROCESS, service="svc", run=_ok, build=lambda _s: _root(r), once=True,
               shutdown=lambda: done.append(1))
    assert done == [1]


def test_a_redis_hiccup_is_logged_and_the_loop_keeps_serving(r, monkeypatch, capsys):
    """A blip must not take the host down — it logs, backs off and carries on."""
    monkeypatch.setattr(signal, "signal", lambda sig, fn: None)
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectionError("redis blipped")
        return iter([])

    monkeypatch.setattr(base.workflows, "channel_events", flaky)
    base.serve(process=PROCESS, service="svc", run=_ok, build=lambda _s: _root(r), once=True)
    assert "redis blipped" in capsys.readouterr().out


def test_the_replica_name_is_stable_and_not_a_process_selector(monkeypatch):
    """It names this REPLICA inside its group. Two processes both having a "1" do not collide,
    because the group differs — and a stable name keeps a replica's pending list across restarts.

    Pinned on `config`, not on the environment: config reads env once at ITS import, which may
    already have happened, so setting the variable here would silently do nothing.
    """
    from lab.platform import config

    assert base.consumer_name() == config.WF_CONSUMER
    monkeypatch.setattr(config, "WF_CONSUMER", "2")
    assert base.consumer_name() == "2"


def test_flush_is_a_noop_when_the_provider_cannot_flush(monkeypatch):
    monkeypatch.setattr(base.trace, "get_tracer_provider", lambda: object())
    base.flush()          # must not raise


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
