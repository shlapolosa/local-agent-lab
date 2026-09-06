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

from lab.platform import config, container
from lab.platform.contracts import MEETING_TO_TRANSCRIPT
from lab.workloads.identity import agent_headers
from lab.workloads.meeting_to_transcript.workflow import make_cfg, run_workflow
from lab.workloads.run import governed_run

SERVICE = "process-meeting-to-transcript"   # one distinct service name per business process
PROCESS = MEETING_TO_TRANSCRIPT.name        # the registry names the process; nothing re-types it
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

    The span, the trace headers, the run-log entry and the one way a run is closed are the SHARED
    skeleton (`lab.workloads.run.governed_run`). What is below is only what this process owns.

    The organiser is a real person and span attributes bypass the gateway's PII guardrail on their
    way to a collector that is public in this lab — so the span records THAT an organiser was
    supplied, never who they are.
    """
    return await governed_run(
        root, span_name="meeting-to-transcript-run", process=PROCESS,
        label=_run_label(recording), on_trace=on_trace,
        attrs={"meeting.organiser.given": bool(owner)},
        cfg=lambda c: make_cfg(credential=_cred(), traceparent=c.traceparent_header,
                               languages=config.MEETING_LANGUAGES, tracer=c.tracer,
                               root_ctx=c.root_ctx, mcp_url=c.mcp_url, run_id=c.run_id),
        run=run_workflow, inputs={"recording": recording, "owner": owner}, fields=run_fields)


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
