"""Step 22 — compose the architecture from the derived evidence. Deterministic (D0).

Five published moves, and only the first is a judgement:

1. **Topology** — who owns control flow at runtime. Decided at step 21, passed in here.
2. **Modifiers** — trigger, human position and criticality, read off the facets and the class.
3. **Families** — the union over every step's facet vector. This is the move that makes the
   composition derived rather than chosen.
4. **Connectors** — the data-flow edges, already on the workflow.
5. **Enforcement points** — every obligation bound to a component or a declared boundary interface.

"A composition carrying a family no step calls for is over-built", so absence is as much a result
as presence, and `unbound` is reported rather than swallowed: Q5.3 says an obligation that resolves
to no enforcement point is a STOP, and it can only stop if somebody is told.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from lab.core.usecase import seed
from lab.core.usecase.exposure import exposure_of, influence_of
from lab.core.usecase.model import Workflow
from lab.core.usecase.predicates import PredicateError, parse

__all__ = ["TOPOLOGIES", "Composition", "CompositionError", "compose", "families_for"]

#: The four published topologies (E.7). Anything else is not a composition this framework makes.
TOPOLOGIES = ("T1", "T2", "T3", "T4")


class CompositionError(ValueError):
    """The composition could not be derived, and a half-derived one must not be returned."""


@dataclass(frozen=True)
class Composition:
    topology: str
    families: frozenset[str]
    variants: Mapping[str, str] = field(default_factory=dict)
    modifiers: Mapping[str, str] = field(default_factory=dict)
    enforcement: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unbound: frozenset[str] = frozenset()
    connectors: tuple[tuple[str, str], ...] = ()


def _catalogue(families=None) -> list[dict]:
    """The family triggers. `families` lets a caller supply the governed copy under a pin."""
    return list(families if families is not None else seed.artifact("family_triggers")["families"])


def _vectors(workflow: Workflow) -> list[dict]:
    return [s.facets(exposure=exposure_of(s), influence=influence_of(workflow, s.id),
                     criticality=workflow.criticality) for s in workflow]


def families_for(workflow: Workflow, *, topology: str,
                 conditions: Mapping[str, bool] | None = None,
                 families: list[dict] | None = None) -> frozenset[str]:
    """Move 3 — the union of what every step calls for, plus what the topology itself requires."""
    if topology not in TOPOLOGIES:
        raise CompositionError(f"{topology!r} is not a published topology; expected one of "
                               f"{list(TOPOLOGIES)}")
    vectors = _vectors(workflow)
    # Each step's OWN answers, merged over the workflow-wide ones — the same rule `obligations`
    # applies, and for the same reason: a family predicate asks a question ABOUT A STEP ("step
    # reads any grounding source"), so answering it workflow-wide answers it for every step at
    # once. Without this, a run whose facet vectors carry their conditions still refused at step
    # 22, having derived its whole control set successfully at step 19 — found live, because the
    # tests stub the derivation.
    answers = [{**(conditions or {}), **dict(step.conditions)} for step in workflow]
    present: set[str] = set()
    for family in _catalogue(families):
        allowed = family.get("topology")
        if allowed is not None:
            if topology in allowed:
                present.add(family["id"])
            continue
        if not str(family.get("predicate", "")).strip():
            # A family with neither a topology nor a predicate cannot be evaluated. It means a
            # published row lost a column — measured, against a stale version of the artifact whose
            # master predated the union-columns fix — and a KeyError here says nothing about which
            # rule or which artifact.
            raise CompositionError(
                f'family {family.get("id")!r} carries neither a topology nor a predicate, so '
                f'nothing can decide whether it is present. The published row is missing a column; '
                f'check which version of the family triggers this run pinned.')
        predicate = parse(family["predicate"])
        try:
            if any(predicate.evaluate(v, workflow=vectors, conditions=a)
                   for v, a in zip(vectors, answers)):
                present.add(family["id"])
        except PredicateError as exc:
            raise CompositionError(
                f'family {family["id"]} could not be derived: {exc}') from exc
    return frozenset(present)


def _modifiers(workflow: Workflow) -> dict[str, str]:
    """Move 2. Human position is read from the authorisations actually present — a workflow with a
    per-action human somewhere is in-loop, one with a policy-bounded gate is on-loop, and one with
    neither is out-of-loop."""
    authorisations = {s.authorisation for s in workflow}
    if "per-action human" in authorisations:
        position = "in-loop"
    elif "policy-bounded" in authorisations:
        position = "on-loop"
    else:
        position = "out-of-loop"
    return {"human_position": position, "criticality": workflow.criticality}


def compose(workflow: Workflow, *, topology: str,
            conditions: Mapping[str, bool] | None = None,
            grounding_sources: int = 0,
            obligations: Iterable[str] = (),
            families: list[dict] | None = None) -> Composition:
    """The composed design — what the `decision_composition` tool returns."""
    if not len(workflow):
        raise CompositionError("a composition needs a workflow; there is nothing to derive from")
    present = families_for(workflow, topology=topology, conditions=conditions,
                           families=families)
    catalogue = {f["id"]: f for f in _catalogue(families)}

    variants: dict[str, str] = {}
    if "F1" in present and grounding_sources > 1:
        variants["F1"] = catalogue["F1"]["variant"]["name"]

    enforcement = {fid: tuple(catalogue[fid].get("guardrails", ())) for fid in sorted(present)}
    bound = {g for guardrails in enforcement.values() for g in guardrails}
    connectors = tuple((s.id, nxt) for s in workflow for nxt in s.determines)

    return Composition(topology=topology, families=present, variants=variants,
                       modifiers=_modifiers(workflow), enforcement=enforcement,
                       unbound=frozenset(set(obligations) - bound), connectors=connectors)
