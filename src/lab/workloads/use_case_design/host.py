"""The `use_case_design` host: one governed run, one trace, one run-log entry.

The composition root for this process and the only place here that reads configuration. Its OTel
service name is its own, so this stage of the pipeline is traced and audited independently.

NFR-03's sixty-minute budget spans this process and the screening one; measuring it\nmeans measuring both service names.
"""
from __future__ import annotations

import asyncio
import sys

from lab.platform import config, container
from lab.platform.contracts import USE_CASE_DESIGN
from lab.workloads.identity import agent_headers
from lab.workloads.usecase import identity as ids
from lab.workloads.run import governed_run
from lab.workloads.usecase import agents as A
from lab.workloads.usecase.steps import DESIGN_STEPS
from lab.workloads.use_case_design.workflow import make_cfg, run_workflow

SERVICE = "process-usecase-design"
PROCESS = USE_CASE_DESIGN.name
AGENT_PREFIX = "USECASE_AGENT"


def _cred() -> str:
    """This workload's bearer credential — an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def _credential_for(service: str) -> str:
    """Which identity each bounded context authenticates as.

    Its own Entra registration where one has been provisioned, and the workload's shared credential
    where one has not — so ten registrations are an operator action rather than a prerequisite, and
    a run never fails because an identity somebody intended to create does not exist yet."""
    return ids.credential_for(service, fallback=_cred())


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
        cfg=lambda c: make_cfg(
            credential=_cred(), traceparent=c.traceparent_header, tracer=c.tracer,
            root_ctx=c.root_ctx, mcp_url=c.mcp_url, run_id=c.run_id,
            # Built in the composition root, because building one reads configuration and the
            # graph below is deliberately unable to.
            agents=A.build_all(DESIGN_STEPS, credential_for=_credential_for,
                               gateway_url=config.GATEWAY_URL,
                               model=config.USECASE_AGENT_MODEL,
                               headers=c.traceparent)),
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
