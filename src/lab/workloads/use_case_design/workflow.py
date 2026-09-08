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
    ValuationTools,
)
from lab.workloads import gateway
from lab.workloads.usecase import agents as A
from lab.workloads.usecase.gates import run_gated
from lab.workloads.usecase.steps import DESIGN_STEPS, step_for

#: Declared on every approval this workload raises — see the screening workflow.
PROCESS = USE_CASE_DESIGN.name

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, ApprovalTools.ask,
                  DecisionTools.readiness, DecisionTools.feasibility,
                  DecisionTools.exposure, DecisionTools.obligations,
                  DecisionTools.composition,
                  ValuationTools.cost, ValuationTools.benefit)

#: The reference corpora the design exercises read. Same contract as the screening side:
#: best effort, and a step whose corpus is absent is not run.
CORPORA = {
    "determinism_criteria": ("determinism_criteria", "criteria"),
    "facet_schema": ("facet_schema", "facets"),
    "surface_enforceability": ("surface_enforceability", "matrix"),
    "ai_capability_map": ("ai_capability_map", "capabilities"),
    "price_sheet": ("price_sheet", "lines"),
}

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

PENDING_STEPS = {"25": "generate delivery artifacts"}

CONFORMANCE_PROMPT = (
    "Approve or return this design on CONFORMANCE: is the architecture sound, and is every "
    "obligation bound to a named enforcement point? This is not a funding decision — a conformant "
    "design can still be deferred on value, and that decision belongs to the delegated authority.")

FINDING_PROMPT = (
    "This use case did not pass the feasibility verdict. Confirm or overturn the finding before the "
    "submitter is told: a wrong rejection kills a valuable use case and produces no observable "
    "event afterwards, so this is the only place it can be caught.")


def make_cfg(*, credential="", mcp_url="", traceparent="", agents=None, tracer=None,
             root_ctx=None, run_id=""):
    """The ONE config contract. `agents` maps a step key to its agent; a step with no entry stays
    in `pending_steps` rather than failing the run."""
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return {"headers": headers, "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agents": dict(agents or {}), "tracer": tracer,
            "root_ctx": root_ctx, "run_id": run_id}


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


def _corpora() -> dict:
    """The published rules these exercises read, from the packaged seed.

    Read locally rather than through `reference_lookup` because they are the SAME artifacts a pin
    would serve and the corpus is not yet published — the derivations already say which source they
    used, and doing the same here would be a second, quieter claim. When the corpus is published
    this becomes a pinned read and the provenance travels with it."""
    from lab.core.usecase import seed
    out = {}
    for key, (artifact, section) in CORPORA.items():
        try:
            out[key] = seed.artifact(artifact)[section]
        except (FileNotFoundError, KeyError):
            continue
    return out


async def _agent_step(cfg, number: str, available: dict, derived: dict, pending: dict) -> None:
    """Run one design exercise if its agent and its context are both there."""
    step = step_for(number)
    agent = (cfg.get("agents") or {}).get(step.key)
    if agent is None:
        return
    needs = set(A.CONTEXT_FOR.get(step.key, ())) - set(available)
    if needs:
        pending[number] = f"{step.key} — needs {sorted(needs)}"
        return
    with _span(cfg, f"step_{number}"):
        out = await run_gated(agent, A.message(step, A.context_for(step.key, available)),
                              step=number, validator=step.validator(),
                              normalise=step.normalise, complete=step.complete)
    derived[step.key] = out
    available[step.key] = out
    pending.pop(number, None)


def _workflow_payload(state: dict, derived: dict) -> dict:
    """The facet vectors as `decision-mcp` takes them.

    Step 17's output IS the payload — the vectors it assigned, not a re-derivation of them here.
    An `id` is required and anything without one is dropped: a facet vector nobody can attach to a
    step cannot be reasoned about, and passing it would put a phantom step in the control set.
    """
    steps = [dict(v) for v in (derived.get("facet_vectors") or {}).get("steps") or []
             if str(v.get("id", "")).strip()]
    return {"steps": steps,
            "criticality": (state.get("criticality") or {}).get("criticality_class", "routine")}


async def _valuation(cfg, derived: dict, pending: dict, state: dict) -> None:
    """Steps 23 and 24 through the governed service.

    Each half runs only if its agent produced inputs, and a missing half is left PENDING rather
    than costed at zero — a Year-1 investment with no build line and a benefit with no drivers are
    both perfectly plausible numbers and both completely wrong. The benefit call is given the cost
    it must repay, which is the one direction the dependency may run: the figures were already
    fixed by the step that could not see them.
    """
    inputs = derived.get("cost_inputs")
    if inputs:
        derived["cost"] = await _call(cfg, ValuationTools.cost, {
            "resources": list(inputs.get("resources") or ()),
            "envelope": inputs.get("envelope") or "expected",
            "build_amount": float(inputs.get("build_amount") or 0.0),
            "build_provenance": inputs.get("build_provenance") or "",
            "design_version": state.get("design_ref", "")})
        pending.pop("23", None)
    else:
        pending["23"] = "estimate cost — needs the resources the design switched on, from step 23"

    evidence = derived.get("benefit_inputs")
    if evidence is None or "cost" not in derived:
        pending["24"] = ("build the business case — needs the benefit evidence from step 24 and "
                         "the cost it has to repay from step 23")
        return
    cost_model = derived["cost"]
    derived["benefit"] = await _call(cfg, ValuationTools.benefit, {
        "effort": list(evidence.get("effort") or ()),
        "role_rates": dict(state.get("role_rates") or {}),
        "quality_baseline": dict(evidence.get("quality_baseline") or {}),
        "error_costs": dict(state.get("error_costs") or {}),
        "sensitivity_flags": list(evidence.get("sensitivity_flags") or ()),
        "cited_avoided_cost": evidence.get("cited_avoided_cost"),
        "citation": evidence.get("citation") or "",
        "data_fully_digital": bool(evidence.get("data_fully_digital", True)),
        "build_cost": float((cost_model.get("build") or {}).get("amount") or 0.0),
        "monthly_run_cost": float((cost_model.get("monthly") or {}).get("expected") or 0.0),
        # Everything still open on either side reaches the verdict as a gate condition. A
        # recommendation that did not carry them would read as settled.
        "open_conditions": (list(cost_model.get("requires_input") or ())
                            + list(evidence.get("unsupplied") or ()))})
    pending.pop("24", None)


def build_workflow(cfg):
    @executor(id="readiness")
    async def readiness(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 13-14 — declare the assertions, then rule on readiness.

        Step 13 runs BEFORE the gate and its result does not feed it, which looks redundant until
        you write the assertions: they are what the use case would have to make true, and a run
        returned as not-ready is far more useful carrying them than carrying nothing. The gate
        rules on evidence either way.

        A FAIL halts the run and returns the use case with the failed gates named (FR-19). It is
        not an exception: "return to CAM phase 2 or 3" is a correct outcome, and the record that
        says which gates failed is the whole point of producing it."""
        with _span(cfg, "readiness"):
            raw = await _call(cfg, StorageTools.read_artifact, {"ref": state["screening_ref"]})
            screening = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            derived: dict = {}
            pending: dict = {}
            await _agent_step(cfg, "13",
                              {**{k: v for k, v in screening.items() if v},
                               "criticality": dict(state.get("criticality") or {})},
                              derived, pending)
            verdict = await _call(cfg, DecisionTools.readiness, {
                "gates_evidenced": gate_evidence(screening, state.get("criticality") or {}),
                "criticality": (state.get("criticality") or {}).get("criticality_class", "routine")})
            state = state | {"screening": screening, "readiness": verdict["verdict"],
                             "derived": derived, "pending": pending,
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
            derived = dict(state.get("derived") or {})
            pending = dict(state.get("pending") or {})
            await _agent_step(cfg, "15",
                              {**_corpora(),
                               **{k: v for k, v in state["screening"].items() if v}},
                              derived, pending)
            ruled = await _call(cfg, DecisionTools.feasibility,
                                feasibility_evidence(state["screening"]))
            # The governance tier is step 15's answer, not a constant. It was one while step 15 was
            # a pass-through, and a hardcoded D2 would have kept reporting D2 for a D0 use case
            # long after the step that decides it started running.
            state = state | {"verdict": ruled["verdict"], "verdict_rule": ruled["rule"],
                             "halted": bool(ruled["halts"]), "derived": derived,
                             "pending": pending, "determinism": derived.get("determinism") or {},
                             "governance_tier": (derived.get("determinism") or {})
                                                .get("governance_tier", "")}
        await ctx.send_message(state)

    @executor(id="derive_design")
    async def derive_design(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 17-22 — the risk and architecture chain. Not attempted at all on a halt.

        The order is the derivation's own and cannot be rearranged: facets (17) are assigned before
        exposure and influence are DERIVED from them (18); the obligations (19) follow from those
        classes; the build surface (20) is tested against those obligations; components (21) are
        selected against them; and the composition (22) is the union of what the facets call for.
        Every deterministic link is a governed tool, so the rule a run obeyed is the released one
        rather than a copy living here.
        """
        with _span(cfg, "derive_design"):
            if state.get("halted"):
                await ctx.send_message(state)
                return

            screening = state["screening"]
            available = {**_corpora(), **{k: v for k, v in screening.items() if v},
                         "criticality": dict(state.get("criticality") or {}),
                         "determinism": state.get("determinism") or {}}
            derived: dict = dict(state.get("derived") or {})
            pending = dict(PENDING_STEPS) | dict(state.get("pending") or {})
            available |= derived

            # 17 — the facet vector per step
            await _agent_step(cfg, "17", available, derived, pending)
            steps_payload = _workflow_payload(state, derived)

            if steps_payload["steps"]:
                # 18 — exposure and influence, DERIVED from those facets by the governed service
                risk = await _call(cfg, DecisionTools.exposure, {"workflow": steps_payload})
                derived["risk"] = risk
                # 19 — the control requirement set, and the commit invariant
                obligations = await _call(cfg, DecisionTools.obligations, {
                    "workflow": steps_payload, "conditions": dict(state.get("conditions") or {})})
                derived["obligations"] = obligations
                available["obligations"] = obligations
            else:
                pending["18"] = "derive exposure and influence — needs a facet vector per step"
                pending["19"] = "evaluate obligations — needs a facet vector per step"

            # 20 and 21 — the surface, then the components, both against those obligations
            await _agent_step(cfg, "20", available, derived, pending)
            await _agent_step(cfg, "21", available, derived, pending)

            # 22 — the composition. Its topology comes from step 20 because that is where the
            # question "who owns control flow at runtime" is actually answered.
            topology = (derived.get("build_surface") or {}).get("topology", "")
            if steps_payload["steps"] and topology:
                derived["composition"] = await _call(cfg, DecisionTools.composition, {
                    "workflow": steps_payload, "topology": topology,
                    "conditions": dict(state.get("conditions") or {}),
                    "obligations_required": list((derived.get("obligations") or {})
                                                 .get("guardrails") or ())})
                available["composition"] = derived["composition"]
                pending.pop("22", None)
            else:
                pending["22"] = "compose architecture — needs a topology from step 20"

            # 23 and 24 — cost, then value. The agents choose WHAT is costed and WHAT evidences
            # the benefit; the arithmetic is `valuation-mcp`'s, against a versioned price sheet.
            # The order is not cosmetic: a benefit sized after seeing the investment it has to
            # clear is not evidence, so step 24 reads the submission and never the cost.
            await _agent_step(cfg, "23", available, derived, pending)
            await _agent_step(cfg, "24", available, derived, pending)
            await _valuation(cfg, derived, pending, state)

            package = {"pending_steps": pending,
                       "submission_ref": state["submission_ref"],
                       "screening_ref": state["screening_ref"],
                       "criticality": dict(state.get("criticality") or {}),
                       **derived}
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": package, "name": "design.package.json"})
            # The recommendation is step 24's verdict where there is one. While the valuation is
            # pending it says so, rather than defaulting to the answer that sounds safest — an
            # unearned "proceed with conditions" is still a proceed to whoever reads the summary.
            recommendation = ((derived.get("benefit") or {}).get("recommendation") or {})
            state = state | {"design": package, "design_ref": gateway.ref_from(stored),
                             "recommendation": recommendation.get("verdict", ""),
                             "recommendation_rationale": recommendation.get("rationale", "")}
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
            "risk_ref": state["design_ref"] if (state.get("design") or {}).get("risk") else "",
            "obligations_ref": (state["design_ref"]
                                if (state.get("design") or {}).get("obligations") else ""),
            "recommendation": state.get("recommendation", ""),
            "cost_ref": state["design_ref"] if (state.get("design") or {}).get("cost") else "",
            # Both refs point at the one package, but they are named separately and each is empty
            # until its own step ran. A business_case_ref that is always set means the investment
            # board is handed a link to a case that has no benefit side in it.
            "business_case_ref": (state["design_ref"]
                                  if (state.get("design") or {}).get("benefit") else ""),
            "governance_tier": state.get("governance_tier", ""),
            "readiness": state.get("readiness", ""),
            "summary": {"verdict": "proceed", "design_attempted": True,
                        "pending_steps": len((state.get("design") or {}).get("pending_steps")
                                             or ())}}


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
