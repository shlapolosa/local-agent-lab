"""src/lab/workloads/visio_to_archimate/devui_entry.py — the PER-RUN run-log DevUI runs now write, so a
DevUI-triggered run shows up on the review app's Runs board like a CLI or consumer run (the user
requirement: watch EVERY run from the approval UI, not only the ones you triggered).

`instrument_runs()` wraps the built Workflow's `run` so each run gets its own run id, is registered
in the run-log before it executes and closed when its event stream ends — while DevUI's own live
view keeps working (the wrapper delegates the rest of the ResponseStream API).
Offline: a fake workflow + FakeRedis; no DevUI, no gateway, no Redis server.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_devui_runlog.py (also pytest-compatible)"""
import asyncio

import pytest

from fixtures.fakes import FakeRedis
from fixtures.host import Patched, make_root
from lab.platform import runlog
from lab.workloads.visio_to_archimate import devui_entry as D
from lab.workloads.visio_to_archimate import host as H

TRACE = "ab" * 16
INPUT = {"diagram": "/var/inputs/visio_to_archimate/malaffi.vsdx#Shafafiya", "requirements": []}


class FakeStream:
    """What `Workflow.run(stream=True)` returns: an async-iterable of events, plus the rest of the
    ResponseStream API the wrapper must not hide."""

    def __init__(self, events=("e1", "e2"), error=None):
        self.events, self.error, self.final = list(events), error, "the-result"

    async def __aiter__(self):
        for e in self.events:
            yield e
        if self.error:
            raise self.error

    async def get_final_response(self):
        return self.final


class FakeWorkflow:
    """Only what the wrapper touches. `run` records how it was called and can refuse a second run,
    exactly as Agent Framework does (concurrent runs on one instance raise)."""

    def __init__(self, stream=None, result=None, error=None):
        self.calls, self._stream, self._result, self._error = [], stream, result, error

    def run(self, message=None, **kw):
        self.calls.append((message, kw))
        if self._error:
            raise self._error
        if kw.get("stream"):
            return self._stream or FakeStream()

        async def _await():
            return self._result
        return _await()


def _cfg():
    return {"run_id": None}


def _wire(wf, **kw):
    """Install the run-log wrapper against a FakeRedis; returns (cfg, redis)."""
    cfg, r = _cfg(), FakeRedis()
    D.instrument_runs(wf, cfg, TRACE, client=r, mermaid="flowchart TD\n  ba[\"BA\"]", **kw)
    return cfg, r


async def _drain(stream):
    return [e async for e in stream]


# ---------------------------------------------------------------------------- per-run ids
def test_each_devui_run_gets_its_own_run_id_and_lands_on_the_runs_board():
    wf = FakeWorkflow()
    cfg, r = _wire(wf)
    assert cfg["run_id"] is None                                    # nothing is logged until a run starts

    asyncio.run(_drain(wf.run(INPUT, stream=True)))
    first = cfg["run_id"]
    asyncio.run(_drain(wf.run(INPUT, stream=True)))
    assert first == f"{TRACE}-1" and cfg["run_id"] == f"{TRACE}-2"   # per RUN, not per session

    board = runlog.recent(10, client=r)
    assert [h["run_id"] for h in board] == [f"{TRACE}-2", f"{TRACE}-1"]
    assert runlog.active(client=r) == []                             # both closed
    h = board[0]
    assert h["status"] == "done" and h["trace_id"] == TRACE and h["process"] == "visio_to_archimate"
    assert h["input"] == "malaffi.vsdx#Shafafiya" and h["mermaid"].startswith("flowchart TD")
    assert h["host"] == D.SERVICE                                    # which host ran it


def test_the_run_is_registered_before_its_first_event_and_the_events_still_reach_devui():
    wf = FakeWorkflow(stream=FakeStream(events=["a", "b", "c"]))
    cfg, r = _wire(wf)
    stream = wf.run(INPUT, stream=True)
    assert cfg["run_id"] == f"{TRACE}-1"                              # the executors read cfg lazily
    assert runlog.get(cfg["run_id"], client=r)["status"] == "running"
    assert asyncio.run(_drain(stream)) == ["a", "b", "c"]             # DevUI's live view is untouched
    assert wf.calls == [(INPUT, {"stream": True})]


def test_the_wrapper_delegates_the_rest_of_the_response_stream_api():
    wf = FakeWorkflow()
    _wire(wf)
    stream = wf.run(INPUT, stream=True)
    assert asyncio.run(stream.get_final_response()) == "the-result"
    with pytest.raises(AttributeError):
        stream.not_a_stream_method


# ---------------------------------------------------------------------------- closing a run
def test_a_stream_that_raises_closes_the_run_as_failed_and_re_raises():
    wf = FakeWorkflow(stream=FakeStream(error=RuntimeError("gateway down")))
    cfg, r = _wire(wf)
    with pytest.raises(RuntimeError):
        asyncio.run(_drain(wf.run(INPUT, stream=True)))
    h = runlog.get(cfg["run_id"], client=r)
    assert h["status"] == "failed" and h["error"] == "RuntimeError: gateway down"


def test_a_node_failure_recorded_by_the_run_log_closes_the_run_as_failed():
    """Agent Framework may surface an executor error as an event rather than raising, so the final
    status comes from the node timeline the workflow itself wrote."""
    wf = FakeWorkflow()
    cfg, r = _wire(wf)
    stream = wf.run(INPUT, stream=True)
    runlog.node(cfg["run_id"], "ba", "start", client=r)
    runlog.node(cfg["run_id"], "ba", "fail", error="ValueError: bad diagram", client=r)
    asyncio.run(_drain(stream))
    h = runlog.get(cfg["run_id"], client=r)
    assert h["status"] == "failed" and h["error"] == "ValueError: bad diagram"


def test_a_non_streaming_run_is_awaited_and_closed():
    wf = FakeWorkflow(result="out")
    cfg, r = _wire(wf)
    assert asyncio.run(wf.run(INPUT)) == "out"
    assert runlog.get(cfg["run_id"], client=r)["status"] == "done"

    wf = FakeWorkflow(error=None)
    wf._result = None

    async def boom():
        raise KeyError("nope")
    wf.run = lambda message=None, **kw: boom()                        # the awaitable itself fails
    cfg, r = _cfg(), FakeRedis()
    D.instrument_runs(wf, cfg, TRACE, client=r)
    with pytest.raises(KeyError):
        asyncio.run(wf.run(INPUT))
    assert runlog.get(cfg["run_id"], client=r)["status"] == "failed"


def test_a_refused_concurrent_run_logs_nothing():
    """The workflow rejects a second concurrent run on the same instance — which is exactly why one
    mutable cfg per session is safe. Nothing must be written for a run that never started."""
    wf = FakeWorkflow(error=RuntimeError("Workflow is already running"))
    cfg, r = _wire(wf)
    with pytest.raises(RuntimeError):
        wf.run(INPUT, stream=True)
    assert cfg["run_id"] is None and runlog.active(client=r) == [] and runlog.recent(10, client=r) == []


# ---------------------------------------------------------------------------- labels + wiring
def test_the_input_label_is_what_a_reviewer_can_read():
    assert D._input_label(INPUT) == "malaffi.vsdx#Shafafiya"
    assert D._input_label({"requirements": []}) == "?"
    assert D._input_label("/tmp/sys.vsdx") == "sys.vsdx"
    assert D._input_label(None) == "?"


def test_build_installs_the_run_log_on_the_real_workflow():
    with Patched((H, "_cred", lambda p: f"cred-{p}"),
                 (H, "_load_schema", lambda: {"type": "object", "properties": {}})):
        wf, trace_id = D.build(make_root(D.SERVICE))
    assert "run" in vars(wf)                       # the instance shadows Workflow.run with the wrapper
    assert wf.run.__doc__ and "run-log" in wf.run.__doc__
    assert len(trace_id) == 32


# ---------------------------------------------------------------------------- the stream contract
def _response_stream(events=("a", "b"), error=None):
    """A REAL agent_framework ResponseStream — what DevUI actually gets back from `Workflow.run`."""
    from agent_framework._types import ResponseStream

    async def gen():
        for e in events:
            yield e
        if error:
            raise error
    return ResponseStream(gen(), finalizer=list)


def test_the_wrapper_closes_the_run_exactly_once_however_a_real_stream_is_consumed():
    """`ResponseStream` is iterable AND awaitable, and dunders are resolved on the TYPE — so each
    must be delegated explicitly. A missed one would leave the board row stuck on `running`."""
    closes = []
    s1 = D._LoggedStream(_response_stream(), closes.append)
    assert asyncio.run(_drain(s1)) == ["a", "b"] and closes == [None]

    async def pull_again():                         # a second pull past the end must not re-close
        with pytest.raises(StopAsyncIteration):
            await s1.__anext__()
    asyncio.run(pull_again())
    assert closes == [None]

    closes.clear()                                  # an explicit pull loop, no `async for`
    s2 = D._LoggedStream(_response_stream(), closes.append)

    async def pull():
        out = []
        while True:
            try:
                out.append(await s2.__anext__())
            except StopAsyncIteration:
                return out
    assert asyncio.run(pull()) == ["a", "b"] and closes == [None]

    closes.clear()                                  # `await stream` RESOLVES, it does not consume
    s3 = D._LoggedStream(_response_stream(), closes.append)

    async def resolve_then_iterate():
        same = await s3
        assert same is s3 and closes == []          # nothing consumed yet -> the run is still open
        return [e async for e in same]
    assert asyncio.run(resolve_then_iterate()) == ["a", "b"] and closes == [None]

    closes.clear()
    s4 = D._LoggedStream(_response_stream(error=RuntimeError("boom")), closes.append)
    with pytest.raises(RuntimeError):
        asyncio.run(_drain(s4))
    assert len(closes) == 1 and isinstance(closes[0], RuntimeError)

    closes.clear()                                  # the rest of the API is still reachable
    s5 = D._LoggedStream(_response_stream(), closes.append)
    assert asyncio.run(_drain(s5)) == ["a", "b"] and asyncio.run(s5.get_final_response()) == ["a", "b"]
    assert closes == [None]                         # and the run is closed once, not twice


def test_a_devui_checkpoint_resume_is_logged_as_a_new_run():
    """DevUI resumes with `run(stream=True, responses=…, checkpoint_id=…)` and NO message. This
    workflow has no in-graph HIL pause today, so a resume cannot happen; when it gains one, one
    logical run will show as two rows — pinned here so the change is deliberate."""
    wf = FakeWorkflow()
    cfg, r = _wire(wf)
    asyncio.run(_drain(wf.run(stream=True, responses={"q": "yes"}, checkpoint_id="c1")))
    assert wf.calls == [(None, {"stream": True, "responses": {"q": "yes"}, "checkpoint_id": "c1"})]
    assert runlog.get(cfg["run_id"], client=r)["input"] == "?"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
