"""Step 18 — derive exposure and influence per step. Deterministic (D0).

Two properties, two questions. **Exposure** is how bad it is when the step WORKS: read off the
step's own effect, reversibility, blast radius and audience, in the four published moves. It is
scored. **Influence** is how bad it is when the step is WRONG: read, not scored — walk the data
flow forward to every effect this step helps determine and take the highest exposure among them,
attenuated wherever a gate stands between.

The asymmetry is the point, and it is why an "advisory" step is not automatically safe. The doc's
own example is an interpretive step with effect `none` whose output selects a branch: exposure 0,
influence 3. Controls are selected from both, and only influence catches that one.
"""
from __future__ import annotations

from lab.core.usecase.model import Step, Workflow

__all__ = ["BASE_BY_EFFECT", "CAP", "DOMAIN_FLOOR", "derive", "exposure_of", "influence_of"]

#: Move 1 — base from effect class.
BASE_BY_EFFECT: dict[str, int] = {
    "none": 0,
    "advisory": 0,
    "record write": 1,
    "external communication": 2,
    "financial or contractual commitment": 3,
    "physical or clinical action": 3,
}

#: Move 2 — modifiers.
_IRREVERSIBLE = 1
_RADIUS_MODIFIER = {"single record": 0, "single subject": 0, "cohort": 1, "population": 2}
_AUDIENCE_MODIFIER = {"public": 1, "regulator": 1}

#: Move 3 — a domain raises a FLOOR; it never adds a class on top of one.
DOMAIN_FLOOR: dict[str, int] = {"clinical": 2, "safety": 2, "financial": 1, "hr": 1}

#: Move 4 — class 3 is the ceiling. There is no class 4.
CAP = 3


def exposure_of(step: Step) -> int:
    """How bad it is when this step works — the four published moves, in order."""
    score = BASE_BY_EFFECT[step.effect]
    score += _IRREVERSIBLE if step.reversibility == "irreversible" else 0
    score += _RADIUS_MODIFIER[step.blast_radius]
    score += _AUDIENCE_MODIFIER.get(step.audience, 0)
    score = max(score, DOMAIN_FLOOR.get(step.domain, 0))     # a floor, not an addition
    return min(score, CAP)


def influence_of(workflow: Workflow, step_id: str) -> int:
    """How bad it is when this step is wrong — the highest exposure it determines downstream.

    Walks the data flow forward from `step_id`. Crossing a gate the walking step does NOT supply
    predicate inputs to caps everything beyond it at what the gate permits (Q3.3); crossing a gate
    that reads this step is no attenuation at all, because a step the gate depends on can mislead
    the gate. A cycle is visited once. A `determines` naming a step that is not in the workflow is
    a broken graph and refuses — ignoring it would under-score influence, and under-scoring is the
    direction that quietly drops controls.
    """
    origin = workflow[step_id]                               # refuse an unknown origin, loudly
    # An effect this step determines outside the workflow counts too — the derivation says "every
    # effect the step determines", and an advisory workflow that sets another system's controls has
    # influence with no in-graph effect at all.
    best = origin.determines_externally or 0
    # (step id, the cap in force on this path) — a path may reach one step under several caps.
    frontier: list[tuple[str, int]] = [(step_id, CAP)]
    seen: set[tuple[str, int]] = set()
    while frontier:
        current_id, cap = frontier.pop()
        if (current_id, cap) in seen:
            continue
        seen.add((current_id, cap))
        current = workflow[current_id]
        if current_id != step_id:
            best = max(best, min(exposure_of(current), cap))
        onward = cap
        if current.is_gate and step_id not in current.predicate_inputs:
            onward = min(cap, current.gate_permits or 0)
        for nxt in current.determines:
            workflow[nxt]                                    # a dangling edge is a broken graph
            frontier.append((nxt, onward))
    return min(best, CAP)


def derive(workflow: Workflow) -> dict[str, dict[str, int]]:
    """Both classes for every step — what the `decision_exposure` tool returns."""
    return {s.id: {"exposure": exposure_of(s), "influence": influence_of(workflow, s.id)}
            for s in workflow}
