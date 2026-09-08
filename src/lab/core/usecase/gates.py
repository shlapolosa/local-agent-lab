"""Steps 14 and 16 — the readiness verdict and the feasibility verdict. Both deterministic (D0).

The two cheap gates. Together they are the only places a use case stops before an architect has
spent real time on it, and both rule on DERIVED evidence rather than an estimate — which is what
makes them D0. The spec is explicit that this is the point: an earlier draft screened at step 8
from a coarse determinism guess, and that guess (with the anchoring control it needed) was removed
once the verdict moved to step 16 where the workflow graph, the readiness verdict and the
governance tier are all in hand.

Neither gate is an approval. Step 16's outcome still goes to an architect before the submitter
hears it (FR-12) — a wrong rejection kills a valuable use case and produces no observable event, so
it is the one refusal a human always sees.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

__all__ = [
    "Feasibility", "FeasibilityOutcome", "GateError", "Readiness", "ReadinessOutcome",
    "feasibility_verdict", "readiness_verdict",
]

#: The four M0 gates. A and D are load-bearing for everything after them and are never partial;
#: only B (semantic) and C (knowledge) may be carried as conditions.
GATES = ("A", "B", "C", "D")
CONDITIONABLE = ("B", "C")


class GateError(ValueError):
    """A verdict could not be reached on the evidence supplied, and must not be guessed."""


class Readiness(StrEnum):
    PASS = "pass"
    CONDITIONAL = "conditional"
    FAIL = "fail"


class Feasibility(StrEnum):
    PROCEED = "proceed"
    REJECT = "reject"
    INTEGRATION = "integration"


@dataclass(frozen=True)
class ReadinessOutcome:
    verdict: Readiness
    failed: tuple[str, ...] = ()
    conditions: Mapping[str, Mapping[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.conditions is None:
            object.__setattr__(self, "conditions", {})


@dataclass(frozen=True)
class FeasibilityOutcome:
    verdict: Feasibility
    rule: str

    @property
    def halts(self) -> bool:
        """FR-11: a reject or an integration finding stops the run. Steps 17-25 are not attempted
        and no partial design package is produced."""
        return self.verdict is not Feasibility.PROCEED


# ---------------------------------------------------------------- step 14

def readiness_verdict(evidence: Mapping[str, Any], *, criticality: str,
                      conditions: Mapping[str, Mapping[str, str]] | None = None
                      ) -> ReadinessOutcome:
    """Evaluate the four gates against the Stage 0 outputs.

    `evidence` maps each gate to `True` (evidenced), `False` (not), or `"partial"`. A partial B or
    C may be carried as a CONDITION, but only with a named owner and a dated closure plan — a
    conditional pass with nobody accountable is a fail that has been dressed up — and never for a
    safety-of-life class, where the gates that most need settling are the least allowed to slip.
    """
    missing = [g for g in GATES if g not in evidence]
    if missing:
        raise GateError(f"no evidence supplied for gate(s) {missing}; all of {list(GATES)} must be "
                        f"assessed before a readiness verdict")

    supplied = conditions or {}
    failed: list[str] = []
    carried: dict[str, Mapping[str, str]] = {}

    for gate in GATES:
        state = evidence[gate]
        if state is True:
            continue
        if state != "partial":
            failed.append(gate)
            continue
        plan = supplied.get(gate) or {}
        if gate not in CONDITIONABLE:
            failed.append(gate)                      # A and D are never carried as conditions
        elif criticality == "safety-of-life":
            failed.append(gate)                      # stated outright in the artifact
        elif not (plan.get("owner") and plan.get("closes")):
            failed.append(gate)                      # unowned or undated is not a condition
        else:
            carried[gate] = plan

    if failed:
        return ReadinessOutcome(Readiness.FAIL, tuple(failed), carried)
    if carried:
        return ReadinessOutcome(Readiness.CONDITIONAL, (), carried)
    return ReadinessOutcome(Readiness.PASS, (), {})


# ---------------------------------------------------------------- step 16

def feasibility_verdict(*, capability_matched: bool, existing_realisation: bool,
                        capability_is_commodity: bool, capability_is_mature: bool,
                        capability_meets_target: bool) -> FeasibilityOutcome:
    """Apply the published verdict rule, in order. The first rule that fires decides.

    Every outcome carries the rule that fired, because "the feasibility verdict with the rule that
    fired" is a persisted design-pack artifact: a rejection an architect cannot interrogate is not
    reviewable, and OA-1 requires an architect to see every one.
    """
    if not capability_matched:
        return FeasibilityOutcome(
            Feasibility.REJECT,
            "no capability match — the use case serves no capability on the map, so there is "
            "nothing for it to improve")
    if existing_realisation:
        return FeasibilityOutcome(
            Feasibility.INTEGRATION,
            "an existing realisation already serves this capability — the use case returns as an "
            "integration rather than a build")
    if capability_is_commodity and capability_is_mature and capability_meets_target:
        return FeasibilityOutcome(
            Feasibility.REJECT,
            "the capability is commodity, mature and meeting target on the heat map — there is no "
            "headroom for this to move a measure")
    return FeasibilityOutcome(
        Feasibility.PROCEED,
        "a matched capability with headroom and no existing realisation")
