"""The `use_case_design` host: one governed run, one trace, one run-log entry.

The composition root for this process and the only place here that reads configuration. Its OTel
service name is its own, so this stage of the pipeline is traced and audited independently.

NFR-03's sixty-minute budget spans this process and the screening one; measuring it\nmeans measuring both service names.
"""
from __future__ import annotations

import asyncio
import sys

from lab.platform import container
from lab.platform.contracts import USE_CASE_DESIGN
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run
from lab.workloads.use_case_design.workflow import make_cfg, run_workflow

SERVICE = "process-usecase-design"
PROCESS = USE_CASE_DESIGN.name
AGENT_PREFIX = "USECASE_AGENT"


def _cred() -> str:
    """This workload's bearer credential — an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """The row a reviewer follows from the Runs board to what the run produced."""
    return {"approval_id": out.get("approval_id"),
            "verdict": out.get("verdict"),
            "business_case_ref": out.get("business_case_ref")}


async def run_once(root, submission_ref: str, screening_ref: str, criticality=None, *, on_trace=None, **extra) -> dict:
    """One governed run. Span attributes are counts and shapes — a span reaches a collector this
    lab does not authenticate, so no person and no free text goes on one."""
    inputs = {"submission_ref": submission_ref, "screening_ref": screening_ref,
              "criticality": dict(criticality or {})}
    inputs.update({k: v for k, v in extra.items() if k in {"submitter", "conversation"}})
    return await governed_run(
        root, span_name="usecase-design-run", process=PROCESS,
        label=f"design {submission_ref}", on_trace=on_trace,
        attrs={"usecase.criticality.given": bool(criticality)},
        cfg=lambda c: make_cfg(credential=_cred(), traceparent=c.traceparent_header,
                               tracer=c.tracer, root_ctx=c.root_ctx, mcp_url=c.mcp_url,
                               run_id=c.run_id),
        run=run_workflow, inputs=inputs, fields=run_fields)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, *argv[:2]))
    print(f'trace {out.get("trace_id")}')
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
