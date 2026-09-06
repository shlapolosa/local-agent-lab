"""`lab.workloads.run.governed_run` — the skeleton every workload host shares.

Three hosts used to carry a copy of this, and the copy had already drifted: `runlog.start` defaulted
`process=` to one workload's name, so the two later hosts had to remember to pass it and the board
mislabelled the rows of the one that forgot. What is tested here is what the skeleton GUARANTEES for
every host at once — the span, the trace headers, the run-log entry, and the single way a run closes
whether it succeeded or raised.

Offline: a real in-memory tracer, a fake Redis, no gateway.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/test_run.py
"""
import asyncio

import pytest
from opentelemetry import trace as ot
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from fixtures.fakes import FakeRedis
from lab.platform import runlog
from lab.workloads.run import RunContext, governed_run


class Root:
    """The process container a host is given: the tracer and Redis come from it, never from a host."""

    def __init__(self, tracer, redis):
        self._t, self._r = tracer, redis
        self.config = type("C", (), {"gateway_mcp_url": staticmethod(lambda: "http://gw/mcp")})()

    def tracer(self):
        return self._t

    def redis(self):
        return self._r


@pytest.fixture
def root():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    r = Root(provider.get_tracer("test"), FakeRedis())
    r.exporter = exporter
    return r


async def _ok(cfg, inputs):
    return {"minutes_ref": "art://m/x.json", "seen": inputs, "cfg": cfg}


def test_a_run_gets_a_span_a_trace_id_and_a_row_on_the_board(root):
    traces = []
    out = asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="a.vsdx",
                                   cfg=lambda c: {"run_id": c.run_id}, run=_ok, inputs={"x": 1},
                                   fields=lambda o: {"minutes_ref": o["minutes_ref"]},
                                   on_trace=traces.append))
    tid = out["trace_id"]
    assert len(tid) == 32 and int(tid, 16) != 0
    assert traces == [tid], "published as soon as the span exists — a 600 s run is watched live"
    row = runlog.get(tid, client=root.redis())
    assert row["process"] == "demo" and row["input"] == "a.vsdx" and row["status"] == "done"
    assert row["minutes_ref"] == "art://m/x.json", "the host chooses what its board row carries"
    assert out["seen"] == {"x": 1}


def test_the_process_is_the_host_s_and_never_a_default(root):
    """The drift this replaced: `runlog.start` carried one workload's name as its default, so a row
    from any other host was filed under the wrong process until someone noticed."""
    asyncio.run(governed_run(root, span_name="m", process="meeting_to_transcript", label="rec.mp4",
                             cfg=lambda c: {}, run=_ok, inputs={}))
    (rid,) = [k.split(":")[-1] for k in root.redis().h if k.startswith("run:")]
    assert runlog.get(rid, client=root.redis())["process"] == "meeting_to_transcript"


def test_the_config_is_built_from_the_run_s_own_trace_context(root):
    """Everything a host needs to join its calls to THIS trace arrives as one value object, so no
    host derives the traceparent header, the run id or the gateway address for itself."""
    seen = {}
    asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="x",
                             cfg=lambda c: seen.setdefault("ctx", c) and {}, run=_ok, inputs={}))
    c: RunContext = seen["ctx"]
    assert c.run_id == c.trace_id and c.mcp_url == "http://gw/mcp"
    assert c.traceparent["traceparent"].startswith("00-") and c.trace_id in c.traceparent["traceparent"]
    assert c.traceparent_header == c.traceparent["traceparent"], "one derivation, not one per host"
    assert c.tracer is root.tracer() and c.root_ctx is not None


def test_span_attributes_are_the_host_s_counts_and_shapes(root):
    """A span reaches a collector the gateway's PII guardrail never sees, and in this lab that
    collector is public — so a host passes shapes, and the skeleton stamps the trace id."""
    asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="x",
                             attrs={"meeting.organiser.given": True, "minutes.speakers": 4},
                             cfg=lambda c: {}, run=_ok, inputs={}))
    (span,) = root.exporter.get_finished_spans()
    assert span.name == "demo-run"
    assert span.attributes["meeting.organiser.given"] is True
    assert span.attributes["minutes.speakers"] == 4
    assert span.attributes["lab.trace_id"] == format(span.get_span_context().trace_id, "032x")


def test_a_failed_run_is_closed_once_and_then_re_raised(root):
    """ONE way to close a run, and the caller still decides what a failure means — a consumer marks
    its request FAILED from the exception this lets through."""
    async def boom(cfg, inputs):
        raise RuntimeError("the gateway refused")

    with pytest.raises(RuntimeError, match="the gateway refused"):
        asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="x",
                                 cfg=lambda c: {}, run=boom, inputs={}))
    (rid,) = [k.split(":")[-1] for k in root.redis().h if k.startswith("run:")]
    row = runlog.get(rid, client=root.redis())
    assert row["status"] == "failed" and "the gateway refused" in row["error"]


def test_a_host_that_declares_no_board_fields_still_closes_its_run(root):
    out = asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="x",
                                   cfg=lambda c: {}, run=_ok, inputs={}))
    (rid,) = [k.split(":")[-1] for k in root.redis().h if k.startswith("run:")]
    assert runlog.get(rid, client=root.redis())["status"] == "done" and out["trace_id"] == rid


def test_the_root_span_is_current_while_the_workflow_runs(root):
    """The whole point of the root span: every gateway and MCP span raised inside the workflow joins
    THIS trace rather than starting one of its own."""
    seen = {}

    async def check(cfg, inputs):
        seen["trace"] = format(ot.get_current_span().get_span_context().trace_id, "032x")
        return {}

    out = asyncio.run(governed_run(root, span_name="demo-run", process="demo", label="x",
                                   cfg=lambda c: {}, run=check, inputs={}))
    assert seen["trace"] == out["trace_id"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
