"""The nine screening steps: their schema, and the completeness rule a schema cannot express.

A schema says the shape is right. It cannot say the answer is. Every rule below is a sentence from
the specification that valid JSON would otherwise walk straight past:

* step 3 — "reject a problem stated as a solution, and reject shared accountability" (FR-05)
* step 4 — "sequence nothing; an implied order means you have skipped to E0.7" (E0.2)
* step 5 — "never invent a capability to justify the use case" (FR-07); coverage BOTH ways
* step 6 — "record confidence as lookup, assumption or survey" (FR-08)
* step 7 — the band is PROVISIONAL, for the feasibility verdict only
* step 8 — a numeric response measure "taken from an existing business commitment" (FR-13)
* step 9 — the check is at OBJECT level, coverage AND conflict (FR-14)
* step 10 — "one step per business function per active element" (FR-15)
* step 11 — "a citation policy in every retrieval contract" (FR-16)

Each is a pure function over the agent's output, so it is tested without a model and the rule can
be read next to the sentence that requires it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lab.workloads.usecase.gates import validator_for

__all__ = ["DESIGN_STEPS", "SCREENING_STEPS", "STEPS", "Step", "schema", "step_for"]

SCHEMAS = Path(__file__).parent / "schemas"
PROMPTS = Path(__file__).parent / "prompts"

#: Words that turn a problem statement into a solution statement. FR-05 rejects the second, because
#: a use case framed as its answer has already skipped the assessment it came for.
_SOLUTION_WORDS = ("we need a", "we should build", "implement a", "deploy a", "use an llm",
                   "use ai to", "a chatbot", "a copilot", "an agent that", "rpa")

#: An implied order in the behavioural list. E0.2: "sequence nothing" — ordering is step 10's job,
#: and a decomposition that has already ordered has skipped the exercise.
_ORDER_WORDS = ("first", "then", "next", "finally", "afterwards", "subsequently", "step 1",
                "step 2", "before that", "once that")


def schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Step:
    """One screening step: which agent performs it, what it emits, and what makes it complete."""
    number: str
    key: str                    # the field it contributes to the screening record
    service: str                # the bounded context that owns it
    complete: Callable[[dict], list[str]]
    normalise: Callable[[dict], None] | None = None

    def validator(self):
        return validator_for(schema(self.key))

    def prompt(self) -> str:
        return prompt(self.key)


# ---------------------------------------------------------------- the completeness rules

def _frame(out: dict) -> list[str]:
    bad = []
    problem = str(out.get("problem", "")).lower()
    hit = [w for w in _SOLUTION_WORDS if w in problem]
    if hit:
        bad.append(f"the problem is stated as a solution ({hit[0]!r}) — say what is wrong and for "
                   f"whom, not what to build; choosing the answer is what the rest of this "
                   f"assessment is for")
    owner = str(out.get("accountable_owner", "")).strip()
    # An owner the submission does not name is an OPEN QUESTION, not a failure. A live run proved
    # why: the model read a submission that names nobody, said so honestly, and the gate refused it
    # — leaving one honest answer and one fabricated one, of which only the fabricated one passes.
    # That is the opposite of what every prompt here asks for. A gap that reaches a human gets
    # closed; a name invented to satisfy a gate never does.
    unnamed = not owner or any(w in owner.lower() for w in ("unspecified", "not named", "unknown",
                                                            "names no person", "no person"))
    if unnamed:
        if not any("owner" in str(q).lower() or "accountab" in str(q).lower()
                   for q in out.get("open_questions") or []):
            bad.append("no accountable owner is named and no open question asks for one — an "
                       "unowned use case must reach a human as a question, not pass as an answer")
        return bad[:5]
    # `&` and `/` are not word characters, so a `\b` around them matches nothing — the separators
    # have to be looked for literally, and " and " needs its spaces or it fires inside "Alexander".
    # A COMMA is deliberately not a separator: "Jane Smith, Chief Medical Officer" is one person
    # with a title, and treating punctuation as plurality refused more honest answers than shared
    # ones.
    shared = any(sep in owner for sep in ("&", "/")) or " and " in f" {owner} "
    if shared or any(w in owner.lower() for w in (" team", " group", " department", " unit")):
        bad.append(f"accountability is shared ({owner!r}) — name ONE person; a use case everyone "
                   f"owns is a use case nobody answers for")
    return bad


def _elements(out: dict) -> list[str]:
    bad = []
    for kind in ("active", "behavioural", "passive"):
        if not out.get(kind):
            bad.append(f"the {kind} list is empty — a decomposition that found no {kind} elements "
                       f"has not been done")
    ordered = [b["name"] for b in out.get("behavioural") or []
               if any(w in str(b.get("name", "")).lower() for w in _ORDER_WORDS)]
    if ordered:
        bad.append(f"the behavioural list implies an order ({ordered[:2]}) — sequence nothing here; "
                   f"ordering is step 10, and a decomposition that has already ordered has skipped "
                   f"the exercise")
    return bad


def _coverage_map(out: dict) -> list[str]:
    bad = []
    if not out.get("matched") and not out.get("functions_without_capability"):
        bad.append("neither a match nor an unmatched function — the coverage check was not done")
    for match in out.get("matched") or []:
        if not str(match.get("capability_id", "")).strip():
            bad.append(f'{match.get("function")!r} names no capability id — a capability must be '
                       f'looked up, never invented to justify the use case')
    if "capabilities_without_function" not in out:
        bad.append("coverage must be reported BOTH ways, even where the second direction is empty")
    # The heat-map position is what step 16's reject rule reads. Required whenever anything
    # matched, and required WITH its source: a capability that is commodity, mature and already
    # meeting target is a reason not to build, and that verdict must rest on a lookup rather than
    # on an agent's impression of how common the capability feels.
    heat = out.get("heat_map")
    if out.get("matched") and not heat:
        bad.append("a capability matched but its heat-map position is missing — the "
                   "commodity/mature/meets-target reject rule cannot fire without it, and a rule "
                   "that never fires is one nobody can tell is broken")
    elif heat and not str(heat.get("source", "")).strip():
        bad.append("the heat-map position names no source — it is a LOOKUP against the published "
                   "capability map, not a judgement made here")
    return bad


def _realisation_match(out: dict) -> list[str]:
    bad = []
    if not out.get("matched") and not out.get("unrealised"):
        bad.append("no element was matched and none reported unrealised — the check was not done")
    for match in out.get("matched") or []:
        if match.get("confidence") == "survey" and not (out.get("gap_flags") or []):
            bad.append(f'{match.get("element")!r} was matched by SURVEY with no gap flag — a survey '
                       f'result is a gap flag candidate, never a silent assumption')
    return bad


def _criticality_band(out: dict) -> list[str]:
    if out.get("provisional") is not True:
        return ["the band must be marked provisional — it exists for the feasibility verdict only, "
                "and step 12 derives the confirmed class independently"]
    return []


def _quality_attributes(out: dict) -> list[str]:
    bad = []
    for scenario in out.get("scenarios") or []:
        taken = str(scenario.get("taken_from", "")).strip().lower()
        if not taken or taken in ("none", "n/a", "assumed", "estimated"):
            bad.append(f'{scenario.get("function")!r} has no business commitment behind its '
                       f'response measure — a service level is taken from an existing commitment '
                       f'or it is a gap flag, never invented')
    if not out.get("scenarios") and not (out.get("gap_flags") or []):
        bad.append("no scenarios and no gap flags — where no commitment exists, RAISE the gap")
    return bad


def _ontology_delta(out: dict) -> list[str]:
    if not out.get("concepts"):
        return ["no business object was checked — the ontology check is per OBJECT, and an empty "
                "result means it was not run"]
    if "conflicts" not in out:
        return ["conflicts must be reported even where empty — one word meaning two things is the "
                "half of this check that a coverage list cannot show"]
    return []


def _workflow_graph(out: dict) -> list[str]:
    bad = []
    nodes = {n["id"] for n in out.get("nodes") or []}
    if not nodes:
        bad.append("the graph has no nodes — a workflow that cannot be stated explicitly is a "
                   "Board escalation, not an empty answer")
    for edge in out.get("edges") or []:
        for end in ("from", "to"):
            if edge.get(end) not in nodes:
                bad.append(f'an edge names {edge.get(end)!r}, which is not a node in this graph')
        if not str(edge.get("data_class", "")).strip():
            bad.append(f'the edge {edge.get("from")}->{edge.get("to")} carries no data class — '
                       f'every data-flow edge carries a business object')
    return bad[:5]


def _source_contracts(out: dict) -> list[str]:
    bad = []
    for source in out.get("sources") or []:
        if not str(source.get("citation_policy", "")).strip():
            bad.append(f'{source.get("source")!r} has no citation policy — every retrieval contract '
                       f'carries one, or the grounding cannot be audited')
    if not out.get("sources") and not (out.get("gap_flags") or []):
        bad.append("no source was contracted and no gap flagged — a source with no contract FAILS "
                   "readiness, so it must be reported either way")
    return bad



# ---------------------------------------------------------------- the design-side rules

def _assertions(out: dict) -> list[str]:
    """E0.10 / FR-18: "evaluable against a system of record without reading anything the workflow
    produced". The rule this enforces is the difference between monitoring and self-congratulation:
    an assertion that reads the workflow's own output is true whenever the workflow says so, and
    cannot detect the failure it was written for."""
    bad = []
    if not out.get("assertions"):
        bad.append("no outcome assertion — a workflow with influence above the lowest class must "
                   "declare at least one, monitored independently of the steps producing it")
    for item in out.get("assertions") or []:
        if item.get("reads_workflow_output"):
            bad.append(f'{item.get("statement", "")[:60]!r} reads the workflow\'s own output — it '
                       f'would be true whenever the workflow says it is, and cannot detect the '
                       f'failure it was written for')
        if not str(item.get("evaluated_against", "")).strip():
            bad.append("an assertion names no system of record to evaluate it against")
    return bad[:5]


def _determinism(out: dict) -> list[str]:
    """Q1.1-Q1.5. The necessity test is asked ONCE per non-D0 step, and a step reducible by
    criteria 6-7 is re-tiered to D0 — the observed failure is over-classifying as
    non-deterministic, which buys an agent where a lookup table would do."""
    bad = []
    if not out.get("graph_is_explicit", True):
        bad.append("the graph is not explicit — that is D3 at orchestration level and a Board "
                   "escalation, which must be said rather than scored around")
    tiers = [s.get("tier") for s in out.get("steps") or []]
    if not tiers:
        bad.append("no step was classified")
    for step in out.get("steps") or []:
        if step.get("tier") != "D0" and not step.get("necessity"):
            bad.append(f'step {step.get("id")!r} is above D0 with no necessity test — every '
                       f'non-D0 step is asked once whether it is irreducible')
        if step.get("necessity") == "by default" and step.get("reducible_to") != "D0":
            bad.append(f'step {step.get("id")!r} is non-deterministic BY DEFAULT, which means a '
                       f'rule exists and nobody wrote it down — it re-tiers to D0')
    aggregate = out.get("governance_tier")
    if tiers and aggregate and aggregate != max(tiers):
        bad.append(f"the governance tier is the MAXIMUM of the step tiers: {max(tiers)}, not "
                   f"{aggregate}")
    return bad[:5]


#: What the published guardrail predicates ask that a facet vector cannot answer. Read from the
#: corpus rather than restated, so a new guardrail's condition becomes required the moment it is
#: published rather than the next time somebody remembers this list.
try:
    from lab.core.usecase.seed import NAMED_CONDITIONS
except ImportError:                                        # pragma: no cover - the seed is packaged
    NAMED_CONDITIONS: frozenset[str] = frozenset()


def _facet_vectors(out: dict) -> list[str]:
    """Q2.4 and FR-22: every override carries a written justification, and exposure and influence
    are NOT decided here — they follow by a published derivation, and deciding them in an agent
    would make the derivation an opinion."""
    bad = []
    if not out.get("steps"):
        bad.append("no step was given a facet vector")
    for step in out.get("steps") or []:
        for override in step.get("overrides") or []:
            if len(str(override.get("justification", "")).strip()) < 10:
                bad.append(f'the override of {override.get("facet")!r} on step {step.get("id")!r} '
                           f'has no justification — an override without a reason is a default '
                           f'nobody checked')
        for forbidden in ("exposure", "influence"):
            if forbidden in step:
                bad.append(f"step {step.get('id')!r} sets {forbidden!r} — that is derived from "
                           f"these facets by a deterministic service, not decided here")
        # The prose conditions the guardrail predicates ask about. Every one, or the derivation
        # REFUSES — `predicates.Named` will not read an unanswered condition as false, because a
        # guardrail that silently fails to fire is the failure nobody can see. Answering them here
        # is not the same as choosing controls: these describe the step this agent is already
        # describing, and it never sees which guardrails they turn on.
        unanswered = sorted(set(NAMED_CONDITIONS) - set(step.get("conditions") or {}))
        if unanswered:
            bad.append(f'step {step.get("id")!r} leaves {unanswered[:3]} unanswered '
                       f'({len(unanswered)} in total) — a guardrail whose condition nobody '
                       f'answered does not fire, and nothing downstream can tell it was skipped')
    return bad[:5]


def _build_surface(out: dict) -> list[str]:
    """FR-25 and FR-26. The incumbent question is asked FIRST and its failures recorded; an
    obligation the selected surface cannot enforce sends the design back to step 17, because a
    different runtime with the same gap is the same gap."""
    bad = []
    if not out.get("incumbent_considered"):
        bad.append("the incumbent-platform question was not asked — it is asked first, and an "
                   "incumbent that satisfies the obligations is usually the right answer")
    if out.get("incumbent") and not out.get("incumbent_failed_obligations") \
            and out.get("surface") != out.get("incumbent"):
        bad.append(f'the incumbent {out.get("incumbent")!r} was rejected without recording which '
                   f'obligations it failed — "we chose something else" is not a decision record')
    return bad


def _component_selection(out: dict) -> list[str]:
    """FR-27 and FR-28. A tradeoff is RECORDED, never resolved by dropping a constraint — a
    constraint quietly dropped reappears as an incident."""
    bad = []
    if not out.get("selected"):
        bad.append("nothing was selected")
    for choice in out.get("selected") or []:
        if not choice.get("rejected_alternatives"):
            bad.append(f'{choice.get("capability")!r} names no rejected alternative — a selection '
                       f'with none is a preference written down, not a decision')
    for tradeoff in out.get("tradeoffs") or []:
        for field in ("compensating_control", "review_trigger"):
            if not str(tradeoff.get(field, "")).strip():
                bad.append(f'a tradeoff has no {field.replace("_", " ")} — that is a dropped '
                           f'constraint wearing a decision record')
    for block in out.get("building_blocks") or []:
        if not str(block.get("owner", "")).strip():
            bad.append(f'the building block {block.get("what")!r} has no named owner — an '
                       f'out-of-scope component nobody owns is an obligation nobody carries')
    return bad[:5]


# ---------------------------------------------------------------- the registry

#: Steps 3-11 — the pre-work exercises, run by the SCREENING process before the criticality gate.
#: The eight sections a business case has. Named here rather than counted, so a case missing
#: "Risks and mitigations" fails on the name a person can go and write.
BUSINESS_CASE_SECTIONS = ("executive summary", "current state", "proposed solution",
                          "value drivers", "financial summary", "roadmap",
                          "risks and mitigations", "approvals and recommendation")


def _delivery_artifacts(out: dict) -> list[str]:
    """Step 25. Four artifacts, and each rule below is the field its own schema calls the one worth
    keeping — which is exactly the field a model under length pressure drops first."""
    bad = []
    written = {str(s.get("section", "")).strip().lower() for s in out.get("business_case") or []}
    missing = [s for s in BUSINESS_CASE_SECTIONS if s not in written]
    if missing:
        bad.append(f"the business case is missing {missing} — an approver reading seven of eight "
                   f"sections cannot tell which one is absent")
    for record in out.get("decision_records") or []:
        if len(record.get("options") or []) < 2:
            bad.append(f'the decision record for {record.get("decision")!r} considered fewer than '
                       f'two options, which is a preference and not a decision')
        if not str(record.get("sacrificed", "")).strip():
            bad.append(f'the decision record for {record.get("decision")!r} names nothing that was '
                       f'sacrificed — the field that makes the record worth keeping')
    for contract in out.get("service_contracts") or []:
        if not str(contract.get("service_level_source", "")).strip():
            bad.append(f'the service level for {contract.get("name")!r} names no source; a service '
                       f'level is DERIVED from the business one, never invented, and an invented '
                       f'latency target is a promise somebody will be held to')
    unowned = [w.get("key") for w in out.get("work_items") or []
               if not str(w.get("owner", "")).strip()]
    if unowned:
        bad.append(f"work items {unowned} name no owner — a task nobody has agreed to do")
    return bad[:5]


def _cost_inputs(out: dict) -> list[str]:
    """Sub-steps 23.1-23.2 and 23.5. The arithmetic is the service's; what is checked here is that
    the selection is auditable and that a build cost never arrives without its provenance."""
    bad = []
    resources = out.get("resources") or []
    switched = out.get("switched_on_by") or {}
    if not resources and not (out.get("unpriceable") or []):
        bad.append("no resource was selected and none was flagged unpriceable — a composed design "
                   "switches something on, and a cost of nothing is not an answer")
    unexplained = [r for r in resources if not str(switched.get(r, "")).strip()]
    if unexplained:
        bad.append(f"{unexplained} name no family or component that switched them on — a bill "
                   f"nobody can audit is a bill nobody should approve")
    if out.get("build_amount") and not out.get("build_provenance"):
        bad.append("a build cost was given with no provenance — an approver reads a vendor quote "
                   "as a number somebody will be held to, and an estimate is not one")
    if out.get("build_provenance") and not out.get("build_amount"):
        bad.append("a build provenance was given with no amount — the provenance describes a "
                   "figure, and there is none")
    return bad[:5]


def _benefit_inputs(out: dict) -> list[str]:
    """Sub-steps 24.1-24.4. The one rule worth the gate: an absent driver is DECLARED, never
    silently omitted and never filled with a default that looks like evidence."""
    bad = []
    for row in out.get("effort") or []:
        if not str(row.get("source", "")).strip():
            bad.append(f'the effort figures for {row.get("role")!r} carry no source — a headcount '
                       f'somebody will act on and nobody can check')
        if _number(row.get("expected_minutes")) > _number(row.get("current_minutes")):
            bad.append(f'{row.get("role")!r} is expected to take LONGER after the change, which is '
                       f'a cost and not a benefit; state it as such or correct the figures')
    baseline = out.get("quality_baseline") or {}
    if baseline and not str(baseline.get("source", "")).strip():
        bad.append("the quality baseline carries no source")
    if not (out.get("effort") or []) and not baseline and not (out.get("unsupplied") or []):
        bad.append("no driver has inputs and nothing is declared unsupplied — a case with no "
                   "evidence either way is not the same as a case worth nothing, and only one of "
                   "them should reach a funding decision")
    return bad[:5]


def _number(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


SCREENING_STEPS: tuple[Step, ...] = (
    Step("3", "frame", "Business Analyst", _frame),
    Step("4", "elements", "Business Architect", _elements),
    Step("5", "coverage_map", "Business Architect", _coverage_map),
    Step("6", "realisation_match", "Application Architect", _realisation_match),
    Step("7", "criticality_band", "Risk Officer", _criticality_band),
    Step("8", "quality_attributes", "Product Owner", _quality_attributes),
    Step("9", "ontology_delta", "Data Architect", _ontology_delta),
    Step("10", "workflow_graph", "Business Analyst", _workflow_graph),
    Step("11", "source_contracts", "Data Architect", _source_contracts),
)

#: Steps 13-21 — the interpretive half of the DESIGN process. 14, 16, 18, 19 and 22 are absent
#: because they are deterministic: they are `decision-mcp`'s, not an agent's, and putting one here
#: would be a second implementation of a published rule.
DESIGN_STEPS: tuple[Step, ...] = (
    Step("13", "assertions", "Product Owner", _assertions),
    Step("15", "determinism", "Solution Architect", _determinism),
    Step("17", "facet_vectors", "Risk Officer", _facet_vectors),
    Step("20", "build_surface", "Technology Architect", _build_surface),
    Step("21", "component_selection", "Solution Architect", _component_selection),
    Step("23", "cost_inputs", "Cost Engineer", _cost_inputs),
    Step("24", "benefit_inputs", "Value Analyst", _benefit_inputs),
    Step("25", "delivery_artifacts", "Product Owner", _delivery_artifacts),
)

STEPS: tuple[Step, ...] = SCREENING_STEPS + DESIGN_STEPS


def step_for(number: str) -> Step:
    for step in STEPS:
        if step.number == number:
            return step
    raise KeyError(f"no step {number!r}; have {[s.number for s in STEPS]}")
