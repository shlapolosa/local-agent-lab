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

__all__ = ["STEPS", "Step", "schema", "step_for"]

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
    owner = str(out.get("accountable_owner", ""))
    # `&` and `/` are not word characters, so a `\b` around them matches nothing — the separators
    # have to be looked for literally, and " and " needs its spaces or it fires inside "Alexander".
    shared = any(sep in owner for sep in ("&", "/", ",", ";")) or " and " in f" {owner} "
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


# ---------------------------------------------------------------- the registry

STEPS: tuple[Step, ...] = (
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


def step_for(number: str) -> Step:
    for step in STEPS:
        if step.number == number:
            return step
    raise KeyError(f"no screening step {number!r}; have {[s.number for s in STEPS]}")
