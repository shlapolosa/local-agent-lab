"""Which component belongs to which architecture family — DERIVED, never authored.

Step 21's soft rule asks whether every family the composition requires is carried by a selected
component. The obvious data for that would be a `families` column on the component catalogue, and
the catalogue has none: the CAFÉ artifact these rows were extracted from does not assert it. Writing
one by hand would put a mapping nobody published in front of a reviewer as if it were the reference
architecture's.

The corpus does assert a chain, in two published hops:

    family --(family-triggers.guardrails)--> guardrail
           --(guardrails.cap)--> "Domain · Capability"
           --(ai-capability-map.capability)--> component ids

So a component carries family F when it realises a capability that enforces one of F's guardrails.
That is the reference architecture's own reasoning, followed rather than summarised.

It is PARTIAL by nature, and the partiality is the point: a family whose guardrails reach no
capability resolves to no component — not because nothing realises it, but because the corpus does
not say. `unclaimed()` names exactly those, and the rule that consumes this stays silent about them.
A derivation that guessed the rest would be the authored column again, wearing a join.

**The partiality had a second cause nobody had separated, measured 18 Sep 2026: 20 of the 24 live
guardrails named an enforcement point that resolved to NO row in the map** — nine were label drift
against a row that existed, eleven named a control capability the map lacked, and two were prose.
`unclaimed()` reported all of them as corpus silence, which is indistinguishable from a typo, so the
join looked partial-by-design when it was mostly broken. `tests/governance/test_guardrail_bindings_
resolve.py` now refuses a dangling reference, and silence means silence again.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from lab.core.usecase import capabilities, enforcement

__all__ = ["by_component", "of_component", "unclaimed"]

# The join key and the reference split live in `lab.core.usecase.capabilities` — the binding and the
# governance check that refuses a dangling reference need the IDENTICAL spelling, and two spellings
# of a join key is exactly the defect that check exists to catch.
_list = capabilities.refs
_capability_key = capabilities.key


def _components_of_guardrail(guardrails: Iterable[Mapping[str, Any]],
                             capability_map: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    """guardrail -> the components that could enforce it.

    The two hops themselves live in `lab.core.usecase.enforcement.candidates` — this module had its
    own line-for-line copy, and the CHAIN drifting apart is exactly the failure the join key was
    hoisted to prevent one level down. Only the shape differs: a family join wants sets.

    `or []` here and not at the caller: a family join over an absent corpus is the SILENCE this
    module exists to report, whereas an obligation binding over one is a false accusation, which is
    why `candidates` refuses a None and this does not.
    """
    return {g: set(c) for g, c in enforcement.candidates(guardrails or [],
                                                         capability_map or []).items()}


def by_component(enforcement: Mapping[str, Any], guardrails: Iterable[Mapping[str, Any]],
                 capability_map: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """`{component id: [family, …]}` — a component carries a family when it realises a capability
    that enforces one of that family's guardrails. `enforcement` is the composition's own
    family → guardrails mapping, so this follows THIS design's families rather than all of them."""
    of_guardrail = _components_of_guardrail(guardrails, capability_map)
    out: dict[str, set[str]] = {}
    for family, guards in (enforcement or {}).items():
        for guardrail in _list(guards):
            for component in of_guardrail.get(guardrail, ()):
                out.setdefault(component, set()).add(str(family))
    return {component: sorted(families) for component, families in sorted(out.items())}


def of_component(component_id: str, enforcement, guardrails, capability_map) -> list[str]:
    return by_component(enforcement, guardrails, capability_map).get(str(component_id), [])


def unclaimed(enforcement: Mapping[str, Any], guardrails: Iterable[Mapping[str, Any]],
              capability_map: Iterable[Mapping[str, Any]]) -> list[str]:
    """The families whose guardrails reach NO component in the published map — what the corpus is
    silent about, as opposed to what this design failed to cover. A rule that cannot tell the two
    apart refuses work nobody could have done."""
    of_guardrail = _components_of_guardrail(guardrails, capability_map)
    return sorted(family for family, guards in (enforcement or {}).items()
                  if not any(of_guardrail.get(g) for g in _list(guards)))
