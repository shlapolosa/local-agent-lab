"""Step 26b — assemble the investment package and route it to the authority that can fund it.

Its own process because conformance and investment are two decisions on one package, taken by two
people against two questions. An architect approving a design does not thereby approve the spend it
implies, and where the investment falls below the delegated threshold the architect takes both — but
they are still RECORDED separately, which is why they are separate approvals rather than one card
with two buttons.
"""
from __future__ import annotations

import contextlib
import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config, runlog
from lab.core.usecase import authority as delegation
from lab.platform.contracts import (
    USE_CASE_PROVISIONING,
    ApprovalTools,
    Continuation,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, ApprovalTools.ask)

#: The eight sections a business case has, in order. Read from the design package rather than
#: re-drafted: step 25 wrote them under a gate, and rewriting them here would be a second draft
#: nobody reviewed.
BUSINESS_CASE = "business_case"

PROMPT = ("Approve, approve with conditions, or defer this INVESTMENT. Every open gate condition is "
          "listed below; a case carrying a requires-input marker cannot recommend a plain proceed. "
          "A sound design that does not repay its cost is a correct outcome and a decision not to "
          "build.")


def make_cfg(*, credential="", mcp_url="", traceparent="", agent=None, tracer=None,
             root_ctx=None, run_id="", authority_table=()):
    """`authority_table` is the tenant's delegation bands, injected by the composition root. Empty
    is the DEFAULT and is honest: with no table there is no threshold that can say who may sign,
    so the routing escalates and says so."""
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return {"headers": headers, "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agent": agent, "tracer": tracer, "root_ctx": root_ctx,
            "run_id": run_id, "authority_table": tuple(authority_table or ())}


def _span(cfg, node):
    rid = cfg.get("run_id")
    return runlog.span_node(rid, node) if rid else contextlib.nullcontext()


async def _call(cfg, suffix, args):
    return (await gateway.call_tools(cfg["headers"], cfg["mcp_url"], [(suffix, args)]))[0]


def open_conditions(design: dict) -> list[str]:
    """Everything still open on either side of the case, in one list.

    Assembled from what the derivations THEMSELVES reported rather than from a summary somebody
    wrote: a cost model's gap flags, a benefit's unresolved drivers, the conditions the readiness
    gate attached, and any step that never ran. An approver has to see all four, and the one most
    likely to be quietly dropped is the last — a case whose delivery artifacts were never drafted
    looks complete right up until somebody asks for them."""
    cost = design.get("cost") or {}
    benefit = design.get("benefit") or {}
    recommendation = benefit.get("recommendation") or {}
    pending = design.get("pending_steps") or {}
    return (list(cost.get("requires_input") or ())
            + list((benefit.get("summary") or {}).get("requires_input") or ())
            + [c for c in recommendation.get("gate_conditions") or ()
               if c not in (cost.get("requires_input") or ())]
            + [f"step {number} was not completed: {why}" for number, why in sorted(pending.items())])


def build_workflow(cfg):
    @executor(id="assemble")
    async def assemble(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Gather the financial summary, the recommendation and every open gate condition.

        Read from the design package, never re-derived. The figures were computed by a governed
        service under a version-stamped price sheet, and recomputing them here would produce a
        second number for the same case with nothing to say which one an approver saw."""
        with _span(cfg, "assemble"):
            raw = await _call(cfg, StorageTools.read_artifact, {"ref": state["design_ref"]})
            design = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            benefit = design.get("benefit") or {}
            summary = benefit.get("summary") or {}
            conditions = open_conditions(design)
            package = {"design_ref": state["design_ref"],
                       "conformance": dict(state.get("conformance") or {}),
                       "business_case": (design.get("delivery_artifacts") or {}).get(BUSINESS_CASE)
                                        or [],
                       "financial_summary": summary,
                       "cost": design.get("cost") or {},
                       "recommendation": (benefit.get("recommendation") or {}),
                       "gate_conditions": conditions}
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": package, "name": "investment.package.json"})
            state = state | {"investment_ref": gateway.ref_from(stored),
                             "gate_conditions": conditions,
                             "year_one_investment": summary.get("year_one_investment"),
                             "recommendation": (benefit.get("recommendation")
                                                or {}).get("verdict", "")}
        await ctx.send_message(state)

    @executor(id="route_investment")
    async def route_investment(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Route by investment value to the delegated authority. Terminal."""
        with _span(cfg, "route_investment"):
            routing = delegation.route(state.get("year_one_investment"),
                                       cfg.get("authority_table") or (),
                                       open_conditions=state.get("gate_conditions") or ())
            cont = Continuation(
                process=USE_CASE_PROVISIONING.name,
                inputs={"investment_ref": state["investment_ref"],
                        "submitter": state.get("submitter", "")},
                answer_input="authorisation", requester=state.get("submitter", ""))
            asked = await _call(cfg, ApprovalTools.ask, {
                "subject": f"Approve an investment — {routing.authority}",
                "prompt": f"{PROMPT}\n\nRouted to: {routing.authority}. {routing.reason}.",
                "items": [{"label": "decision",
                           "samples": ["approve", "approve with conditions", "defer"]},
                          {"label": "authority", "samples": [routing.authority]}],
                "continuation": cont.to_dict(),
                "artifacts": {"investment": state["investment_ref"],
                              "design": state["design_ref"]},
                "requester": state.get("submitter", "")})
            out = {"approval_id": asked["request_id"],
                   "review_app": asked.get("review_app", ""),
                   "investment_ref": state["investment_ref"],
                   "recommendation": state.get("recommendation", ""),
                   "authority": routing.authority,
                   "summary": {"gate_conditions": len(state.get("gate_conditions") or ()),
                               "escalated": routing.escalated,
                               "routing": routing.reason}}
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
