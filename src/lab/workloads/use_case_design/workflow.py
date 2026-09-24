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
# Aliased: `enforcement` is already the local name for the composition's family -> guardrail map,
# and two different things called `enforcement` in one file is how the wrong one gets passed.
from lab.core.usecase import enforcement as enforcement_binding
from lab.core.usecase.model import canonical_criticality
from lab.platform import config, contracts, runlog
from lab.platform.contracts import (
    ReferenceTools,
    USE_CASE_DESIGN,
    USE_CASE_INVESTMENT,
    ApprovalTools,
    Continuation,
    DecisionTools,
    EATools,
    SemanticTools,
    StorageTools,
    ValuationTools,
)
from lab.workloads import gateway
from lab.workloads.usecase import reference
from lab.workloads.usecase import families, mappers, modeltrace, modelling, owed
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.steps import derived_for
from lab.workloads.usecase.steps import NUMBER_OF, step_for

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
    # The published guardrails, for the ONE thing the workload derives from them: which capability
    # (and so which component) enforces each — the chain that tells step 21 whether the selection
    # carries the families the composition requires. The control set itself is decision-mcp's.
    "guardrails": ("guardrails", "guardrail"),
    # Which archetype a topology composes to — read for the model, so the draw.io projection knows
    # its base without reaching the corpus from the substrate.
    "topology_archetypes": ("reference-architecture-topology-archetypes", "topology-archetype"),
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

#: An ESCALATE is not a finding to overturn — it is a question nobody could answer from the corpus,
#: so asking a person to "confirm or overturn" would frame a decision they must MAKE as a machine
#: judgement they may correct. Different verdict, different sentence.
ESCALATED_PROMPT = (
    "This use case could not be ruled on automatically — the evidence the feasibility rule needs is "
    "not published in this tenant. Decide it: does this use case serve a named capability with "
    "headroom? Nothing was rejected and nothing was approved; the rule is waiting on you.")


def finding_prompt(verdict: str) -> str:
    return ESCALATED_PROMPT if str(verdict).strip().lower() == "escalate" else FINDING_PROMPT


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

    `capability_matched` has a THIRD state. When step 5 was DEFAULTED — this tenant publishes no
    business capability map — false would say "the use case serves no capability on the map", a
    finding about a map nobody wrote, and it would reject every use case identically. `None` says
    "not known" and the verdict escalates to an architect instead. Read off `defaulted_steps`
    rather than from an empty `matched`, because a map that IS published and genuinely matches
    nothing is the reject rule doing its job.
    """
    coverage = screening.get("coverage_map") or {}
    realisations = screening.get("realisation_match") or {}
    heat = coverage.get("heat_map") or {}
    defaulted = NUMBER_OF.get("coverage_map", "") in (screening.get("defaulted_steps") or {})
    return {"capability_matched": None if defaulted else bool(coverage.get("matched")),
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
    """One design exercise, through the shared runner — then onto the model."""
    step = step_for(number)
    await d.run_step(cfg, step)
    await modelling.grow(cfg, d, step.key)


def determines_from(graph: Mapping[str, Any]) -> dict:
    """`{step id: the steps it determines}` — DERIVED from step 10's data-flow edges.

    Influence walks forward to every effect a step determines, and until 23 Sep 2026 nothing ever
    told the domain what a step determined: the facet schema had no such field, so `influence_of`
    returned 0 for every step of every run and G13, G18 and G19 could not fire.

    Derived rather than asked. Step 10 already produces the edges and `_workflow_graph` already
    gates them — every endpoint is a declared node — so asking step 17 to restate them would add a
    second opinion that can disagree with the first, which is the defect step 15 and step 17
    already have over determinism. An edge to a node nobody declared is not a determination: it is
    the gate's business, and silently honouring it here would put a phantom step in the chain.
    """
    # The screening record sometimes carries the graph as SHAPE — `nodes: 6` — rather than as a
    # list. That is the evidence form, and raising on it would kill a design run over a summary.
    # A count names no edges, so a count derives nothing.
    raw_nodes = (graph or {}).get("nodes")
    raw_edges = (graph or {}).get("edges")
    if not isinstance(raw_nodes, (list, tuple)) or not isinstance(raw_edges, (list, tuple)):
        return {}
    nodes = {str(n.get("id", "")).strip() for n in raw_nodes if isinstance(n, Mapping)}
    out: dict[str, list] = {}
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            continue
        src, dst = str(edge.get("from", "")).strip(), str(edge.get("to", "")).strip()
        if src in nodes and dst in nodes and dst not in out.get(src, ()):
            out.setdefault(src, []).append(dst)
    return {k: tuple(v) for k, v in out.items()}


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
    determines = determines_from((state.get("screening") or {}).get("workflow_graph") or {})
    steps = [_domain_step(v, determines) for v in (derived.get("facet_vectors") or {}).get("steps") or []
             if str(v.get("id", "")).strip()]
    return {"steps": steps, "criticality": _criticality(state)}


#: The facets a domain `Step` takes, by name — the translation at this edge hands the domain exactly
#: these and nothing the agent's schema adds for a reader (an `overrides` list with its written
#: justifications stays on the recorded facet-vector output; the first live design run died in the
#: decision service on that key, 13 Sep 2026).
_STEP_FIELDS = ("id", "activity", "determinism", "effect", "reversibility", "blast_radius", "audience",
                "authorisation", "domain", "sensitivity", "trust", "freshness", "determines",
                "determines_externally", "gate_permits", "predicate_inputs", "conditions")


#: Facets an override may not touch: `id` and `activity` are identity, `conditions` are answers
#: rather than a facet, and `determines` is DERIVED from the gated graph — an override of it would
#: be an agent editing the data-flow.
_NOT_OVERRIDABLE = ("id", "activity", "conditions", "determines")


def _domain_step(vector: Mapping[str, Any], determines: Mapping[str, tuple] = ()) -> dict:
    """One facet vector as the domain reads it: an override is APPLIED to its facet (that is what
    an override is — the justified value replaces the default), and only the domain's fields go.

    `determines` arrives from the GRAPH, not from the vector — see `determines_from`.

    An override naming a facet the domain does not recognise is REFUSED, not dropped. It used to be
    skipped in silence while its justification stayed in the recorded output, so a reader saw a
    written argument for a value the derivation never used. The schema now closes the set, and this
    raises if one gets past it, because the two ways to be wrong here are not equal: refusing is
    visible and a silent drop is not.
    """
    step = {k: vector[k] for k in _STEP_FIELDS if k in vector}
    if determines and (mine := dict(determines).get(str(vector.get("id", "")).strip())):
        step["determines"] = mine
    for override in vector.get("overrides") or []:
        facet, to = str(override.get("facet", "")).strip(), override.get("to")
        if to in (None, "") or facet in _NOT_OVERRIDABLE:
            continue
        if facet not in _STEP_FIELDS:
            raise ValueError(
                f"facet vector {vector.get('id')!r}: override names {facet!r}, which is not a "
                f"facet — the justified value would be discarded and its justification kept")
        step[facet] = to
    return step


async def _risk_and_obligations(cfg, payload: dict, d: Derivation, pin_id: str) -> None:
    """Steps 18 and 19 — exposure and influence from the facets, then the control set from those
    classes. Both refused without a facet vector: a control set derived for an empty workflow is
    valid, empty, and completely wrong. The obligations are derived UNDER THE PIN, attributed to
    the field they become."""
    if not payload["steps"]:
        d.defer("18", "derive exposure and influence — needs a facet vector per step")
        d.defer("19", "evaluate obligations — needs a facet vector per step")
        return
    await d.derive(cfg, derived_for("18"),
                   await gateway.call(cfg, DecisionTools.exposure, {"workflow": payload}))
    await modelling.grow(cfg, d, "risk")
    await d.derive(cfg, derived_for("19"), await gateway.call(cfg, DecisionTools.obligations, {
        "workflow": payload, "pin_id": pin_id, **reference.attribution(cfg, "obligations")}))
    await modelling.grow(cfg, d, "obligations")


async def _compose(cfg, payload: dict, d: Derivation, pin_id: str) -> None:
    """Step 22. Its topology comes from step 20, because that is where the question "who owns
    control flow at runtime" is actually answered."""
    topology = (d.derived.get("build_surface") or {}).get("topology", "")
    if not (payload["steps"] and topology):
        d.defer("22", "compose architecture — needs a topology from step 20")
        return
    await d.derive(cfg, derived_for("22"), await gateway.call(cfg, DecisionTools.composition, {
        "workflow": payload, "topology": topology,
        "obligations_required": list((d.derived.get("obligations") or {}).get("guardrails") or ()),
        "pin_id": pin_id, **reference.attribution(cfg, "composition")}))
    # Which component carries which of THIS design's families, followed through the published chain
    # (family -> guardrail -> capability -> component) rather than read off a catalogue column the
    # reference architecture does not have. Recorded before step 21 so the architect selecting
    # components can see what each one would satisfy, and the gate can hold it to that.
    enforcement = (d.derived.get("composition") or {}).get("enforcement") or {}
    # NOT `or []`. `_corpora` OMITS an artifact it could not read, so absent is None — and `or []`
    # would turn "we never read the map" into "the map binds nothing", which reports every
    # obligation as a gap in the FRAMEWORK when in fact nothing was read. `candidates()` refuses a
    # None outright; `families` tolerates it, because a family join over an absent corpus is the
    # silence it is designed to report.
    guardrails = d.available.get("guardrails")
    capability_map = d.available.get("ai_capability_map")
    d.record("component_families", {
        "by_component": families.by_component(enforcement, guardrails, capability_map),
        # Families whose guardrails name no capability in the published map: the corpus is silent,
        # which is not the same as the design failing to cover them.
        "unclaimed": families.unclaimed(enforcement, guardrails, capability_map)})
    # Move 5's input: which catalogue component COULD enforce each guardrail. Recorded before step
    # 21 so the architect selects an enforcing component deliberately rather than being failed for
    # having missed one, and so the gate binds against exactly what the prompt was shown.
    try:
        d.record("enforcement_points", enforcement_binding.candidates(guardrails, capability_map))
    except enforcement_binding.EnforcementError as absent:
        d.defer("21", f"bind obligations to enforcement points: {absent}")
    await modelling.grow(cfg, d, "composition")


async def _bind_obligations(d: Derivation) -> None:
    """Composition move 5, after step 21 — every obligation on a component this design SELECTED.

    Runs here and not inside `_compose` because it needs the selection. The gate on step 21 refuses
    an `unbound` obligation already; this records the whole binding so the conformance reviewer sees
    what enforces what, rather than only what does not.
    """
    points = d.derived.get("enforcement_points")
    if points is None:
        return                       # `_compose` already deferred by name; do not defer twice
    selection = d.derived.get("component_selection") or {}
    binding = enforcement_binding.bind(
        list((d.derived.get("obligations") or {}).get("guardrails") or ()),
        candidates=points,
        selected=[str(c.get("component_id", "")) for c in selection.get("selected") or []])
    d.record("enforcement", {"bound": {g: list(c) for g, c in binding.bound.items()},
                             "unbound": list(binding.unbound),
                             "unenforceable": list(binding.unenforceable),
                             "complete": binding.complete})


def effort_rows(state: Mapping[str, Any], evidence: Mapping[str, Any]) -> list:
    """The effort table driver 1 is computed from: what a person CAPTURED, else what step 24 inferred.

    Not because the agent is bad at reading an effort table, but because one of these is evidence
    and the other is a reconstruction — and step 24 is not even shown the intake, so its prompt
    tells it to cite "the intake field it came from", a source it structurally cannot see.

    A captured table is typed at the door (`InputKind.TABLE`), so the rows arrive as numbers rather
    than as prose for the formula to parse. An empty capture is not a capture: the agent's answer
    stands, and a run with neither still reports `requires_input` by name.
    """
    captured = list(state.get("effort") or ())
    return captured or list((evidence or {}).get("effort") or ())


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
        await modelling.grow(cfg, d, "cost")

    evidence = d.derived.get("benefit_inputs")
    cost_model = d.derived.get("cost")
    if evidence is None or cost_model is None:
        d.defer("24", "build the business case — needs the benefit evidence from step 24 and the "
                      "cost it has to repay from step 23")
        return
    d.record("benefit", await gateway.call(cfg, ValuationTools.benefit, {
        # What a person captured at intake beats what step 24 reconstructed from prose.
        "effort": effort_rows(state, evidence),
        "quality_baseline": dict(evidence.get("quality_baseline") or {}),
        "sensitivity_flags": list(evidence.get("sensitivity_flags") or ()),
        "cited_avoided_cost": evidence.get("cited_avoided_cost"),
        "citation": evidence.get("citation") or "",
        "data_fully_digital": bool(evidence.get("data_fully_digital", True)),
        # None, not 0.0: an uncaptured build cost must stay UNKNOWN so `authority.route`
        # escalates to the top band instead of routing a real spend under a small one.
        "build_cost": (None if (cost_model.get("build") or {}).get("amount") is None
                       else float((cost_model["build"] or {})["amount"])),
        "capex": float(cost_model.get("capex") or 0.0),
        "monthly_run_cost": float((cost_model.get("monthly") or {}).get("expected") or 0.0),
        # Everything still open on either side reaches the verdict as a gate condition. A
        # recommendation that did not carry them would read as settled.
        "open_conditions": (list(cost_model.get("requires_input") or ())
                            + list(evidence.get("unsupplied") or ()))}), "24")
    await modelling.grow(cfg, d, "benefit")


async def _views(cfg, model: Mapping[str, Any]) -> dict:
    """Project the model: `model_ref` (the spec, by ref), the ArchiMate XML + one SVG per standard
    view, the CAFÉ draw.io view + its SVG. `architecture_ref` is the drawing a person opens — the
    draw.io file, else the model. Every failure is a named warning, never an exception: a design
    that cannot draw is still a design."""
    out: dict[str, Any] = {"model_ref": "", "archimate_xml_ref": "", "architecture_ref": "",
                           "svg_refs": {}, "warnings": []}
    if not model.get("elements"):
        out["warnings"].append("no model: nothing to render")
        return out
    try:
        stored = await gateway.call(cfg, SemanticTools.store_spec,
                                    {"spec": model, "name": "design.model.json"})
        out["model_ref"] = out["architecture_ref"] = gateway.ref_from(stored)
    except Exception as exc:                       # noqa: BLE001 — recorded, never raised
        out["warnings"].append(f"store model: {exc!r}"[:200])
        return out
    root = next((e for e in model.get("elements") or [] if e.get("id") == mappers.ROOT), {})
    admitted = mappers.as_list((root.get("props") or {}).get("cafe.archetypes"))
    if len(admitted) > 1:
        # The corpus admits several archetypes for this topology; the drawing has to stand on one.
        # Recorded beside the drawing, where the reviewer sees the assumption.
        out["warnings"].append(f'cafe: drawn on {(root.get("props") or {}).get("cafe.archetype")}; '
                               f'the pinned corpus admits {", ".join(admitted)} for this topology')
    for tool, args, take in (
            (EATools.render, {"spec_ref": out["model_ref"], "basename": "design", "strict": False},
             lambda r: {"archimate_xml_ref": r.get("xml_ref", ""), "svg_refs": dict(r.get("svg_refs") or {})}),
            (SemanticTools.render_cafe, {"spec_ref": out["model_ref"], "basename": "design"},
             lambda r: {"architecture_ref": r.get("drawio_ref") or out["architecture_ref"],
                        "svg_refs": {**out["svg_refs"], **({"cafe": r["svg_ref"]} if r.get("svg_ref") else {})},
                        "cafe_unplaced": list(r.get("unplaced") or ()),
                        # Counts a reviewer can read without opening the drawing: how many of the
                        # selected components the reference architecture carries, and how many
                        # connections it therefore drew. A view of tiles with no lines is a parts
                        # list, and this is what says so on the record.
                        "cafe_catalogued": r.get("catalogued"), "cafe_edges": r.get("edges")})):
        try:
            res = await gateway.call(cfg, tool, args)
            res = res if isinstance(res, dict) else json.loads(res or "{}")
            out.update(take(res))
            out["warnings"].extend(f"{tool}: {w}" for w in (res.get("warnings") or ())[:5])
        except Exception as exc:                   # noqa: BLE001
            out["warnings"].append(f"{tool}: {type(exc).__name__}: {str(exc)[:120]}")
    if cfg.get("run_id") and out["warnings"]:
        runlog.update(cfg["run_id"], render_warnings="; ".join(out["warnings"])[:400])
    return out


#: What each executor DOES, declared beside the graph that declares the executors. A node id is an
#: address — `derive` says where a run is, not what it is doing — and the live page must not be
#: where a human name for somebody else's step is invented. Stamped on the node by `_node` below,
#: so the SSE frame carries the label and the page renders whatever arrived.
#: Held honest by `tests/unit/workloads/test_node_titles.py`, which reads the `@executor(id=...)`
#: declarations themselves rather than a list kept in step with them.
NODES = {"readiness": "check readiness gates",
         "feasibility": "judge feasibility",
         "derive_design": "run the design steps",
         "render_views": "render the views",
         "route": "route for approval"}


def _node(cfg, name: str):
    """A run-log span for one executor, labelled from `NODES`."""
    return gateway.node_span(cfg, name, title=NODES.get(name, ""))


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
        with _node(cfg, "readiness"):
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
                             "effort": list(record.get("effort") or ()),
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
        with _node(cfg, "feasibility"):
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
        classes; the build surface (20) is tested against those obligations; the composition (22)
        is the union of what the facets call for, given that surface's topology; and components
        (21) are selected against those obligations AND the families the composition requires —
        which is why 22 runs before 21 here: its inputs are 17, 19 and 20, and a selection made
        before the families are known cannot be held to them (step 21's soft rule). Every
        deterministic link is a governed tool, so the rule a run obeyed is the released one rather
        than a copy living here.
        """
        with _node(cfg, "derive_design"):
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
            await _compose(cfg, payload, d, pin_id)      # 22 the composition — its families...
            modelling.ensure(d)                          # ...on the model step 21 is shown
            await _agent_step(cfg, "21", d)              # the components, against those controls
            await _bind_obligations(d)                   # 22 move 5 — obligation -> selected component
            await _agent_step(cfg, "23", d)              # what the design costs
            await _agent_step(cfg, "24", d)              # what evidences the benefit
            await _valuation(cfg, d, state)              # 23/24 arithmetic, by the governed service
            await _agent_step(cfg, "25", d)              # write down what was decided

            state = state | {"derived": d.derived, "pending": d.pending,
                             "defaulted": dict(d.defaulted)}
        await ctx.send_message(state)

    @executor(id="render_views")
    async def render_views(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The views, then the package. The model the run grew is stored by ref and projected
        twice — the ArchiMate views by the engine, the CAFÉ solution view by the draw.io projector —
        and the refs go INTO the package, because the investment run reads the package. Each render
        is best-effort in its own right: a run that produced a model but no picture is still a run,
        and the warning it records is the visible degradation (neither render tool is REQUIRED).
        """
        with _node(cfg, "render_views"):
            if state.get("halted"):
                await ctx.send_message(state)
                return
            d = Derivation(derived=dict(state.get("derived") or {}),
                           pending=dict(state.get("pending") or {}))
            d.defaulted = dict(state.get("defaulted") or {})
            d.record("views", await _views(cfg, d.derived.get("model") or {}))
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
        with _node(cfg, "route"):
            if state.get("readiness") == "fail":
                out = _not_ready(state)
            elif state.get("halted"):
                out = await _finding(cfg, state)
            else:
                out = await _conformance(cfg, state)
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=readiness)
            .add_chain([readiness, feasibility, derive_design, render_views, route]).build())


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
        "prompt": finding_prompt(state.get("verdict", "")),
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


def _view_artifacts(state: dict) -> dict:
    """What the conformance reviewer can OPEN: the refs the views produced (each a download) and the
    SVGs (rendered inline as tabs) — the final views first, then the per-step trace while it is on."""
    design = state.get("design") or {}
    views = design.get("views") or {}
    # One key per DISTINCT ref: when nothing drew, `architecture_ref` IS the model ref, and two
    # downloads of one file is what the review app refuses (`contracts.import_artifacts` dedupes
    # too — belt and braces, because this payload is read by more than the review app).
    refs: dict[str, str] = {}
    for k in ("model_ref", "archimate_xml_ref", "architecture_ref"):
        if views.get(k) and views[k] not in refs.values():
            refs[k] = views[k]
    svgs = {**(views.get("svg_refs") or {}), **modeltrace.tabs(design)}
    return {**refs, **({"svg_refs": svgs} if svgs else {})}


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
        "fields": ["value"],                   # one thing to say per label, not a voice
        # What is still OPEN, before the reviewer opens anything. Run 8 (15 Sep 2026) proceeded with
        # four obligations bound to no enforcement point, eleven components nobody could price and a
        # benefit nobody could compute — all recorded in the package, none of it in front of the
        # person being asked to approve, whose summary was empty.
        "summary": {**owed.counts(state.get("design") or {}),
                    "screening_defaulted_steps": sorted(
                        (state.get("screening") or {}).get("defaulted_steps") or {})},
        "artifacts": {"design": state["design_ref"], "screening": state["screening_ref"],
                      **_view_artifacts(state)},
        "requester": state.get("submitter", ""),
                "process": PROCESS})
    views = (state.get("design") or {}).get("views") or {}
    return {"approval_id": asked["request_id"], "review_app": asked.get("review_app", ""),
            "verdict": "proceed", "halted": False,
            # The drawing a person opens; the model when nothing drew; the package as a last resort.
            "architecture_ref": views.get("architecture_ref") or views.get("model_ref") or state["design_ref"],
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
