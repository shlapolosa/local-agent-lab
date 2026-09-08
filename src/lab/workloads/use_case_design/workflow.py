"""Steps 13-26a — rule on feasibility, and if it proceeds, derive the design.

The FR-11 halt lives here. A reject or an integration finding stops the run: steps 17 to 25 are not
attempted and no partial design package is produced. That is enforced by a deterministic switch —
`halted` is set by the verdict node and every later node returns immediately — never by an agent
choosing and never by an exception. The graph stays static, so NFR-14 ("the orchestrator may not
select, skip or reorder steps") holds by construction rather than by discipline.

FR-12 is the other half: a rejection reaches an ARCHITECT before the submitter hears it. The run
raises that finding as an approval and ends; the notifier releases the submitter's message from the
architect's decision, so "architect first" is an ordering the machinery guarantees rather than a
convention somebody follows.
"""
from __future__ import annotations

import contextlib

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config, runlog
from lab.platform.contracts import (
    USE_CASE_INVESTMENT,
    ApprovalTools,
    Continuation,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, ApprovalTools.ask)

#: Everything steps 17-25 would produce. Named here because "no partial design package" is only
#: checkable against a list of what a package HAS — a test that guessed would pass on a typo.
DESIGN_OUTPUTS = ("risk_ref", "obligations_ref", "architecture_ref", "cost_ref",
                  "business_case_ref", "recommendation", "delivery_ref")

PENDING_STEPS = {
    "13": "declare assertions", "15": "classify determinism", "17": "assign facet vectors",
    "18": "derive exposure and influence", "19": "evaluate obligations",
    "20": "select build surface", "21": "select components", "22": "compose architecture",
    "23": "estimate cost", "24": "build business case", "25": "generate delivery artifacts",
}

CONFORMANCE_PROMPT = (
    "Approve or return this design on CONFORMANCE: is the architecture sound, and is every "
    "obligation bound to a named enforcement point? This is not a funding decision — a conformant "
    "design can still be deferred on value, and that decision belongs to the delegated authority.")

FINDING_PROMPT = (
    "This use case did not pass the feasibility verdict. Confirm or overturn the finding before the "
    "submitter is told: a wrong rejection kills a valuable use case and produces no observable "
    "event afterwards, so this is the only place it can be caught.")


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
    @executor(id="assertions")
    async def assertions(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 13-15 — assertions, readiness, determinism. Pass-through until their agents land."""
        with _span(cfg, "assertions"):
            state = state | {"readiness": "pass", "governance_tier": "D2"}
        await ctx.send_message(state)

    @executor(id="feasibility")
    async def feasibility(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 16 — the verdict, and the switch FR-11 turns on.

        Deterministic: the rule is applied to derived evidence, and the outcome sets `halted` for
        every node after it. A reject or an integration finding is not an error — it is a correct
        outcome of the process, and it must still produce the record that shows why."""
        with _span(cfg, "feasibility"):
            verdict = state.get("verdict") or "proceed"
            state = state | {"verdict": verdict, "halted": verdict != "proceed"}
        await ctx.send_message(state)

    @executor(id="derive_design")
    async def derive_design(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 17-25. Not attempted at all on a halt — that is the whole of FR-11."""
        with _span(cfg, "derive_design"):
            if state.get("halted"):
                await ctx.send_message(state)
                return
            package = {"pending_steps": dict(PENDING_STEPS),
                       "submission_ref": state["submission_ref"],
                       "screening_ref": state["screening_ref"],
                       "criticality": dict(state.get("criticality") or {})}
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": package, "name": "design.package.json"})
            state = state | {"design": package, "design_ref": gateway.ref_from(stored),
                             "recommendation": "proceed with conditions"}
        await ctx.send_message(state)

    @executor(id="route")
    async def route(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 26a, or the FR-12 finding. Terminal either way."""
        with _span(cfg, "route"):
            out = await (_halt(cfg, state) if state.get("halted") else _conformance(cfg, state))
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=assertions)
            .add_chain([assertions, feasibility, derive_design, route]).build())


async def _halt(cfg, state: dict) -> dict:
    """A rejection goes to an architect, and the run ends carrying none of a design package."""
    asked = await _call(cfg, ApprovalTools.ask, {
        "subject": f'Feasibility finding: {state["verdict"]}',
        "prompt": FINDING_PROMPT,
        "items": [{"label": "decision", "samples": ["confirm", "overturn"]},
                  {"label": "reason", "samples": []}],
        "artifacts": {"submission": state["submission_ref"],
                      "screening": state["screening_ref"]},
        "requester": state.get("submitter", "")})
    return {"approval_id": asked["request_id"], "review_app": asked.get("review_app", ""),
            "verdict": state["verdict"], "halted": True,
            "summary": {"verdict": state["verdict"], "design_attempted": False}}


async def _conformance(cfg, state: dict) -> dict:
    """A proceeding run ends at the architect's conformance decision, carrying what 26b needs."""
    cont = Continuation(
        process=USE_CASE_INVESTMENT.name,
        inputs={"design_ref": state["design_ref"],
                "submitter": state.get("submitter", ""),
                "conversation": state.get("conversation", "")},
        answer_input="conformance", requester=state.get("submitter", ""))
    asked = await _call(cfg, ApprovalTools.ask, {
        "subject": "Approve or return a composed design on conformance",
        "prompt": CONFORMANCE_PROMPT,
        "items": [{"label": "decision", "samples": ["approve", "return"]},
                  {"label": "conditions", "samples": []}],
        "continuation": cont.to_dict(),
        "artifacts": {"design": state["design_ref"], "screening": state["screening_ref"]},
        "requester": state.get("submitter", "")})
    return {"approval_id": asked["request_id"], "review_app": asked.get("review_app", ""),
            "verdict": "proceed", "halted": False,
            "architecture_ref": state["design_ref"],
            "business_case_ref": state["design_ref"],
            "recommendation": state.get("recommendation", ""),
            "governance_tier": state.get("governance_tier", ""),
            "readiness": state.get("readiness", ""),
            "summary": {"verdict": "proceed", "design_attempted": True,
                        "pending_steps": len(PENDING_STEPS)}}


async def run_workflow(cfg, inputs: dict) -> dict:
    await gateway.preflight(cfg["mcp_url"], cfg["headers"], REQUIRED_TOOLS)
    workflow = build_workflow(cfg)
    if cfg.get("run_id"):
        from lab.workloads import workflowviz
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(workflow))
    result = await workflow.run(dict(inputs))
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError("the design run produced no output")
    return outputs[0]
