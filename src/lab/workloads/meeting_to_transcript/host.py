"""The `meeting_to_transcript` host: one governed run, one trace, one run-log entry.

The composition root for this process. It is the only place here that reads configuration — the
graph below it takes every value as an argument, which is what keeps this workload off the
env-reader ratchet.

Its OTel service name is its own, so this process can be traced and audited independently of every
other one, exactly as the design requires.

Run one directly:
  .venv/bin/python -m lab.workloads.meeting_to_transcript.host <collab://handle> <organiser>
"""
from __future__ import annotations

import asyncio
import sys

from opentelemetry import propagate, trace

from lab.platform import config, container, runlog
from lab.workloads.identity import agent_headers
from lab.workloads.meeting_to_transcript.workflow import make_cfg, run_workflow

SERVICE = "process-meeting-to-transcript"   # one distinct service name per business process
AGENT_PREFIX = "MEETING_AGENT"              # this workload's own identity at the gateway


def _cred() -> str:
    """This workload's bearer credential — an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """What a finished run's row on the Runs board carries: the references a reviewer follows from
    the board to what the run produced. ONE mapping for every host of this process, so a row means
    the same thing whoever started the run. `None` values are dropped by `runlog.finish`."""
    return {"approval_id": out.get("request_id"), "transcript_ref": out.get("transcript_ref")}


async def run_once(root, recording: str, owner: str, on_trace=None) -> dict:
    """One governed run: root span -> identity -> workflow -> a question for the organiser.

    `root` is the process container (tracer and Redis come from it). `on_trace(trace_id)` fires as
    soon as the span exists, so the consumer can publish the trace id before the run finishes and a
    reviewer can watch it live rather than after the fact.
    """
    tr, r = root.tracer(), root.redis()
    with tr.start_as_current_span("meeting-to-transcript-run") as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        span.set_attribute("lab.trace_id", trace_id)
        # Shapes only. The organiser is a real person and span attributes bypass the gateway's PII
        # guardrail on their way to a collector that is public in this lab — so the fact that an
        # organiser was supplied is recorded, and never who they are.
        span.set_attribute("meeting.organiser.given", bool(owner))
        if on_trace:
            on_trace(trace_id)
        traceparent: dict = {}
        propagate.inject(traceparent)     # W3C headers so gateway and MCP spans join this trace
        root_ctx = trace.set_span_in_context(span)
        run_id = trace_id
        # The default process name is another workload's, so it is passed EXPLICITLY — otherwise
        # every row here is mislabelled on the board and in the run-log CLI.
        runlog.start(run_id, process="meeting_to_transcript", input=_run_label(recording),
                     trace_id=trace_id, client=r)

        cfg = make_cfg(credential=_cred(), traceparent=traceparent.get("traceparent", ""),
                       languages=config.MEETING_LANGUAGES, tracer=tr, root_ctx=root_ctx,
                       mcp_url=root.config.gateway_mcp_url(), run_id=run_id)
        try:
            out = await run_workflow(cfg, {"recording": recording, "owner": owner})
        except Exception as e:
            runlog.finish_from(run_id, e, client=r)     # ONE way to close a run
            raise
        runlog.finish_from(run_id, client=r, **run_fields(out))
    return {**out, "trace_id": trace_id}


def _run_label(recording: str) -> str:
    """What the Runs board shows for this run. A handle carries ids only, so the last segment is the
    most identifying thing available — and it is an id, not a person."""
    return recording.rstrip("/").split("/")[-1]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m lab.workloads.meeting_to_transcript.host "
              "<collab://recording/...> <organiser@example.com>", file=sys.stderr)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, argv[0], argv[1]))
    print(f'asked {out["summary"]["speakers"]} speaker(s) -> approval {out["request_id"]}\n'
          f'  review: {out.get("review_app")}\n  trace:  {out["trace_id"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
