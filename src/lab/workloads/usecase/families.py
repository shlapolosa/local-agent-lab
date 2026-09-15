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

It is PARTIAL by nature, and the partiality is the point: only ten of twenty-six guardrails name a
capability, so some families resolve to no component at all — not because nothing realises them, but
because the corpus does not say. `unclaimed()` names exactly those, and the rule that consumes this
stays silent about them. A derivation that guessed the rest would be the authored column again,
wearing a join.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

__all__ = ["by_component", "of_component", "unclaimed"]


def _list(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or "").replace(",", ";").split(";") if v.strip()]


def _capability_key(row: Mapping[str, Any]) -> str:
    return f'{str(row.get("domain", "")).strip()} · {str(row.get("capability", "")).strip()}'.strip(" ·")


def _components_by_capability(capability_map: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in capability_map or ():
        if isinstance(row, Mapping):
            out.setdefault(_capability_key(row), []).extend(_list(row.get("components")))
    return out


def _components_of_guardrail(guardrails: Iterable[Mapping[str, Any]],
                             capability_map: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    by_capability = _components_by_capability(capability_map)
    out: dict[str, set[str]] = {}
    for row in guardrails or ():
        if not isinstance(row, Mapping) or not row.get("id"):
            continue
        found: set[str] = set()
        for name in _list(row.get("cap")):
            found |= set(by_capability.get(name, ()))
        out[str(row["id"]).strip()] = found
    return out


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
