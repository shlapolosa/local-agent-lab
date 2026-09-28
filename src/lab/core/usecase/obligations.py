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
from lab.core.usecase.model import DOMAINS, Workflow
from lab.core.usecase.predicates import PredicateError, parse

__all__ = [
    "ControlRequirementSet", "Obligation", "ObligationError", "Violation",
    "commit_invariant", "derive", "estate_guardrails", "mandatory_for", "triggered_for",
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
    the released one rather than whatever this package shipped with (NFR-15). Omitted, it refuses:
    there is no packaged copy to fall back on."""
    if rows is None:
        raise ObligationError("the class-to-guardrail mapping must be supplied — read "
                              "`guardrail-mapping` under the run's pin; there is no packaged copy")
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
        label, cell = str(values[0]).strip(), str(values[1])
        out[_row_kind(label)] = cell
    return out


def _row_kind(label: str) -> str:
    """Which KIND of row this is, from its label — and a refusal for a label nobody wrote a rule for.

    It used to be "an E/I class, else the baseline", so every other row was filed as BASELINE and
    the LAST one won. Measured 28 Sep 2026: the CAFÉ bundle added a domain floor and an estate-level
    row after the baseline, and every step's baseline became the estate row — prompt integrity,
    agent identity, component admission, registration and ontology conformance gone from every
    control set, with nothing failing. A row whose meaning is unknown is refused, never guessed.
    """
    match = _CLASS_ROW.match(label)
    if match:
        return match.group(1).upper()
    low = label.lower()
    if low.startswith("baseline"):
        return "BASELINE"
    if low.startswith("domain floor"):
        _floor_domains(label)                        # refuses a floor that floors nothing
        return f"FLOOR:{label}"
    if low.startswith("estate level"):
        # Recognised, and applied to NO step: the row says it is evaluated at registration and as
        # a standing estate check, "not from facet vectors".
        return "ESTATE"
    raise ObligationError(f"the guardrail mapping has a row {label!r} this derivation has no rule "
                          f"for — a control set cannot be derived from a row it does not "
                          f"understand, and guessing filed a whole row under the wrong class once")


def _floor_domains(label: str) -> set[str]:
    """The step domains a "Domain floor — …" row floors, by the model's own vocabulary.

    A domain counts only as a whole word NOT negated by a prefix: "non-clinical data" floors
    nothing, though a hyphen is a word boundary to a plain `\\b` match. A floor naming none of the
    domains is refused — it would otherwise apply to nothing, silently."""
    named = {d for d in DOMAINS if re.search(rf"(?<![\w-]){re.escape(d)}\b", label.lower())}
    if not named:
        raise ObligationError(f"the domain floor {label!r} names no step domain "
                              f"({', '.join(DOMAINS)}) — it would floor nothing")
    return named


#: One clause of the mapping, keyed for supersession: `(chain, guardrail, n)` — n counting that
#: guardrail's clauses within ITS row, and `chain` the row's independent line of inheritance
#: ("baseline", "floor:<label>", "E", "I"). Only a clause on the SAME chain can override another:
#: every row is mandatory "in addition to the baseline", and the E and I rows are independent. A
#: clause naming no guardrail is keyed by its own prose.
_Clause = tuple[tuple[str, str, int], Obligation]


def _obligations_from(cell: str, source: str, chain: str) -> list[_Clause]:
    """Split a mapping cell into keyed clauses, following "All of E1" rather than reading it as one.

    Cells are `·`-separated clauses; a clause may name a guardrail or may be pure prose. The key is
    `(guardrail, n)`, n counting that guardrail's clauses WITHIN this cell, because a class may
    state two requirements under one guardrail — E2's G09 is both "human confirmation, or a
    policy-bounded gate" and "approver holds a current, role-specific authorisation". Keyed by
    guardrail alone the second erased the first. Supersession is settled once, in `_supersede`.
    """
    out: list[_Clause] = []
    seen: dict[str, int] = {}
    for clause in (c.strip() for c in cell.split("·")):
        if not clause or _INHERITS.match(clause):
            continue
        ids = _GUARDRAIL.findall(clause)
        gid = ids[0] if ids else ""
        n = seen.get(gid, 0)
        seen[gid] = n + 1
        out.append(((chain, gid, n) if gid else (chain, clause, 0),
                    Obligation(text=clause, source=source, guardrail=gid)))
    return out


def _supersede(found: list[_Clause]) -> list[Obligation]:
    """One obligation per guardrail, in first-seen order, every contributing row named.

    `_resolve` recurses into the inherited class first, so an inherited clause arrives before the
    one that re-states it — and a plain "already seen" test kept the weaker text. E3's "G09 as
    per-action human authorisation — a policy-bounded gate is NOT sufficient at this class" was
    dropped in favour of E2's "or a policy-bounded gate", so a reviewer approving an irreversible
    financial commitment was handed the sentence saying the weaker control is acceptable.

    So a later clause overrides the clause at the SAME key — the same guardrail, the same position,
    on the same CHAIN. E3's single G09 clause restates E2's first (the confirmation mode) and leaves
    E2's second (the approver's authorisation) inherited. Across chains nothing is overridden: the
    baseline's "G29 on every model call" and the clinical floor's "G29 health content in-region" are
    two requirements, and keying by guardrail alone let the floor erase the baseline for exactly the
    steps carrying health data (review, 28 Sep 2026). The clauses of one guardrail are then read
    back as ONE obligation, in order: a reviewer reads one line per control.
    """
    by_key: dict = {}
    for key, obligation in found:
        by_key[key] = obligation           # insertion order kept; a later wording wins its key
    out: list[Obligation] = []
    parts: dict[str, tuple[list[str], list[str]]] = {}      # guardrail -> (texts, sources)
    for obligation in by_key.values():
        gid = obligation.guardrail
        if not gid:
            out.append(obligation)
            continue
        if gid not in parts:
            parts[gid] = ([], [])
            out.append(obligation)                          # its position; rebuilt below
        texts, sources = parts[gid]
        texts.append(obligation.text)
        if obligation.source not in sources:
            sources.append(obligation.source)
    return [Obligation(text=" · ".join(parts[o.guardrail][0]),
                       source=" + ".join(parts[o.guardrail][1]), guardrail=o.guardrail)
            if o.guardrail else o for o in out]


def _resolve(label: str, rows: dict[str, str]) -> list[_Clause]:
    """Everything this class mandates, inherited rows FIRST so a re-statement can supersede them."""
    cell = rows.get(label)
    if cell is None:
        raise ObligationError(f"the mapping has no row for {label!r}; have {sorted(rows)}")
    out: list[_Clause] = []
    inherits = _INHERITS.search(cell)
    if inherits:
        out += _resolve(inherits.group(1).upper(), rows)
    return out + _obligations_from(cell, label, label[0].upper())


def mandatory_for(exposure: int, influence: int, *, mapping_rows=None,
                  domain: str = "general") -> list[Obligation]:
    """What these two classes mandate for a step in this `domain`, baseline included and
    inheritance resolved.

    A DOMAIN FLOOR row applies when its label names the step's domain ("Domain floor — clinical or
    health data" names `clinical`): the exposure floor itself is `exposure.DOMAIN_FLOOR`, and this
    row adds the controls that come with it. The ESTATE row never applies to a step — it says so.
    """
    for name, value in (("exposure", exposure), ("influence", influence)):
        if not isinstance(value, int) or not 0 <= value <= 3:
            raise ObligationError(f"{name}: {value!r} is not a published class (0-3)")
    rows = _mapping_rows(mapping_rows)
    if "BASELINE" not in rows:
        raise ObligationError(f"the guardrail mapping has no baseline row; have {sorted(rows)}")
    out = _obligations_from(rows["BASELINE"], "baseline", "baseline")
    for kind, cell in rows.items():
        if kind.startswith("FLOOR:") and domain in _floor_domains(kind[len("FLOOR:"):]):
            out += _obligations_from(cell, "domain floor", kind.lower())
    if exposure:
        out += _resolve(f"E{exposure}", rows)
    if influence:
        out += _resolve(f"I{influence}", rows)
    # Once, over the whole set: a class that re-states a guardrail is strengthening it, and the
    # baseline/inherited wording must not shadow the stronger one.
    return _supersede(out)


def estate_guardrails(mapping_rows) -> set[str]:
    """The guardrails the mapping's ESTATE row names — evaluated at registration and as standing
    estate checks, "not from facet vectors". `derive` never evaluates their predicates per step:
    G28's asks whether "a managed device can reach an AI provider", which no step can answer, and
    evaluating it refused every step of every run (measured, 28 Sep 2026)."""
    cell = _mapping_rows(mapping_rows).get("ESTATE") or ""
    return set(_GUARDRAIL.findall(cell))


# ---------------------------------------------------------------- the predicates

def triggered_for(workflow: Workflow, step_id: str, *,
                  conditions: dict[str, bool] | None = None,
                  guardrails: list[dict] | None = None,
                  skip: frozenset[str] | set[str] = frozenset()) -> set[str]:
    """The guardrails whose trigger predicate fires for this step.

    Refuses the whole step rather than skipping a predicate it cannot answer: a short control set
    is indistinguishable from a correct one at review, which is exactly why this cannot be lenient.

    `skip` names guardrails whose predicate is NOT this step's to evaluate — those its classes
    already mandate (evaluating one can add nothing, and refusing over a control the step carries
    anyway refuses for nothing) and the estate-level ones (`estate_guardrails`). The refusal stands
    for every guardrail that might or might not fire, which is the only place it protects anything.
    """
    step = workflow[step_id]
    facts = step.facets(exposure=exposure_of(step),
                        influence=influence_of(workflow, step_id),
                        criticality=workflow.criticality)
    vectors = [s.facets(exposure=exposure_of(s), influence=influence_of(workflow, s.id),
                        criticality=workflow.criticality) for s in workflow]
    answers = {**(conditions or {}), **dict(step.conditions)}
    fired: set[str] = set()
    if guardrails is None:
        raise ObligationError("the guardrail set must be supplied — read `guardrails` under the "
                              "run's pin; there is no packaged copy")
    for guardrail in seed.live_only(guardrails):
        if guardrail["id"] in skip:
            continue
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

    `guardrails` and `mapping_rows` are the GOVERNED copies the caller pinned. There is no
    packaged fallback any more — an answer from the image changes when the image does."""
    if guardrails is None:
        raise ObligationError("the guardrail set must be supplied — read `guardrails` under the "
                              "run's pin; there is no packaged copy")
    # `live_only` on the rows: a governed corpus serves the retired guardrails as well, because
    # their identifiers must stay resolvable for citations already written down.
    live = seed.live_only(guardrails)
    estate = estate_guardrails(mapping_rows)
    by_step: dict[str, list[Obligation]] = {}
    for step in workflow:
        exposure, influence = exposure_of(step), influence_of(workflow, step.id)
        obligations = mandatory_for(exposure, influence, mapping_rows=mapping_rows,
                                    domain=step.domain)
        claimed = {o.guardrail for o in obligations if o.guardrail}
        catalogue = {g["id"]: g for g in live}
        for gid in sorted(triggered_for(workflow, step.id, conditions=conditions,
                                        guardrails=live, skip=claimed | estate)):
            obligations.append(Obligation(text=catalogue[gid]["rule"],
                                          source=f"predicate {catalogue[gid]['pred']}",
                                          guardrail=gid))
        by_step[step.id] = obligations
    return ControlRequirementSet(by_step=by_step, violations=tuple(commit_invariant(workflow)))
