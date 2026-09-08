"""The `use_case_provisioning` host: one governed run, one trace, one run-log entry.

The composition root for this process and the only place here that reads configuration. Its OTel
service name is its own, so this stage of the pipeline is traced and audited independently.

Nothing is created before the funding decision, and no earlier process is even granted a\nwrite tool — the control is a grant, not a branch somebody could take the wrong way.
"""
from __future__ import annotations

import asyncio
import sys

from lab.platform import container
from lab.platform.contracts import USE_CASE_PROVISIONING
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run
from lab.workloads.use_case_provisioning.workflow import make_cfg, run_workflow

SERVICE = "process-usecase-provisioning"
PROCESS = USE_CASE_PROVISIONING.name
AGENT_PREFIX = "USECASE_DELIVERY"


def _cred() -> str:
    """This workload's bearer credential — an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """The row a reviewer follows from the Runs board to what the run produced."""
    return {"provisioned": out.get("provisioned"),
            "work_items_ref": out.get("work_items_ref")}


async def run_once(root, investment_ref: str, authorisation=None, *, on_trace=None, **extra) -> dict:
    """One governed run. Span attributes are counts and shapes — a span reaches a collector this
    lab does not authenticate, so no person and no free text goes on one."""
    inputs = {"investment_ref": investment_ref, "authorisation": dict(authorisation or {})}
    inputs.update({k: v for k, v in extra.items() if k in {"submitter", "conversation"}})
    return await governed_run(
        root, span_name="usecase-provisioning-run", process=PROCESS,
        label=f"provisioning {investment_ref}", on_trace=on_trace,
        attrs={"usecase.authorisation.given": bool(authorisation)},
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
    out = asyncio.run(run_once(root, *argv[:1]))
    print(f'trace {out.get("trace_id")}')
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
