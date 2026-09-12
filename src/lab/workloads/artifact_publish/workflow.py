"""The `artifact_publish` graph: a reviewed record is baselined, re-indexed and announced.

    resolve [D] -> baseline [D] -> index [D] -> finish [D]

Deterministic end to end. What the owner CONFIRMED was already promoted (S → H) by the continuation runner
when the approval was decided — with the PROMOTE grant no workload holds — so this run records the
baseline (which version was approved, by whom, when), refreshes the record's embedding and ends. Its
finished-run event is what the projector turns into a wiki page.
"""
from __future__ import annotations

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.core.semantic.fabric.catalog import describe, subject_labels
from lab.platform.contracts import ARTIFACT_PUBLISH, ApprovalTools, CollabTools, SemanticTools
from lab.workloads import gateway

PROCESS = ARTIFACT_PUBLISH.name
REQUIRED_TOOLS = (ApprovalTools.get, SemanticTools.catalog_get, SemanticTools.catalog_state, SemanticTools.embed)


def make_cfg(*, credential: str = "", mcp_url: str = "", traceparent: str = "", tracer=None, root_ctx=None,
             run_id: str = ""):
    """The ONE config contract for every host of this process."""
    from lab.platform import config
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "tracer": tracer, "root_ctx": root_ctx, "run_id": run_id}


def _describe(row: dict) -> str:
    return describe(row.get("title") or row["iri"].rsplit(":", 1)[-1], str(row.get("document_type") or ""),
                    subject_labels(row.get("links") or []))


def build_workflow(cfg):
    @executor(id="resolve")
    async def resolve(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The approval that released this run, and the record it concerns. A run released by an approval
        that is not approved is refused: the gate is the only thing that lets a record be published."""
        with gateway.node_span(cfg, "resolve"):
            approval = await gateway.call(cfg, ApprovalTools.get, {"request_id": state["approval_id"]})
            if str(approval.get("decision") or approval.get("status") or "") not in ("approve", "approved"):
                raise RuntimeError(f'approval {state["approval_id"]} is not approved '
                                   f'({approval.get("decision") or approval.get("status") or "unknown"})')
            row = await gateway.call(cfg, SemanticTools.catalog_get, {"iri": state["artifact_iri"]})
            if not row:
                raise RuntimeError(f'no catalog record {state["artifact_iri"]}')
            state = state | {"approval": approval, "row": row}
        await ctx.send_message(state)

    @executor(id="baseline")
    async def baseline(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Which source version was approved: the pointer's version, else the item's modified stamp, else
        the decision's own time. Recorded on the row and mirrored into the graph by the catalog."""
        with gateway.node_span(cfg, "baseline"):
            pointer = state["row"].get("pointer") or {}
            version = str(pointer.get("version") or "")
            if not version and pointer.get("handle"):
                try:
                    item = await gateway.call(cfg, CollabTools.item, {"handle": pointer["handle"]})
                    version = str(item.get("modified") or "")
                except Exception:                    # noqa: BLE001 — a version is evidence, not a gate
                    version = ""
            version = version or str(state["approval"].get("decided_at") or "")
            row = await gateway.call(cfg, SemanticTools.catalog_state, {
                "iri": state["artifact_iri"], "state": "published", "baseline_version": version[:64]})
            state = state | {"row": row | {"links": state["row"].get("links") or []},
                             "baseline": {"version": version[:64],
                                          # `approvals_get` reports the person as `decided_by`
                                          "approved_by": str(state["approval"].get("decided_by") or state["approval"].get("actor") or ""),
                                          "at": str(state["approval"].get("decided_at") or "")}}
        await ctx.send_message(state)

    @executor(id="index")
    async def index(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Refresh the descriptive embedding now that the facets are confirmed. Best effort: a deployment
        without an embedder still publishes."""
        with gateway.node_span(cfg, "index"):
            note = ""
            try:
                await gateway.call(cfg, SemanticTools.embed, {"iri": state["artifact_iri"], "text": _describe(state["row"])})
            except Exception as e:                    # noqa: BLE001
                note = f"{type(e).__name__}: {e}"
            state = state | {"index_note": note}
        await ctx.send_message(state)

    @executor(id="finish")
    async def finish(state: dict, ctx: WorkflowContext[dict]) -> None:
        with gateway.node_span(cfg, "finish"):
            promoted = sum(1 for l in state["row"].get("links") or [] if l.get("rung") == "H")
            # `projection_ref` is a DECLARED output the projector annotates onto the run later; the run itself
            # never writes it, so it is absent here rather than a placeholder that looks like an answer.
            await ctx.yield_output({"artifact_iri": state["artifact_iri"], "baseline": state["baseline"],
                                    "promoted": promoted, "index_note": state.get("index_note", "")})

    return WorkflowBuilder(start_executor=resolve).add_chain([resolve, baseline, index, finish]).build()


async def run_workflow(cfg, inputs: dict):
    return await gateway.run_graph(cfg, build_workflow, inputs, what="artifact publish", required=REQUIRED_TOOLS)


__all__ = ["REQUIRED_TOOLS", "PROCESS", "make_cfg", "build_workflow", "run_workflow"]
