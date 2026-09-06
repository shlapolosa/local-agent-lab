"""One governed run — the skeleton every workload host shares.

The sibling of `lab.workloads.consumer.serve`, which already does this for the poll loop. What a
host does around its workflow is identical in all three: open the root span, publish the trace id,
inject W3C headers so the gateway's and the MCP servers' spans join THIS trace, register the run on
the board, run the graph, and close the run exactly once whether it succeeded or raised.

It was copied instead, and the copy had already drifted: `runlog.start` used to default `process=` to
one workload's name, so the two later hosts had to remember to pass it and the board mislabelled the
rows of the one that forgot. A fourth workload would have started from whichever copy it was shown.

What a host still owns is only what is genuinely its own — its span name and attributes, its process
identity, the label a person reads on the Runs board, how it builds its config, its inputs, and which
of its outputs belong on the board. Everything else is here, once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from opentelemetry import propagate, trace

from lab.platform import runlog


@dataclass(frozen=True)
class RunContext:
    """What the skeleton has established by the time a host builds its config.

    `traceparent` is the header MAP and `traceparent_header` the single header value: hosts want one
    or the other, and deriving it here stops each of them deriving it slightly differently.
    """

    trace_id: str
    run_id: str
    traceparent: dict
    tracer: Any
    root_ctx: Any
    mcp_url: str

    @property
    def traceparent_header(self) -> str:
        return self.traceparent.get("traceparent", "")


async def governed_run(root, *, span_name: str, process: str, label: str,
                       cfg: Callable[[RunContext], dict],
                       run: Callable[[dict, dict], Awaitable[dict]],
                       inputs: dict,
                       fields: Callable[[dict], dict] | None = None,
                       attrs: dict | None = None,
                       on_trace: Callable[[str], None] | None = None) -> dict:
    """Run one workflow under a root span and a run-log entry. Returns its output plus `trace_id`.

    `root` is the process container — the tracer and Redis come from it, so a host never builds
    either. `attrs` are span attributes: COUNTS AND SHAPES ONLY, because a span reaches a collector
    the gateway's PII guardrail never sees, and in this lab that collector is public.

    `on_trace(trace_id)` fires as soon as the span exists rather than when the run ends, so a
    consumer can publish the id and a reviewer can watch a 600-second run live instead of after it.

    The run is closed in exactly ONE place either way — `runlog.finish_from` — and a failure is
    re-raised after it is recorded, so the caller still decides what a failed run means.
    """
    tr, r = root.tracer(), root.redis()
    with tr.start_as_current_span(span_name) as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        span.set_attribute("lab.trace_id", trace_id)
        for k, v in (attrs or {}).items():
            span.set_attribute(k, v)
        if on_trace:
            on_trace(trace_id)
        traceparent: dict = {}
        propagate.inject(traceparent)
        ctx = RunContext(trace_id=trace_id, run_id=trace_id, traceparent=traceparent, tracer=tr,
                         root_ctx=trace.set_span_in_context(span),
                         mcp_url=root.config.gateway_mcp_url())
        runlog.start(ctx.run_id, input=label, process=process, trace_id=trace_id, client=r)
        try:
            out = await run(cfg(ctx), inputs)
        except Exception as e:
            runlog.finish_from(ctx.run_id, e, client=r)
            raise
        runlog.finish_from(ctx.run_id, client=r, **(fields(out) if fields else {}))
    return {**out, "trace_id": trace_id}
