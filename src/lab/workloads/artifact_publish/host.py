"""The `artifact_publish` host — the composition root for this process. Deterministic: no model, ONE tool-only
identity of its own (`publish-agent`, team `fabric-publish`): it reads the decision that released it, which the
intake's agents may not, and holds nothing they hold that it does not need."""
from __future__ import annotations

import asyncio
import sys

from lab.platform import container
from lab.platform.contracts import ARTIFACT_PUBLISH
from lab.workloads.artifact_publish.workflow import make_cfg, run_workflow
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run

SERVICE = "process-artifact-publish"
PROCESS = ARTIFACT_PUBLISH.name
AGENT_PREFIX = "PUBLISH_AGENT"


def _cred() -> str:
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def run_fields(out: dict) -> dict:
    return {"artifact_iri": out.get("artifact_iri"), "baseline": out.get("baseline")}


async def run_once(root, artifact_iri: str, approval_id: str, *, on_trace=None) -> dict:
    return await governed_run(
        root, span_name="artifact-publish-run", process=PROCESS, label=f"publish {artifact_iri.rsplit(':', 1)[-1]}",
        on_trace=on_trace, attrs={"fabric.approval.given": bool(approval_id)},
        cfg=lambda c: make_cfg(credential=_cred(), traceparent=c.traceparent_header, tracer=c.tracer,
                               root_ctx=c.root_ctx, mcp_url=c.mcp_url, run_id=c.run_id),
        run=run_workflow, fields=run_fields,
        inputs={"artifact_iri": artifact_iri, "approval_id": approval_id})


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m lab.workloads.artifact_publish.host <artifact_iri> <approval_id>", file=sys.stderr)
        return 2
    out = asyncio.run(run_once(container.build(SERVICE), argv[0], argv[1]))
    print(f'{out["artifact_iri"]} published at {out["baseline"].get("version") or "?"}\n  trace: {out["trace_id"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
