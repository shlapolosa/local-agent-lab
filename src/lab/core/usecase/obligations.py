"""Step 19 — evaluate obligations and emit the control requirement set. Deterministic (D0).

Three sources, and a set missing any one of them would still look complete:

1. **Predicates** (Q3.1) — every published guardrail's trigger predicate, evaluated against every
   step's facet vector. This is where `lab.core.usecase.predicates` is used in anger.
2. **The risk-class mapping** (E.6) — what a step's exposure and influence classes mandate whatever
   the predicates say. The artifact writes inheritance as prose ("All of E1"), so it has to be
   resolved rather than read literally, and some cells mandate an obligation with **no guardrail
   id at all** ("an evaluation harness with a stated accuracy target"). Keeping only the numbered
   ones silently drops real controls.
3. **The commit invariant** (Q3.2) — a workflow-level test: no step may produce an irreversible or
   externally visible effect while non-deterministically informed and unauthorised.

A breach of the invariant is reported, not raised. It is a finding the architect must see, and a
run that crashed instead would destroy the evidence that shows why.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lab.core.usecase import seed
from lab.core.usecase.exposure import exposure_of, influence_of
from lab.core.usecase.model import Workflow
from lab.core.usecase.predicates import PredicateError, parse

__all__ = [
    "ControlRequirementSet", "Obligation", "ObligationError", "Violation",
    "commit_invariant", "derive", "mandatory_for", "triggered_for",
]

_GUARDRAIL = re.compile(r"\bG\d{2}\b")
_INHERITS = re.compile(r"\ball of ([EI]\d)\b", re.I)
_CLASS_ROW = re.compile(r"^([EI]\d)\b")

#: Effects that make a step a COMMIT for the invariant's purposes — the ones a reversal path or a
#: pre-commit confirmation has to exist for.
_EXTERNALLY_VISIBLE = frozenset({
    "external communication", "financial or contractual commitment", "physical or clinical action",
})


class ObligationError(ValueError):
    """The control requirement set could not be derived, and must not be half-derived."""


@dataclass(frozen=True)
class Obligation:
    """One control this step must carry, and where it came from.

    `guardrail` is empty for the obligations the mapping states in prose without an id. `source`
    always names the origin — a class cell or a fired predicate — because FR-44 requires every
    derived field to record how it was derived, and "why is this control here" is the question an
    architect asks first at review.
    """
    text: str
    source: str
    guardrail: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ObligationError("an obligation needs text a person can act on")
        if not self.source.strip():
            raise ObligationError(f"{self.text!r} does not say which rule mandated it")


@dataclass(frozen=True)
class Violation:
    step: str
    reason: str


@dataclass(frozen=True)
class ControlRequirementSet:
    by_step: dict[str, list[Obligation]] = field(default_factory=dict)
    violations: tuple[Violation, ...] = ()

    @property
    def commit_invariant_holds(self) -> bool:
        return not self.violations

    def guardrails(self) -> set[str]:
        """Every guardrail the whole set names — what §9's control list is checked against."""
        return {o.guardrail for obs in self.by_step.values() for o in obs if o.guardrail}


# ---------------------------------------------------------------- the class mapping

def _mapping_rows(rows=None) -> dict[str, str]:
    """The class mapping, as rows. `rows` lets a caller supply the GOVERNED copy — the decision
    server passes what it read from the reference corpus under a pin, so the rule a run obeyed is
    the released one rather than whatever this package shipped with (NFR-15). Omitted, the local
    seed answers, which is what keeps the domain testable with no infrastructure at all."""
    rows = rows if rows is not None else seed.artifact("guardrail_mapping")["mandatory_by_class"]["rows"]
    out: dict[str, str] = {}
    for row in rows:
        # Rows are the master's table: (class, what it mandates). A mapping is also accepted, with
        # the store's bookkeeping id dropped — but a caller reading from the corpus should flatten
        # there, so the derivation never has to know how a record was addressed.
        if isinstance(row, dict):
            values = [v for k, v in row.items() if not str(k).startswith("record_")]
        else:
            values = list(row)
        if len(values) < 2:
            raise ObligationError(f"a mapping row needs a class and what it mandates; got {row!r}")
        label, cell = values[0], values[1]
        match = _CLASS_ROW.match(str(label).strip())
        out[match.group(1).upper() if match else "BASELINE"] = str(cell)
    return out


def _obligations_from(cell: str, source: str, seen: set[str]) -> list[Obligation]:
    """Split a mapping cell into obligations, following "All of E1" rather than reading it as one.

    Cells are `·`-separated clauses; a clause may name a guardrail or may be pure prose."""
    out: list[Obligation] = []
    for clause in (c.strip() for c in cell.split("·")):
        if not clause or _INHERITS.match(clause):
            continue
        ids = _GUARDRAIL.findall(clause)
        key = f"{ids[0] if ids else clause}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Obligation(text=clause, source=source, guardrail=ids[0] if ids else ""))
    return out


def _resolve(label: str, rows: dict[str, str], seen: set[str]) -> list[Obligation]:
    cell = rows.get(label)
    if cell is None:
        raise ObligationError(f"the mapping has no row for {label!r}; have {sorted(rows)}")
    out: list[Obligation] = []
    inherits = _INHERITS.search(cell)
    if inherits:
        out += _resolve(inherits.group(1).upper(), rows, seen)
    return out + _obligations_from(cell, label, seen)


def mandatory_for(exposure: int, influence: int, *, mapping_rows=None) -> list[Obligation]:
    """What these two classes mandate, baseline included and inheritance resolved."""
    for name, value in (("exposure", exposure), ("influence", influence)):
        if not isinstance(value, int) or not 0 <= value <= 3:
            raise ObligationError(f"{name}: {value!r} is not a published class (0-3)")
    rows = _mapping_rows(mapping_rows)
    seen: set[str] = set()
    out = _obligations_from(rows["BASELINE"], "baseline", seen)
    if exposure:
        out += _resolve(f"E{exposure}", rows, seen)
    if influence:
        out += _resolve(f"I{influence}", rows, seen)
    return out


# ---------------------------------------------------------------- the predicates

def triggered_for(workflow: Workflow, step_id: str, *,
                  conditions: dict[str, bool] | None = None,
                  guardrails: list[dict] | None = None) -> set[str]:
    """The guardrails whose trigger predicate fires for this step.

    Refuses the whole step rather than skipping a predicate it cannot answer: a short control set
    is indistinguishable from a correct one at review, which is exactly why this cannot be lenient.
    """
    step = workflow[step_id]
    facts = step.facets(exposure=exposure_of(step),
                        influence=influence_of(workflow, step_id),
                        criticality=workflow.criticality)
    vectors = [s.facets(exposure=exposure_of(s), influence=influence_of(workflow, s.id),
                        criticality=workflow.criticality) for s in workflow]
    answers = {**(conditions or {}), **dict(step.conditions)}
    fired: set[str] = set()
    for guardrail in (seed.live_only(guardrails) if guardrails is not None
                      else seed.live_guardrails()):
        try:
            if parse(guardrail["pred"]).evaluate(facts, workflow=vectors, conditions=answers):
                fired.add(guardrail["id"])
        except PredicateError as exc:
            raise ObligationError(
                f'{guardrail["id"]} could not be evaluated for step {step_id!r}: {exc}') from exc
    return fired


# ---------------------------------------------------------------- the commit invariant

def _informants(workflow: Workflow, step_id: str) -> dict[str, bool]:
    """Every step whose output reaches `step_id`, and whether a gate stands on the way.

    Walks the data flow backwards. `True` means every path from that informant passes a gate."""
    reached: dict[str, bool] = {}
    frontier = [(s.id, False) for s in workflow if step_id in s.determines]
    while frontier:
        current_id, gated = frontier.pop()
        was = reached.get(current_id)
        if was is not None and (was is False or was == gated):
            continue
        reached[current_id] = gated if was is None else (was and gated)
        current = workflow[current_id]
        onward = gated or current.is_gate
        frontier += [(s.id, onward) for s in workflow if current_id in s.determines]
    return reached


def commit_invariant(workflow: Workflow) -> list[Violation]:
    """Q3.2 — no irreversible or externally visible effect while non-deterministically informed.

    "Gated" satisfies it, and so does per-action human authorisation. Anything else is a breach the
    architect has to see: this is the one obligation the framework says is *not permitted* rather
    than merely controlled."""
    out: list[Violation] = []
    for step in workflow:
        committing = step.effect in _EXTERNALLY_VISIBLE or (
            step.reversibility == "irreversible" and step.effect != "none")
        if not committing or step.authorisation == "per-action human":
            continue
        loose = [informant for informant, gated in _informants(workflow, step.id).items()
                 if not gated and workflow[informant].determinism != "D0"]
        if step.determinism != "D0":
            loose.append(step.id)
        if loose:
            out.append(Violation(
                step=step.id,
                reason=(f"{step.effect} is informed non-deterministically by "
                        f"{sorted(set(loose))} with authorisation {step.authorisation!r} and no "
                        f"gate between")))
    return out


# ---------------------------------------------------------------- the whole set

def derive(workflow: Workflow, *,
           conditions: dict[str, bool] | None = None,
           guardrails: list[dict] | None = None,
           mapping_rows=None) -> ControlRequirementSet:
    """The control requirement set — what the `decision_obligations` tool returns.

    `guardrails` and `mapping_rows` are the GOVERNED copies when a caller has pinned them; omitted,
    the local seed answers. The rules are read at call time either way — never compiled in."""
    # `live_only` on the INJECTED rows too: a governed corpus serves the retired guardrails as
    # well, because their identifiers must stay resolvable for citations already written down.
    live = seed.live_only(guardrails) if guardrails is not None else seed.live_guardrails()
    by_step: dict[str, list[Obligation]] = {}
    for step in workflow:
        exposure, influence = exposure_of(step), influence_of(workflow, step.id)
        obligations = mandatory_for(exposure, influence, mapping_rows=mapping_rows)
        claimed = {o.guardrail for o in obligations if o.guardrail}
        catalogue = {g["id"]: g for g in live}
        for gid in sorted(triggered_for(workflow, step.id, conditions=conditions,
                                        guardrails=live) - claimed):
            obligations.append(Obligation(text=catalogue[gid]["rule"],
                                          source=f"predicate {catalogue[gid]['pred']}",
                                          guardrail=gid))
        by_step[step.id] = obligations
    return ControlRequirementSet(by_step=by_step, violations=tuple(commit_invariant(workflow)))
