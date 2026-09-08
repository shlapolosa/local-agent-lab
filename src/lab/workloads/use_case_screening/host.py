"""The `use_case_screening` host: one governed run, one trace, one run-log entry.

The composition root for this process, and the only place here that reads configuration — the graph
below takes every value as an argument, which is what keeps this workload off the env-reader
ratchet.

Its OTel service name is its own, so the screening half of the pipeline can be traced and audited
independently of the design half. NFR-02's five-minute budget is a property of THIS process, and
measuring it means measuring this service name.

Run one directly:
  .venv/bin/python -m lab.workloads.use_case_screening.host <art://ref> <submitter>
"""
from __future__ import annotations

import asyncio
import sys

from lab.platform import container
from lab.platform.contracts import USE_CASE_SCREENING
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run
from lab.workloads.use_case_screening.workflow import make_cfg, run_workflow

SERVICE = "process-usecase-screening"   # one distinct service name per business process
PROCESS = USE_CASE_SCREENING.name       # the registry names the process; nothing re-types it
AGENT_PREFIX = "USECASE_AGENT"          # this workload's own identity at the gateway


def _cred() -> str:
    """This workload's bearer credential — an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """The row a reviewer follows from the Runs board to what the run produced."""
    return {"approval_id": out.get("approval_id"),
            "screening_ref": out.get("screening_ref")}


def _label(submission: str, handle: str) -> str:
    """What a person reads on the board. A reference, never the submitter — a label is rendered
    beside other people's runs."""
    return f"screening {submission or handle}"


async def run_once(root, submission: str = "", submitter: str = "", *, handle: str = "",
                   attachments=(), intake=None, conversation: str = "", on_trace=None) -> dict:
    """One governed run: root span -> identity -> workflow -> a question for an architect.

    Span attributes are counts and shapes. The submitter is a real person and a span reaches a
    collector this lab does not authenticate, so the span records THAT one was supplied.
    """
    return await governed_run(
        root, span_name="usecase-screening-run", process=PROCESS,
        label=_label(submission, handle), on_trace=on_trace,
        attrs={"usecase.submitter.given": bool(submitter),
               "usecase.attachments": len(attachments or ()),
               "usecase.intake_groups": len(intake or {}),
               "usecase.from_handle": bool(handle)},
        cfg=lambda c: make_cfg(credential=_cred(), traceparent=c.traceparent_header,
                               tracer=c.tracer, root_ctx=c.root_ctx, mcp_url=c.mcp_url,
                               run_id=c.run_id),
        run=run_workflow,
        inputs={"submission": submission, "submission_handle": handle, "submitter": submitter,
                "attachments": list(attachments or ()), "intake": dict(intake or {}),
                "conversation": conversation},
        fields=run_fields)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, argv[0], argv[1] if len(argv) > 1 else ""))
    print(f'trace {out.get("trace_id")}  approval {out.get("approval_id")}')
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
