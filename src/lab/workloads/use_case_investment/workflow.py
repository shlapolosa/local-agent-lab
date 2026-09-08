"""Step 26b — assemble the investment package and route it to the authority that can fund it.

Its own process because conformance and investment are two decisions on one package, taken by two
people against two questions. An architect approving a design does not thereby approve the spend it
implies, and where the investment falls below the delegated threshold the architect takes both — but
they are still RECORDED separately, which is why they are separate approvals rather than one card
with two buttons.
"""
from __future__ import annotations

import contextlib

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config, runlog
from lab.platform.contracts import (
    USE_CASE_PROVISIONING,
    ApprovalTools,
    Continuation,
    SemanticTools,
)
from lab.workloads import gateway

REQUIRED_TOOLS = (SemanticTools.store_spec, ApprovalTools.ask)

PROMPT = ("Approve, approve with conditions, or defer this INVESTMENT. Every open gate condition is "
          "listed below; a case carrying a requires-input marker cannot recommend a plain proceed. "
          "A sound design that does not repay its cost is a correct outcome and a decision not to "
          "build.")


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
    @executor(id="assemble")
    async def assemble(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Gather the financial summary, the recommendation and every open gate condition."""
        with _span(cfg, "assemble"):
            package = {"design_ref": state["design_ref"],
                       "conformance": dict(state.get("conformance") or {}),
                       "gate_conditions": list(state.get("gate_conditions") or ())}
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": package, "name": "investment.package.json"})
            state = state | {"investment_ref": gateway.ref_from(stored)}
        await ctx.send_message(state)

    @executor(id="route_investment")
    async def route_investment(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Route by investment value to the delegated authority. Terminal."""
        with _span(cfg, "route_investment"):
            cont = Continuation(
                process=USE_CASE_PROVISIONING.name,
                inputs={"investment_ref": state["investment_ref"],
                        "submitter": state.get("submitter", "")},
                answer_input="authorisation", requester=state.get("submitter", ""))
            asked = await _call(cfg, ApprovalTools.ask, {
                "subject": "Approve the investment in an approved design",
                "prompt": PROMPT,
                "items": [{"label": "decision",
                           "samples": ["approve", "approve with conditions", "defer"]},
                          {"label": "authority", "samples": []}],
                "continuation": cont.to_dict(),
                "artifacts": {"investment": state["investment_ref"],
                              "design": state["design_ref"]},
                "requester": state.get("submitter", "")})
            out = {"approval_id": asked["request_id"],
                   "review_app": asked.get("review_app", ""),
                   "investment_ref": state["investment_ref"],
                   "recommendation": state.get("recommendation", ""),
                   "authority": state.get("authority", "delegated"),
                   "summary": {"gate_conditions": len(state.get("gate_conditions") or ())}}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=assemble)
            .add_chain([assemble, route_investment]).build())


async def run_workflow(cfg, inputs: dict) -> dict:
    await gateway.preflight(cfg["mcp_url"], cfg["headers"], REQUIRED_TOOLS)
    workflow = build_workflow(cfg)
    if cfg.get("run_id"):
        from lab.workloads import workflowviz
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(workflow))
    result = await workflow.run(dict(inputs))
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError("the investment run produced no output")
    return outputs[0]
