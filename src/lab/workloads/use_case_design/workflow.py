"""Steps 13-26a — rule on readiness and feasibility, and if it proceeds, derive the design.

Two gates and a halt, and the halt is the point. A reject or an integration finding stops the run:
steps 17 to 25 are not attempted and no partial design package is produced. That is a deterministic
switch — `halted` is set by a verdict node and every later node returns immediately — never an agent
choosing and never an exception. The graph stays static, so NFR-14 ("the orchestrator may not
select, skip or reorder steps") holds by construction rather than by discipline.

**Both verdicts are ruled by `decision-mcp`, not here.** The rules live in a governed service
because they change under governance approval and are also run by conformance review; a copy in
this workload would be a second implementation of one rule set, quietly drifting.

**What the readiness gate does today is worth stating plainly.** Gate evidence is derived from what
the screening record actually contains, and while steps 3-11 are pass-throughs it contains almost
nothing — so readiness FAILS, naming the gates, exactly as FR-19 requires. That is the honest
answer: a design cannot be composed from evidence nobody derived. It is not a stub returning
"pass"; it is the gate doing its job on an incomplete record, and it will start passing as the
screening agents land, one gate at a time.
"""
from __future__ import annotations

import contextlib
import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config, runlog
from lab.platform.contracts import (
    USE_CASE_DESIGN,
    USE_CASE_INVESTMENT,
    ApprovalTools,
    Continuation,
    DecisionTools,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway

#: Declared on every approval this workload raises — see the screening workflow.
PROCESS = USE_CASE_DESIGN.name

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, ApprovalTools.ask,
                  DecisionTools.readiness, DecisionTools.feasibility)

#: Everything steps 17-25 would produce. Named here because "no partial design package" is only
#: checkable against a list of what a package HAS — a test that guessed would pass on a typo.
DESIGN_OUTPUTS = ("risk_ref", "obligations_ref", "architecture_ref", "cost_ref",
                  "business_case_ref", "recommendation", "delivery_ref")

#: Which screening output evidences which M0 gate. A gate is evidenced when the thing it asks for
#: is THERE — not when the step that should have produced it was scheduled.
GATE_EVIDENCE = {
    "A": ("coverage_map", "workflow_graph"),      # business grounding: which capability, which measure
    "B": ("ontology_delta",),                     # semantic readiness: the concepts exist and are bound
    "C": ("source_contracts",),                   # knowledge readiness: every source is contracted
    "D": ("criticality",),                        # criticality class: the human's confirmed answer
}

PENDING_STEPS = {
    "13": "declare assertions", "17": "assign facet vectors",
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


def gate_evidence(screening: dict, criticality: dict) -> dict:
    """Which M0 gates the screening record actually evidences.

    Evidence is presence, not intent: a gate whose artifact is absent is unevidenced whatever the
    record says about the step that should have produced it. Reading a `pending_steps` entry as
    "will be fine" is precisely how a readiness gate stops meaning anything."""
    available = {"criticality": criticality} | {k: v for k, v in screening.items() if v}
    return {gate: all(bool(available.get(name)) for name in names)
            for gate, names in GATE_EVIDENCE.items()}


def feasibility_evidence(screening: dict) -> dict:
    """Step 16's inputs, from the derived evidence rather than an estimate.

    Every one is FALSE until the step that derives it exists — and false is not a guess here: "no
    capability match" is the reject rule, so an undeciable use case would reject rather than
    proceed. The readiness gate stops the run before that can happen, which is why it comes first.
    """
    coverage = screening.get("coverage_map") or {}
    realisations = screening.get("realisation_match") or {}
    heat = coverage.get("heat_map") or {}
    return {"capability_matched": bool(coverage.get("matched")),
            "existing_realisation": bool(realisations.get("existing")),
            "capability_is_commodity": bool(heat.get("commodity")),
            "capability_is_mature": bool(heat.get("mature")),
            "capability_meets_target": bool(heat.get("meets_target"))}


def build_workflow(cfg):
    @executor(id="readiness")
    async def readiness(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 13-14 — declare the assertions, then rule on readiness.

        A FAIL halts the run and returns the use case with the failed gates named (FR-19). It is
        not an exception: "return to CAM phase 2 or 3" is a correct outcome, and the record that
        says which gates failed is the whole point of producing it."""
        with _span(cfg, "readiness"):
            raw = await _call(cfg, StorageTools.read_artifact, {"ref": state["screening_ref"]})
            screening = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            verdict = await _call(cfg, DecisionTools.readiness, {
                "gates_evidenced": gate_evidence(screening, state.get("criticality") or {}),
                "criticality": (state.get("criticality") or {}).get("criticality_class", "routine")})
            state = state | {"screening": screening, "readiness": verdict["verdict"],
                             "readiness_failed": list(verdict.get("failed") or ()),
                             "halted": verdict["verdict"] == "fail",
                             "verdict": "not ready" if verdict["verdict"] == "fail" else ""}
        await ctx.send_message(state)

    @executor(id="feasibility")
    async def feasibility(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 15-16 — classify determinism, then rule on feasibility. The switch FR-11 turns on."""
        with _span(cfg, "feasibility"):
            if state.get("halted"):
                await ctx.send_message(state)
                return
            ruled = await _call(cfg, DecisionTools.feasibility,
                                feasibility_evidence(state["screening"]))
            state = state | {"verdict": ruled["verdict"], "verdict_rule": ruled["rule"],
                             "halted": bool(ruled["halts"]), "governance_tier": "D2"}
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
        """Step 26a, the FR-12 finding, or a readiness return. Terminal in every case."""
        with _span(cfg, "route"):
            if state.get("readiness") == "fail":
                out = _not_ready(state)
            elif state.get("halted"):
                out = await _finding(cfg, state)
            else:
                out = await _conformance(cfg, state)
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=readiness)
            .add_chain([readiness, feasibility, derive_design, route]).build())


def _not_ready(state: dict) -> dict:
    """FR-19 — a readiness fail returns the use case, naming the gates. No architect gate: nothing
    has been rejected on merit, and there is nothing for one to overturn."""
    return {"verdict": "not ready", "halted": True,
            "readiness": "fail", "readiness_failed": list(state.get("readiness_failed") or ()),
            "summary": {"verdict": "not ready", "design_attempted": False,
                        "failed_gates": list(state.get("readiness_failed") or ())}}


async def _finding(cfg, state: dict) -> dict:
    """FR-12 — a rejection goes to an architect BEFORE the submitter hears it, and the run ends
    carrying none of a design package. The approval releases nothing: confirming a rejection must
    not start the next process."""
    asked = await _call(cfg, ApprovalTools.ask, {
        "subject": f'Feasibility finding: {state["verdict"]}',
        "prompt": FINDING_PROMPT,
        "items": [{"label": "decision", "samples": ["confirm", "overturn"]},
                  {"label": "reason", "samples": []}],
        "artifacts": {"submission": state["submission_ref"],
                      "screening": state["screening_ref"]},
        "requester": state.get("submitter", ""),
                "process": PROCESS})
    return {"approval_id": asked["request_id"], "review_app": asked.get("review_app", ""),
            "verdict": state["verdict"], "halted": True,
            "summary": {"verdict": state["verdict"], "design_attempted": False,
                        "rule": state.get("verdict_rule", "")}}


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
        "requester": state.get("submitter", ""),
                "process": PROCESS})
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
