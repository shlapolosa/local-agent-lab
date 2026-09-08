"""Step 26b — assemble the investment package and route it to the authority that can fund it.

Its own process because conformance and investment are two decisions on one package, taken by two
people against two questions. An architect approving a design does not thereby approve the spend it
implies, and where the investment falls below the delegated threshold the architect takes both — but
they are still RECORDED separately, which is why they are separate approvals rather than one card
with two buttons.
"""
from __future__ import annotations

import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config
from lab.core.usecase import authority as delegation
from lab.platform.contracts import (
    USE_CASE_INVESTMENT,
    USE_CASE_PROVISIONING,
    ApprovalTools,
    Continuation,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway

#: Declared on the approval this workload raises, like every other — so a channel serving one
#: pipeline can leave the others alone without guessing from a subject line. It was missing here,
#: on the most consequential card in the pipeline.
PROCESS = USE_CASE_INVESTMENT.name

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, ApprovalTools.ask)



PROMPT = ("Approve, approve with conditions, or defer this INVESTMENT. Every open gate condition is "
          "listed below; a case carrying a requires-input marker cannot recommend a plain proceed. "
          "A sound design that does not repay its cost is a correct outcome and a decision not to "
          "build.")


def make_cfg(*, credential="", mcp_url="", traceparent="", tracer=None,
             root_ctx=None, run_id="", authority_table=()):
    """`authority_table` is the tenant's delegation bands, injected by the composition root. Empty
    is the DEFAULT and is honest: with no table there is no threshold that can say who may sign,
    so the routing escalates and says so."""
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "tracer": tracer, "root_ctx": root_ctx,
            "run_id": run_id, "authority_table": tuple(authority_table or ())}




def open_conditions(design: dict) -> list[str]:
    """Everything still open on either side of the case, in one list.

    Assembled from what the derivations THEMSELVES reported rather than from a summary somebody
    wrote: a cost model's gap flags, a benefit's unresolved drivers, the conditions the readiness
    gate attached, and any step that never ran. An approver has to see all four, and the one most
    likely to be quietly dropped is the last — a case whose delivery artifacts were never drafted
    looks complete right up until somebody asks for them."""
    cost = design.get("cost") or {}
    benefit = design.get("benefit") or {}
    pending = design.get("pending_steps") or {}
    # ONE union, order-preserving. `benefit.recommend` already folds the benefit markers into its
    # gate conditions, so adding both listed every benefit-side marker twice — on the card a person
    # reads and in the count the routing summary reports.
    return list(dict.fromkeys(
        list(cost.get("requires_input") or ())
        + list((benefit.get("summary") or {}).get("requires_input") or ())
        + list((benefit.get("recommendation") or {}).get("gate_conditions") or ())
        + [f"step {number} was not completed: {why}" for number, why in sorted(pending.items())]))


def build_workflow(cfg):
    @executor(id="assemble")
    async def assemble(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Gather the financial summary, the recommendation and every open gate condition.

        Read from the design package, never re-derived. The figures were computed by a governed
        service under a version-stamped price sheet, and recomputing them here would produce a
        second number for the same case with nothing to say which one an approver saw."""
        with gateway.node_span(cfg, "assemble"):
            raw = await gateway.call(cfg, StorageTools.read_artifact, {"ref": state["design_ref"]})
            design = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            benefit = design.get("benefit") or {}
            summary = benefit.get("summary") or {}
            conditions = open_conditions(design)
            package = {"design_ref": state["design_ref"],
                       "conformance": dict(state.get("conformance") or {}),
                       "business_case": (design.get("delivery_artifacts") or {}).get("business_case")
                                        or [],
                       "financial_summary": summary,
                       "cost": design.get("cost") or {},
                       "recommendation": (benefit.get("recommendation") or {}),
                       "gate_conditions": conditions}
            stored = await gateway.call(cfg, SemanticTools.store_spec,
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
        with gateway.node_span(cfg, "route_investment"):
            routing = delegation.route(state.get("year_one_investment"),
                                       cfg.get("authority_table") or (),
                                       open_conditions=state.get("gate_conditions") or ())
            cont = Continuation(
                process=USE_CASE_PROVISIONING.name,
                inputs={"investment_ref": state["investment_ref"],
                        "submitter": state.get("submitter", "")},
                answer_input="authorisation", requester=state.get("submitter", ""))
            asked = await gateway.call(cfg, ApprovalTools.ask, {
                "subject": f"Approve an investment — {routing.authority}",
                "prompt": f"{PROMPT}\n\nRouted to: {routing.authority}. {routing.reason}.",
                "items": [{"label": "decision",
                           "samples": ["approve", "approve with conditions", "defer"]},
                          {"label": "authority", "samples": [routing.authority]}],
                "continuation": cont.to_dict(),
                "artifacts": {"investment": state["investment_ref"],
                              "design": state["design_ref"]},
                "requester": state.get("submitter", ""),
                "process": PROCESS})
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
    """Preflight, then the graph. Both are `gateway.run_graph`'s — the preflight rule
    in particular was paid for once by a cloud failure and should not exist per
    workload, because the copy that will lack it is the next one."""
    return await gateway.run_graph(cfg, build_workflow, inputs, what="investment",
                                   required=REQUIRED_TOOLS)
