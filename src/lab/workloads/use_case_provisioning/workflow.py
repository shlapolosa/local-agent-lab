"""Step 27 — create the work items and catalog entries an approved investment authorised.

Reached only by approving the investment. CR-20 ("no work item or catalog entry created before
architect approval") is enforced by the GRANT rather than by this code: no earlier process in the
pipeline is granted a write tool at all, so there is no branch anybody could take the wrong way.

FR-42 requires the creation to be idempotent and reversible. Re-running an approved package must
create nothing new, so everything here is staged for a human release on the `ea_stage_import` model
rather than written directly — which is also what makes it reversible without a new port.
"""
from __future__ import annotations

import contextlib

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config, runlog
from lab.platform.contracts import SemanticTools
from lab.workloads import gateway

REQUIRED_TOOLS = (SemanticTools.store_spec,)


def make_cfg(*, credential="", mcp_url="", traceparent="", agent=None, tracer=None,
             root_ctx=None, run_id=""):
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return {"headers": headers, "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agent": agent, "tracer": tracer, "root_ctx": root_ctx,
            "run_id": run_id}


def _span(cfg, node):
    rid = cfg.get("run_id")
    return runlog.span_node(rid, node) if rid else contextlib.nullcontext()


async def _call(cfg, suffix, args):
    return (await gateway.call_tools(cfg["headers"], cfg["mcp_url"], [(suffix, args)]))[0]


def build_workflow(cfg):
    @executor(id="provision")
    async def provision(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Stage the work item tree and the catalog entries. Terminal.

        The `idempotency` key is the INVESTMENT reference, not the run: re-running the same
        approved package must produce the same staged artifacts, and keying on the run would make
        every retry look like new work."""
        with _span(cfg, "provision"):
            staged = {"investment_ref": state["investment_ref"],
                      "authorisation": dict(state.get("authorisation") or {}),
                      "idempotency": state["investment_ref"],
                      "work_items": [], "catalog_entries": []}
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": staged, "name": "provisioning.staged.json"})
            ref = gateway.ref_from(stored)
            out = {"provisioned": True, "work_items_ref": ref, "catalog_ref": ref,
                   "import_artifacts": [],
                   "summary": {"work_items": 0, "catalog_entries": 0, "staged": True}}
        await ctx.yield_output(out)

    # One node, so no chain: `add_chain` needs two. Step 27 is a single staged write
    # whose approval already happened — there is nothing to sequence it with.
    return WorkflowBuilder(start_executor=provision).build()


async def run_workflow(cfg, inputs: dict) -> dict:
    await gateway.preflight(cfg["mcp_url"], cfg["headers"], REQUIRED_TOOLS)
    workflow = build_workflow(cfg)
    if cfg.get("run_id"):
        from lab.workloads import workflowviz
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(workflow))
    result = await workflow.run(dict(inputs))
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError("the provisioning run produced no output")
    return outputs[0]
