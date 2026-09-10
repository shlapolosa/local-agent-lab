"""The CAFÉ domain objects — a step, its facet vector, and the workflow it sits in.

Typed and self-validating rather than dicts, because the facet vector is the governance primitive:
everything downstream (exposure, influence, obligations, component families, the build surface)
reads it, and a mistyped value that reaches step 19 does not fail — it silently fails to match a
predicate, and the run completes with a control set that is quietly short.

The vocabularies are the published ones. They live here as tuples rather than being read from the
seed at import, because a facet value is part of the domain's language: a new value is a framework
release, and it should arrive as a visible change here that the tests see, not as data that
silently widens what the model accepts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from lab.core.usecase.predicates import normalise_value

__all__ = [
    "ACTIVITIES", "AUDIENCES", "AUTHORISATIONS", "BLAST_RADII", "CRITICALITIES", "DETERMINISM",
    "canonical_criticality",
    "DOMAINS", "EFFECTS", "FRESHNESS", "REVERSIBILITY", "SENSITIVITIES", "TRUST",
    "Step", "Workflow",
]

ACTIVITIES = ("retrieve", "interpret", "decide", "transform", "commit", "notify", "orchestrate")
DETERMINISM = ("D0", "D1", "D2", "D3")
EFFECTS = ("none", "advisory", "record write", "external communication",
           "financial or contractual commitment", "physical or clinical action")
REVERSIBILITY = ("reversible", "reversible with cost", "irreversible")
BLAST_RADII = ("single record", "single subject", "cohort", "population")
AUDIENCES = ("internal individual", "internal group", "partner", "customer", "public", "regulator")
AUTHORISATIONS = ("per-action human", "policy-bounded", "autonomous")
DOMAINS = ("clinical", "financial", "hr", "safety", "general")
SENSITIVITIES = ("public", "internal", "confidential", "restricted")
TRUST = ("authoritative", "corroborated", "single-source unverified", "external untrusted")
FRESHNESS = ("static", "slow-moving", "dynamic", "time-critical")
CRITICALITIES = ("routine", "business-critical", "safety-of-life")

_VOCABULARY: dict[str, tuple[str, ...]] = {
    "activity": ACTIVITIES, "determinism": DETERMINISM, "effect": EFFECTS,
    "reversibility": REVERSIBILITY, "blast_radius": BLAST_RADII, "audience": AUDIENCES,
    "authorisation": AUTHORISATIONS, "domain": DOMAINS, "sensitivity": SENSITIVITIES,
    "trust": TRUST, "freshness": FRESHNESS,
}


# Normalised spelling -> the canonical published one, per facet. The artifact spells one value
# several ways ("a cohort" in the schema, "cohort" in the predicates), and a step must settle on
# one of them or a predicate comparison silently never matches.
_CANONICAL: dict[str, dict[str, str]] = {
    facet: {normalise_value(v): v for v in values} for facet, values in _VOCABULARY.items()
}


_CANONICAL_CRITICALITY = {normalise_value(c): c for c in CRITICALITIES}


def canonical_criticality(value: str) -> str:
    """The published spelling of a criticality class, or a refusal naming the legal ones.

    A human confirms the class in free text and `gates` compares it with `==` against this closed
    set, so "Safety of Life" would otherwise fall through to the permissive branch — the one
    direction whose failure drops controls. Hyphens, spaces and underscores are one spelling."""
    key = normalise_value(str(value or "")).replace("_", "-").replace(" ", "-")
    canonical = _CANONICAL_CRITICALITY.get(key) or _CANONICAL_CRITICALITY.get(key.replace("-", " "))
    if canonical is None:
        raise ValueError(f"{value!r} is not a published class; expected one of {list(CRITICALITIES)}")
    return canonical


def _checked(name: str, value: str) -> str:
    """One published spelling per facet value, or a refusal naming what was legal."""
    canonical = _CANONICAL[name].get(normalise_value(value))
    if canonical is None:
        raise ValueError(f"{name}: {value!r} is not a published value; expected one of "
                         f"{list(_VOCABULARY[name])}")
    return canonical


@dataclass(frozen=True)
class Step:
    """One step of the decomposed workflow, carrying the nine-facet vector step 17 assigns.

    `determines` is the data-flow edge influence walks forward: the steps whose effect this step's
    output helps decide. `gate_permits` marks this step as a gate and says which exposure class it
    lets past; `predicate_inputs` names the steps the gate READS to make that decision — they are
    not attenuated by it, because a step the gate depends on can mislead the gate (Q3.3).

    `determines_externally` is the exposure class of an effect this step determines OUTSIDE this
    workflow. The derivation says influence walks forward "to every effect the step determines" and
    does not restrict that to the graph in hand — an advisory workflow whose output sets the
    controls a system built next quarter will carry has real influence and no in-graph effect at
    all. Without it such a step scores influence 0, which is the wrong answer in the direction that
    drops controls. A CLASS rather than a facet vector, because what is known about another
    system's step is its class, not its reversibility or blast radius.
    """
    id: str
    activity: str
    determinism: str = "D0"
    effect: str = "none"
    reversibility: str = "reversible"
    blast_radius: str = "single record"
    audience: str = "internal individual"
    authorisation: str = "autonomous"
    domain: str = "general"
    sensitivity: str = "internal"
    trust: str = "authoritative"
    freshness: str = "static"
    determines: tuple[str, ...] = ()
    determines_externally: int | None = None
    gate_permits: int | None = None
    predicate_inputs: tuple[str, ...] = ()
    conditions: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.id).strip():
            raise ValueError("a step needs an id — everything downstream refers to it by name")
        for name in _VOCABULARY:
            object.__setattr__(self, name, _checked(name, getattr(self, name)))
        for name in ("gate_permits", "determines_externally"):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 3:
                raise ValueError(f"{name}: {value} is not an exposure class (0-3)")
        object.__setattr__(self, "determines", tuple(self.determines))
        object.__setattr__(self, "predicate_inputs", tuple(self.predicate_inputs))

    @property
    def is_gate(self) -> bool:
        return self.gate_permits is not None

    def facets(self, **extra: Any) -> dict[str, Any]:
        """The vector as a predicate reads it — the flat field names `predicates.FIELDS` uses."""
        return {
            "activity": self.activity, "determinism": self.determinism, "effect": self.effect,
            "reversibility": self.reversibility, "blast_radius": self.blast_radius,
            "audience": self.audience, "authorisation": self.authorisation, "domain": self.domain,
            "input.sensitivity": self.sensitivity, "input.trust": self.trust,
            "input.freshness": self.freshness,
            **extra,
        }


@dataclass(frozen=True)
class Workflow:
    """The sequenced steps (step 10) plus the confirmed criticality class (step 12)."""
    steps: tuple[Step, ...]
    criticality: str = "routine"

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        criticality = normalise_value(self.criticality)
        if criticality not in CRITICALITIES:
            raise ValueError(f"criticality: {self.criticality!r} is not a published class; "
                             f"expected one of {list(CRITICALITIES)}")
        object.__setattr__(self, "criticality", criticality)
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id {step.id!r} — ids address steps downstream")
            seen.add(step.id)

    def __getitem__(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"no step {step_id!r} in this workflow; have {[s.id for s in self.steps]}")

    def __iter__(self):
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)
