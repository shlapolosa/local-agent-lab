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

import hashlib
import json
from typing import Any, Mapping

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.core.usecase import cost
from lab.core.usecase.model import canonical_criticality
from lab.platform import config, contracts, runlog
from lab.platform.contracts import (
    ReferenceTools,
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
from lab.workloads.usecase import reference
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.steps import step_for

#: Declared on every approval this workload raises — see the screening workflow.
PROCESS = USE_CASE_DESIGN.name

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec,
                  # ...with the arguments, not just the name — see the screening workload.
                  (ApprovalTools.ask, ("subject", "prompt", "items", "process")),
                  DecisionTools.readiness, DecisionTools.feasibility,
                  DecisionTools.exposure,
                  # ...and the pin they derive under: a decision server older than this
                  # workload would refuse `pin_id` at the call, twenty minutes in.
                  (DecisionTools.obligations, ("workflow", "pin_id", "run_id", "process", "field")),
                  (DecisionTools.composition, ("workflow", "pin_id", "run_id", "process", "field")),
                  (ValuationTools.cost, ("component_ids", "criticality", "volume", "pin_id")),
                  ValuationTools.benefit,
                  ReferenceTools.pin, (ReferenceTools.lookup, ("pin_id", "artifact_id")))

#: The reference corpora the design exercises read, as CONTEXT key -> (artifact, record type),
#: read under this run's pin. Same contract as the screening side: best effort, and a step whose
#: corpus is absent is deferred, not run on nothing.
CORPORA = {
    "determinism_criteria": ("determinism-criteria", "criterion"),
    "facet_schema": ("facet-schema", "facet"),
    "surface_enforceability": ("surface-enforceability", "obligation"),
    "ai_capability_map": ("ai-capability-map", "capability"),
    "component_catalogue": ("reference-architecture-components", "component"),
}

#: Everything this run pins: what its own steps read, plus what the governed derivations read on
#: its behalf — a derivation whose pin lacks an artifact refuses rather than answering from the
#: image, so the pin has to carry them, and it has to carry NOTHING else.
REFERENCE_ARTIFACTS = tuple(dict.fromkeys(
    [artifact for artifact, _ in CORPORA.values()] + list(DecisionTools.READS)
    + list(ValuationTools.READS)))

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
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agents": dict(agents or {}), "tracer": tracer,
            "root_ctx": root_ctx, "run_id": run_id, "process": PROCESS}


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


def _criticality(state: dict) -> str:
    """The confirmed class, refusing rather than defaulting.

    A default of "routine" is the LOWEST class, and it decides the rigour of everything downstream —
    evaluation depth, approval shape, corroboration. `criticality` is a required input and gate D
    will not pass without it, so the default was unreachable; it was also the one direction whose
    failure drops controls, which is not a default worth keeping for a branch that cannot run."""
    entry = (state.get("criticality") or {}).get("criticality_class")
    if not entry:
        raise ValueError(
            "the confirmed criticality class is missing. It is a required input of this process "
            "and the readiness gate does not pass without it — deriving from the lowest class "
            "instead would silently drop controls.")
    # The answer is a MAPPING — {label: {field: value}}, the shape the process contract validates
    # and every answering surface builds — so the class is the one value under its label, in the
    # taxonomy's own spelling: the gate compares it against a closed set.
    return canonical_criticality(contracts.answer_value(entry))


def _criticality_context(state: dict) -> dict[str, str]:
    """The answer as VALUES for the agent's context — the class canonical, the justification as
    given — so step 13 and the gate see one value spelt one way, not a transport shape."""
    out = {label: contracts.answer_value(entry)
           for label, entry in (state.get("criticality") or {}).items()}
    if "criticality_class" in out:
        out["criticality_class"] = _criticality(state)
    return out


async def _corpora(cfg, pin_id: str) -> dict:
    """The published artifacts these exercises read, under this run's pin.

    Each is read in FULL (the server lifts the limit for an artifact declared `whole`; the others
    are small catalogues) and recorded against the context key it feeds, so the reverse index says
    which design read which version of the facet schema. An artifact the read cannot serve is left
    out, and the step that needs it is deferred by name — never run on an empty corpus."""
    out = {}
    for key, (artifact, record_type) in CORPORA.items():
        try:
            got = await reference.records(cfg, pin_id, artifact, record_type=record_type, field=key)
        except Exception as exc:                            # noqa: BLE001 — a corpus is optional
            if cfg.get("run_id"):
                runlog.update(cfg["run_id"], **{f"corpus_{key}": f"unavailable: {exc}"[:200]})
            continue
        if got:
            out[key] = got
    return out


async def _agent_step(cfg, number: str, d: Derivation) -> None:
    """One design exercise, through the shared runner."""
    await d.run_step(cfg, step_for(number))


def _workflow_payload(state: dict, derived: Mapping[str, Any]) -> dict:
    """The facet vectors as `decision-mcp` takes them.

    Step 17's output IS the payload — the vectors it assigned, not a re-derivation of them here.
    An `id` is required and anything without one is dropped: a facet vector nobody can attach to a
    step cannot be reasoned about, and passing it would put a phantom step in the control set.

    The per-step `conditions` travel with the vector, which is the only place they can live: the
    published guardrail predicates ask prose questions about a STEP ("step invokes any registered
    tool"), the domain refuses to read an unanswered one as false, and a workflow-wide default
    would answer for every step at once — which is the same as not answering at all.
    """
    steps = [dict(v) for v in (derived.get("facet_vectors") or {}).get("steps") or []
             if str(v.get("id", "")).strip()]
    return {"steps": steps, "criticality": _criticality(state)}


async def _risk_and_obligations(cfg, payload: dict, d: Derivation, pin_id: str) -> None:
    """Steps 18 and 19 — exposure and influence from the facets, then the control set from those
    classes. Both refused without a facet vector: a control set derived for an empty workflow is
    valid, empty, and completely wrong. The obligations are derived UNDER THE PIN, attributed to
    the field they become."""
    if not payload["steps"]:
        d.defer("18", "derive exposure and influence — needs a facet vector per step")
        d.defer("19", "evaluate obligations — needs a facet vector per step")
        return
    d.record("risk", await gateway.call(cfg, DecisionTools.exposure, {"workflow": payload}))
    d.record("obligations", await gateway.call(cfg, DecisionTools.obligations, {
        "workflow": payload, "pin_id": pin_id, **reference.attribution(cfg, "obligations")}))


async def _compose(cfg, payload: dict, d: Derivation, pin_id: str) -> None:
    """Step 22. Its topology comes from step 20, because that is where the question "who owns
    control flow at runtime" is actually answered."""
    topology = (d.derived.get("build_surface") or {}).get("topology", "")
    if not (payload["steps"] and topology):
        d.defer("22", "compose architecture — needs a topology from step 20")
        return
    d.record("composition", await gateway.call(cfg, DecisionTools.composition, {
        "workflow": payload, "topology": topology,
        "obligations_required": list((d.derived.get("obligations") or {}).get("guardrails") or ()),
        "pin_id": pin_id, **reference.attribution(cfg, "composition")}), "22")


def design_version(derived: Mapping[str, Any]) -> str:
    """What was costed, as an identity a later reader can compare.

    Not `design_ref` — that is minted after the valuation runs, so reading it here stamped every
    cost model with an empty string. The content is the honest identity anyway: two runs that
    composed the same architecture costed the same thing whatever refs they were stored under.
    """
    body = json.dumps({"composition": derived.get("composition"),
                       "build_surface": derived.get("build_surface")},
                      sort_keys=True, ensure_ascii=False, default=str)
    return f"design-{hashlib.sha256(body.encode()).hexdigest()[:16]}"


async def _valuation(cfg, d: Derivation, state: dict) -> None:
    """Steps 23 and 24 through the governed service.

    The run cost is a JOIN: the component ids step 21 selected, the envelope the confirmed
    criticality class demands, the volume intake captured — priced by valuation-mcp against the
    catalogue at this run's pin. Nothing here is an estimate; a component with no line is a gap
    flag, a driven line with no captured volume is excluded and named. Step 23's agent contributes
    only the build cost and its provenance. Without a selection there is nothing to join, and the
    half is left PENDING rather than costed at zero. The benefit call is given the cost it must
    repay, which is the one direction the dependency may run.

    No role rates or error costs are passed. Those are finance's registries and live on
    valuation-mcp — a workload supplying its own rate card is how two submissions become
    incomparable while both look priced.
    """
    selected = (d.derived.get("component_selection") or {}).get("selected") or []
    component_ids = [str(c.get("component_id", "")).strip() for c in selected
                     if str(c.get("component_id", "")).strip()]
    if not component_ids:
        d.defer("23", "estimate cost — needs the components step 21 selected, by catalogue id")
    else:
        inputs = d.derived.get("cost_inputs") or {}
        d.record("cost", await gateway.call(cfg, ValuationTools.cost, {
            "component_ids": component_ids,
            # The confirmed CLASS travels, not an envelope: which envelope a class buys at is the
            # governed service's rule (and, next, the criticality taxonomy's own column).
            "criticality": _criticality(state),
            "volume": cost.volume_from_intake(state.get("intake") or {}),
            "build_amount": float(inputs.get("build_amount") or 0.0),
            "build_provenance": inputs.get("build_provenance") or "",
            "design_version": design_version(d.derived),
            "pin_id": state["pin_id"], **reference.attribution(cfg, "cost")}), "23")

    evidence = d.derived.get("benefit_inputs")
    cost_model = d.derived.get("cost")
    if evidence is None or cost_model is None:
        d.defer("24", "build the business case — needs the benefit evidence from step 24 and the "
                      "cost it has to repay from step 23")
        return
    d.record("benefit", await gateway.call(cfg, ValuationTools.benefit, {
        "effort": list(evidence.get("effort") or ()),
        "quality_baseline": dict(evidence.get("quality_baseline") or {}),
        "sensitivity_flags": list(evidence.get("sensitivity_flags") or ()),
        "cited_avoided_cost": evidence.get("cited_avoided_cost"),
        "citation": evidence.get("citation") or "",
        "data_fully_digital": bool(evidence.get("data_fully_digital", True)),
        "build_cost": float((cost_model.get("build") or {}).get("amount") or 0.0),
        "monthly_run_cost": float((cost_model.get("monthly") or {}).get("expected") or 0.0),
        # Everything still open on either side reaches the verdict as a gate condition. A
        # recommendation that did not carry them would read as settled.
        "open_conditions": (list(cost_model.get("requires_input") or ())
                            + list(evidence.get("unsupplied") or ()))}), "24")


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
        with gateway.node_span(cfg, "readiness"):
            raw = await gateway.call(cfg, StorageTools.read_artifact, {"ref": state["screening_ref"]})
            screening = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            # The canonical submission record, for what a person captured at INTAKE: the volume
            # assumptions the cost join positions banded lines from, and the build figure.
            record = await gateway.call(cfg, StorageTools.read_artifact,
                                        {"ref": state["submission_ref"]})
            record = record if isinstance(record, dict) else json.loads(record or "{}")
            # The pin comes FIRST and is FAIL-CLOSED — without it there is no reproducible run
            # (preflight already proved the grant, for zero tokens). An individual corpus below
            # is best-effort: the step that needs it defers by name. The versions the pin froze
            # are compared with the ones the screening run cited — recorded, not blocked on,
            # because a routine corpus release must not stall every in-flight case.
            pinned = await reference.pin(cfg, REFERENCE_ARTIFACTS,
                                         previous=screening.get("pinned_versions") or ())
            d = Derivation(available={**{k: v for k, v in screening.items() if v},
                                      "criticality": _criticality_context(state)})
            await _agent_step(cfg, "13", d)
            verdict = await gateway.call(cfg, DecisionTools.readiness, {
                "gates_evidenced": gate_evidence(screening, state.get("criticality") or {}),
                "criticality": _criticality(state)})
            state = state | {"screening": screening, "readiness": verdict["verdict"],
                             "intake": dict(record.get("intake") or {}),
                             "pin_id": pinned["pin_id"],
                             "pinned_versions": pinned["versions"],
                             "version_drift": pinned["drift"],
                             "derived": d.derived, "pending": d.pending,
                             "readiness_failed": list(verdict.get("failed") or ()),
                             "halted": verdict["verdict"] == "fail",
                             "verdict": "not ready" if verdict["verdict"] == "fail" else ""}
        await ctx.send_message(state)

    @executor(id="feasibility")
    async def feasibility(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 15-16 — classify determinism, then rule on feasibility. The switch FR-11 turns on."""
        with gateway.node_span(cfg, "feasibility"):
            if state.get("halted"):
                await ctx.send_message(state)
                return
            d = Derivation(available={**await _corpora(cfg, state["pin_id"]),
                                      **{k: v for k, v in state["screening"].items() if v}},
                           derived=dict(state.get("derived") or {}),
                           pending=dict(state.get("pending") or {}))
            await _agent_step(cfg, "15", d)
            ruled = await gateway.call(cfg, DecisionTools.feasibility,
                                feasibility_evidence(state["screening"]))
            # The governance tier is step 15's answer, not a constant. It was one while step 15 was
            # a pass-through, and a hardcoded D2 would have kept reporting D2 for a D0 use case
            # long after the step that decides it started running.
            state = state | {"verdict": ruled["verdict"], "verdict_rule": ruled["rule"],
                             "halted": bool(ruled["halts"]), "derived": d.derived,
                             "pending": d.pending,
                             "determinism": d.derived.get("determinism") or {},
                             "governance_tier": (d.derived.get("determinism") or {})
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
        with gateway.node_span(cfg, "derive_design"):
            if state.get("halted"):
                await ctx.send_message(state)
                return

            screening = state["screening"]
            d = Derivation(
                available={**await _corpora(cfg, state["pin_id"]),
                           **{k: v for k, v in screening.items() if v},
                           "intake": dict(state.get("intake") or {}),
                           "criticality": dict(state.get("criticality") or {}),
                           "determinism": state.get("determinism") or {},
                           **(state.get("derived") or {})},
                derived=dict(state.get("derived") or {}),
                pending=dict(state.get("pending") or {}))

            await _agent_step(cfg, "17", d)              # the facet vector per step
            payload = _workflow_payload(state, d.derived)
            pin_id = state["pin_id"]
            await _risk_and_obligations(cfg, payload, d, pin_id)  # 18 exposure/influence, 19 controls
            await _agent_step(cfg, "20", d)              # the build surface, against those controls
            await _agent_step(cfg, "21", d)              # the components, against those controls
            await _compose(cfg, payload, d, pin_id)      # 22 the composition
            await _agent_step(cfg, "23", d)              # what the design costs
            await _agent_step(cfg, "24", d)              # what evidences the benefit
            await _valuation(cfg, d, state)              # 23/24 arithmetic, by the governed service
            await _agent_step(cfg, "25", d)              # write down what was decided

            package = d.package(submission_ref=state["submission_ref"],
                                screening_ref=state["screening_ref"],
                                criticality=dict(state.get("criticality") or {}),
                                # What this design read, and what moved since the screening run
                                # cited it — so "screened at v0.26, designed at v0.27" is in the
                                # package a reviewer opens, per artifact.
                                pin_id=state["pin_id"],
                                pinned_versions=state["pinned_versions"],
                                version_drift=state["version_drift"])
            stored = await gateway.call(cfg, SemanticTools.store_spec,
                                        {"spec": package, "name": "design.package.json"})
            # The recommendation is step 24's verdict where there is one. While the valuation is
            # pending it says so, rather than defaulting to the answer that sounds safest — an
            # unearned "proceed with conditions" is still a proceed to whoever reads the summary.
            recommendation = (d.derived.get("benefit") or {}).get("recommendation") or {}
            state = state | {"design": package, "design_ref": gateway.ref_from(stored),
                             "recommendation": recommendation.get("verdict", ""),
                             "recommendation_rationale": recommendation.get("rationale", "")}
        await ctx.send_message(state)

    @executor(id="route")
    async def route(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 26a, the FR-12 finding, or a readiness return. Terminal in every case."""
        with gateway.node_span(cfg, "route"):
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
                        "failed_gates": list(state.get("readiness_failed") or ()),
                        "screening_defaulted_steps": sorted(
                            (state.get("screening") or {}).get("defaulted_steps") or {})}}


async def _finding(cfg, state: dict) -> dict:
    """FR-12 — a rejection goes to an architect BEFORE the submitter hears it, and the run ends
    carrying none of a design package. The approval releases nothing: confirming a rejection must
    not start the next process."""
    asked = await gateway.call(cfg, ApprovalTools.ask, {
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
    asked = await gateway.call(cfg, ApprovalTools.ask, {
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
            "delivery_ref": (state["design_ref"]
                             if (state.get("design") or {}).get("delivery_artifacts") else ""),
            # Both refs point at the one package, but they are named separately and each is empty
            # until its own step ran. A business_case_ref that is always set means the investment
            # board is handed a link to a case that has no benefit side in it.
            "business_case_ref": (state["design_ref"]
                                  if (state.get("design") or {}).get("benefit") else ""),
            "governance_tier": state.get("governance_tier", ""),
            "readiness": state.get("readiness", ""),
            "summary": {"verdict": "proceed", "design_attempted": True,
                        "pending_steps": len((state.get("design") or {}).get("pending_steps")
                                             or ()),
                        # Which screening findings rest on a declared default (an unpublished
                        # tenant corpus), so the conformance reviewer sees it before the design.
                        "screening_defaulted_steps": sorted(
                            (state.get("screening") or {}).get("defaulted_steps") or {})}}


async def run_workflow(cfg, inputs: dict) -> dict:
    """Preflight, then the graph. Both are `gateway.run_graph`'s — the preflight rule
    in particular was paid for once by a cloud failure and should not exist per
    workload, because the copy that will lack it is the next one."""
    return await gateway.run_graph(cfg, build_workflow, inputs, what="design",
                                   required=REQUIRED_TOOLS)
