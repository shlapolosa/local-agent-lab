"""src/lab/workloads/visio_to_archimate/consumer.py — the long-lived `workflow:requests` consumer:
status transitions written back per request (running -> trace id -> done/approval | failed/error),
ack after every outcome, the crash-hygiene pass over stale pending entries, the poll loop's
back-off on a Redis hiccup, SIGTERM/SIGINT stop handling — and the composition: `main()` builds the
container ONCE (container.build(SERVICE)) and every stream/hash call carries ITS Redis client.
Offline: `lab.platform.workflows`, `host.run_once` and the container factory are replaced by fakes in
the consumer's namespace (module globals looked up at call time); no Redis, no gateway.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_consumer.py   (also pytest-compatible)"""
import contextlib
import io
import runpy
import signal
import sys
import time
from types import SimpleNamespace

import pytest

from lab.platform import runlog
from lab.platform import workflows as real_workflows
from lab.platform.contracts import WorkflowRequest
from lab.workloads import consumer as base
from lab.workloads.visio_to_archimate import consumer


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch):
    """`main()` builds the real container and takes its tracer, so keep tracing off — pinned per
    test, never at import (where it leaked into every other module)."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

OUT = {"request_id": "apr-1", "review_app": "http://review.test", "xml_ref": "art://x/m.xml",
       "summary": {"elements": 2}, "trace_id": "ab" * 16}
REDIS = object()                                    # the container's Redis client, by identity


class FakeRoot:
    """The process container as the consumer sees it: `.tracer()` / `.redis()`."""
    def __init__(self):
        self.tracers = 0

    def tracer(self):
        self.tracers += 1
        return None

    def redis(self):
        return REDIS


class FakeWorkflows:
    """Records mark/ack (+ the client each call carried); `stale` feeds the crash-hygiene read, `loop`
    the poll loop (a list of batches: each item is a list of (eid, fields) or an Exception to raise)."""

    def __init__(self, stale=(), loop=(), statuses=None, unknown=()):
        self.stale, self.loop, self.statuses, self.unknown = list(stale), list(loop), dict(statuses or {}), set(unknown)
        self.marks, self.acks, self.reads, self.clients = [], [], [], []

    def channel_events(self, group, consumer="1", block_ms=0, count=1, pending_only=False, client=None):
        self.reads.append((group, consumer, block_ms, count, pending_only)); self.clients.append(client)
        if pending_only:
            return list(self.stale)
        if not self.loop:
            consumer_mod._stop = True        # nothing more to serve -> let main() leave the loop
            return []
        batch = self.loop.pop(0)
        if not self.loop:
            consumer_mod._stop = True
        if isinstance(batch, Exception):
            raise batch
        return list(batch)

    def status(self, rid, client=None):
        self.clients.append(client)
        return dict(self.statuses.get(rid, {}))

    def mark(self, rid, status, client=None, **fields):
        self.clients.append(client)
        if rid in self.unknown:
            raise KeyError(f"unknown request {rid}")
        self.marks.append((rid, status, fields))
        return fields

    def ack(self, group, eid, client=None):
        self.clients.append(client)
        self.acks.append((group, eid))


consumer_mod = consumer


def _fake_run_once(out=OUT, error=None, trace="ab" * 16):
    calls = []

    async def run_once(root, diagram, requirements, on_trace=None):
        calls.append((root, diagram, requirements))
        if on_trace:
            on_trace(trace)
        if error:
            raise error
        return dict(out)
    return run_once, calls


class _Patched:
    """Patch a name wherever it actually lives.

    The poll loop, the ack and the flush moved to `lab.workloads.consumer` when a second process
    needed them; what stayed here is this process's identity and how it unpacks its own inputs. A
    test that patched only this module would silently patch nothing, so each name is set on every
    module that defines it — and `_flush` is this module's alias for the shared `flush`.
    """

    def __init__(self, **attrs):
        self.attrs, self.saved = attrs, []

    def __enter__(self):
        for key, value in self.attrs.items():
            name = "flush" if key == "_flush" else key
            for mod in (consumer, base):
                if hasattr(mod, name):
                    self.saved.append((mod, name, getattr(mod, name)))
                    setattr(mod, name, value)
        return self

    def __exit__(self, *exc):
        for mod, name, value in reversed(self.saved):
            setattr(mod, name, value)
        return False


def _fields(rid="wfr-1", process="visio_to_archimate", diagram="art://d/sys.vsdx", reqs=("art://r/a.md",)):
    """A request event exactly as the producer publishes it (the contract's field set)."""
    return WorkflowRequest(request_id=rid, process=process, inputs={"diagram": diagram, "requirements": list(reqs)},
                           requester="tester", created_at="2026-09-04T10:00:00+00:00", created_ts="1.0").to_fields()


def test_handle_runs_the_request_and_writes_running_trace_done_then_acks_with_the_roots_client():
    wf, root = FakeWorkflows(), FakeRoot()
    run_once, calls = _fake_run_once()
    flushed = []
    with _Patched(workflows=wf, run_once=run_once, _flush=lambda: flushed.append(1)), \
            contextlib.redirect_stdout(io.StringIO()) as buf:
        consumer.handle(root, "7-0", _fields())
    assert calls == [(root, "art://d/sys.vsdx", ["art://r/a.md"])]              # the SAME root reaches run_once
    assert wf.marks == [("wfr-1", "running", {"consumer": consumer.CONSUMER}),
                        ("wfr-1", "running", {"trace_id": "ab" * 16}),
                        ("wfr-1", "done", {"approval_id": "apr-1", "review_app": "http://review.test",
                                           "xml_ref": "art://x/m.xml", "summary": {"elements": 2},
                                           "trace_id": "ab" * 16})]
    assert wf.acks == [(consumer.GROUP, "7-0")] and flushed == [1]
    assert wf.clients and all(c is REDIS for c in wf.clients)                     # every call: the container's client
    assert "request wfr-1 running: art://d/sys.vsdx + 1 doc(s)" in buf.getvalue()
    # The console line says what ran and how long it took. The approval id deliberately is NOT
    # repeated here: it is written to the request hash, the run log and the Runs board, and a log
    # line is not the audit trail — adding a hook to the shared loop for a cosmetic suffix would be
    # machinery serving a string.
    assert "request wfr-1 done in" in buf.getvalue()


def test_handle_marks_failed_with_a_bounded_error_and_still_acks():
    wf = FakeWorkflows()
    run_once, _ = _fake_run_once(error=ValueError("bad diagram " + "y" * 500))
    with _Patched(workflows=wf, run_once=run_once, _flush=lambda: None), \
            contextlib.redirect_stdout(io.StringIO()) as buf, contextlib.redirect_stderr(io.StringIO()):
        consumer.handle(FakeRoot(), "8-0", _fields(rid="wfr-2", reqs=()))
    assert [m[:2] for m in wf.marks] == [("wfr-2", "running"), ("wfr-2", "running"), ("wfr-2", "failed")]
    err = wf.marks[-1][2]["error"]
    assert err.startswith("ValueError: bad diagram") and len(err) == len("ValueError: ") + runlog.ERROR_CHARS
    assert wf.acks == [(consumer.GROUP, "8-0")]
    assert "request wfr-2 failed after" in buf.getvalue()


def test_handle_acks_and_ignores_another_workloads_request():
    wf = FakeWorkflows()
    run_once, calls = _fake_run_once()
    with _Patched(workflows=wf, run_once=run_once):
        consumer.handle(FakeRoot(), "9-0", _fields(rid="wfr-3", process="other_process"))
    assert calls == [] and wf.marks == [] and wf.acks == [(consumer.GROUP, "9-0")] and wf.clients == [REDIS]


def test_handle_rejects_an_event_that_breaks_the_request_contract():
    """A malformed event (fields missing) is an error, not a guess — the loop's catch-all logs it."""
    wf = FakeWorkflows()
    run_once, calls = _fake_run_once()
    with _Patched(workflows=wf, run_once=run_once):
        try:
            consumer.handle(FakeRoot(), "10-0", {"request_id": "wfr-4", "process": "visio_to_archimate"})
            raise AssertionError("KeyError expected")
        except KeyError:
            pass
    assert calls == [] and wf.marks == [] and wf.acks == []


def test_flush_uses_force_flush_only_when_the_provider_has_one():
    flushed = []
    with _Patched(trace=SimpleNamespace(get_tracer_provider=lambda: SimpleNamespace(force_flush=lambda: flushed.append(1)))):
        consumer._flush()
    assert flushed == [1]
    with _Patched(trace=SimpleNamespace(get_tracer_provider=lambda: object())):
        consumer._flush()                       # no force_flush -> no-op, no error


# The poll loop itself — crash hygiene, the back-off on a Redis blip, stopping on a signal — moved
# into the shared `lab.workloads.consumer` when a second business process needed it, and is tested
# there (tests/unit/workloads/test_consumer.py) rather than once per process. What stays here is
# what THIS process owns: how it unpacks its own inputs and which result key carries its approval.
def test_module_entry_point_wires_this_process_into_the_shared_loop():
    """`python -m ...consumer` must reach the shared serve loop with THIS process's identity.

    It asserts the WIRING, not the loop. The loop — crash hygiene, the back-off, stopping on a
    signal — belongs to `lab.workloads.consumer` now and is tested there against a fake Redis. This
    test previously drove the real loop and broke it out by setting a module-global `_stop`; after
    the extraction that global does not exist, and the old version simply spun forever. Which is
    worth recording: a test that hangs is far more expensive than one that fails, because the whole
    run dies with no summary and looks like a memory problem.
    """
    seen = {}

    def fake_serve(**kw):
        seen.update(kw)

    saved, real_workflows_serve = base.serve, None
    base.serve = fake_serve
    try:
        runpy.run_module("lab.workloads.visio_to_archimate.consumer", run_name="__main__",
                         alter_sys=True)
    finally:
        base.serve = saved

    assert seen["process"] == "visio_to_archimate"
    assert seen["service"] == consumer.SERVICE
    # this process supplies its own input unpacking, its output renaming and its log label
    assert callable(seen["run"]) and callable(seen["outputs"]) and callable(seen["describe"])
    assert seen["outputs"]({"request_id": "apr-1", "review_app": "http://r"}) == {
        "approval_id": "apr-1", "review_app": "http://r"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
