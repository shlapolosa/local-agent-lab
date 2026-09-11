"""The `artifact_intake` host — the composition root for this process.

Its own OTel service name, so the fabric's intake is traced and audited independently of the run that
produced the artifact. The only place here that reads configuration; the graph takes every value as an
argument. Two agents, two identities (`contracts.AGENTS`): the classifier's credential also carries the
run's TOOL calls — it is the identity that holds the fabric's PIPELINE grant.
"""
from __future__ import annotations

import asyncio
import json
import sys

from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.platform import config, container
from lab.platform.contracts import ARTIFACT_INTAKE
from lab.workloads.artifact_intake import agents as A
from lab.workloads.artifact_intake.workflow import make_cfg, run_workflow
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run

SERVICE = "process-artifact-intake"
PROCESS = ARTIFACT_INTAKE.name
CLASSIFIER_PREFIX, SYNTHESIS_PREFIX = "CLASSIFIER_AGENT", "SYNTHESIS_AGENT"


def _cred(prefix: str) -> str:
    return agent_headers(prefix)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    """What a finished run's board row carries."""
    return {"artifact_iri": out.get("artifact_iri"), "approval_id": out.get("approval_id")}


def _label(pointer: dict) -> str:
    """A reference, never a person: the item id the pointer names."""
    ident = pointer.get("ref") or pointer.get("handle") or pointer.get("itemId") or pointer.get("workItem") or "?"
    return f"intake {str(ident).rstrip('/').split('/')[-1]}"


async def run_once(root, pointer: dict, event_id: str, *, context: str = "", produced_by: str = "",
                   requester: str = "", on_trace=None) -> dict:
    """One governed run: root span -> identities -> workflow -> a question for the owner."""
    tools_cred = _cred(CLASSIFIER_PREFIX)
    headers = {"traceparent": ""}

    def cfg(c):
        headers["traceparent"] = c.traceparent_header
        common = dict(gateway_url=config.GATEWAY_URL, model=config.FABRIC_AGENT_MODEL, headers=headers,
                      store=config.AGENT_RESPONSES_STORE)
        agents = {"classifier": A.make_agent("classifier", credential=tools_cred, **common),
                  "synthesis": A.make_agent("synthesis", credential=_cred(SYNTHESIS_PREFIX), **common)}
        return make_cfg(credential=tools_cred, traceparent=c.traceparent_header, agents=agents,
                        schemas={"classifier": A.schema("classifier"), "synthesis": A.schema("synthesis")},
                        doc_types=DocumentTypes().types(), threshold=config.FABRIC_ASSOCIATION_THRESHOLD,
                        default_label=config.FABRIC_DEFAULT_LABEL, tracer=c.tracer, root_ctx=c.root_ctx,
                        mcp_url=c.mcp_url, run_id=c.run_id)

    return await governed_run(
        root, span_name="artifact-intake-run", process=PROCESS, label=_label(pointer), on_trace=on_trace,
        # counts and shapes only — a span reaches a collector the guardrail never sees
        attrs={"fabric.source": str(pointer.get("source") or ""), "fabric.has_context": bool(context),
               "fabric.produced_by": produced_by or ""},
        cfg=cfg, run=run_workflow, fields=run_fields,
        inputs={"pointer": dict(pointer), "event_id": event_id, "context": context,
                "produced_by": produced_by, "requester": requester})


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m lab.workloads.artifact_intake.host '<pointer json>' <event_id> [context] [produced_by]",
              file=sys.stderr)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, json.loads(argv[0]), argv[1], context=argv[2] if len(argv) > 2 else "",
                               produced_by=argv[3] if len(argv) > 3 else ""))
    print(f'{out["artifact_iri"]} -> approval {out["approval_id"]} ({out["kind"]})\n  trace: {out["trace_id"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
