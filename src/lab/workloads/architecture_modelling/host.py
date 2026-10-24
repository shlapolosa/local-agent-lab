"""The `architecture_modelling` host: one governed run, one trace, one run-log entry.

The composition root for this process and the only place here that reads configuration. Its OTel
service name is its own, so modelling is traced and audited independently of whoever asked for it.
"""
from __future__ import annotations

import asyncio
import sys

from lab.platform import config, container
from lab.platform.contracts import ARCHITECTURE_MODELLING
from lab.platform.identity import agent_headers
from lab.workloads.architecture_modelling import agents as A
from lab.workloads.architecture_modelling.workflow import make_cfg, run_workflow
from lab.workloads.run import governed_run

SERVICE = "process-architecture-modelling"
PROCESS = ARCHITECTURE_MODELLING.name
AGENT_PREFIX = "MODELLING_AGENT"


def _cred() -> str:
    """This workload's bearer credential: an Entra JWT via MSAL, or its durable virtual key."""
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """The row a reviewer follows from the Runs board to what the run produced."""
    return {"approval_id": out.get("approval_id"), "model_ref": out.get("model_ref")}


async def run_once(root, documents, *, submitter: str = "", on_trace=None) -> dict:
    """One governed run. Span attributes are counts, never a document name or a person."""
    documents = list(documents)
    cred = _cred()

    def cfg(c):
        agent = A.make_agent(credential=cred, gateway_url=config.GATEWAY_URL,
                             model=config.MODELLING_AGENT_MODEL,
                             headers={"traceparent": c.traceparent_header},
                             store=config.AGENT_RESPONSES_STORE)
        return make_cfg(credential=cred, traceparent=c.traceparent_header, tracer=c.tracer,
                        root_ctx=c.root_ctx, mcp_url=c.mcp_url, run_id=c.run_id, agent=agent)

    return await governed_run(
        root, span_name="architecture-modelling-run", process=PROCESS,
        label=f"model from {len(documents)} document(s)", on_trace=on_trace,
        attrs={"modelling.documents": len(documents)},
        cfg=cfg, run=run_workflow, inputs={"documents": documents, "submitter": submitter},
        fields=run_fields)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, argv))
    print(f'trace {out.get("trace_id")}  model {out.get("model_ref")}  approval {out.get("approval_id")}')
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
