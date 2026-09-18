"""Composition move 5 — bind every obligation to a component the design actually selected.

Four of the five published moves were implemented; this one was named in `composition.py`'s
docstring and never written. What stood in for it, `Composition.unbound`, names an obligation that
no present FAMILY carries — move 3 under move 5's name. A family is a shape ("F5 Authorisation and
approval is present"), not something anyone can point at in a deployment, so an obligation covered
by a family may still have nothing enforcing it.

M4 states the test this module implements:

    Selection is not complete until every obligation resolves to a named enforcement point on a
    selected component or on a declared boundary interface carrying a responsibility split and a
    named owner, or is explicitly labelled advisory.

The chain is the corpus's own, followed rather than summarised:

    obligation --(guardrails.cap)--> "Domain · Capability"
               --(ai-capability-map.components)--> component ids
               ∩ what this design selected

**Two ways to fail, deliberately kept apart.** `unbound` means the corpus can enforce this and the
design chose nothing that does — the architect's to fix, by selecting the component. `unenforceable`
means the corpus cannot bind it at whatever version the run pinned: the guardrail names a capability
the map lacks, or one reaching no component, or the obligation is prose carrying no guardrail id at
all. No selection repairs that, and failing a design for it charges an architect for a gap in the
framework. Measured 18 Sep 2026: before the map was repaired, 20 of 24 live guardrails were in the
second class — so a single count would have read as an architect who selected nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from lab.core.usecase import capabilities

__all__ = ["Binding", "EnforcementError", "bind", "candidates"]


class EnforcementError(ValueError):
    """The binding could not be computed, and a half-computed one must not be returned."""


@dataclass(frozen=True)
class Binding:
    """What enforces what, and what nothing does."""

    bound: Mapping[str, tuple[str, ...]]
    unbound: tuple[str, ...]
    unenforceable: tuple[str, ...]
    advisory: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """M4's exit test. Advisory counts as resolved; it was resolved by someone saying so."""
        return not self.unbound and not self.unenforceable


def candidates(guardrails: Sequence[Mapping[str, Any]] | None,
               capability_map: Sequence[Mapping[str, Any]] | None) -> dict[str, tuple[str, ...]]:
    """guardrail id -> every catalogue component that COULD enforce it, through the published two
    hops. Built once, from corpora read under the run's pin, and then used twice: it is what step 21
    is shown (so the architect can select an enforcing component deliberately) and what its gate
    binds against (so the two cannot disagree).

    Both corpora are REQUIRED. An empty candidate map is indistinguishable from a design that
    selected nothing, and these are pinned reads — an absent one is a plumbing failure, not evidence
    about the design.
    """
    if guardrails is None or capability_map is None:
        raise EnforcementError(
            "the guardrails and the technology capability map must both be supplied — read them "
            "under the run's pin; binding against an absent corpus would report every obligation "
            "as unbound and blame the design for it")
    by_capability: dict[str, list[str]] = {}
    for row in capability_map:
        if isinstance(row, Mapping):
            by_capability.setdefault(capabilities.key(row), []).extend(
                capabilities.refs(row.get("components")))
    out: dict[str, tuple[str, ...]] = {}
    for row in guardrails:
        if not isinstance(row, Mapping) or not str(row.get("id") or "").strip():
            continue
        found: set[str] = set()
        for ref in capabilities.refs(row.get("cap")):
            found |= set(by_capability.get(ref, ()))
        out[str(row["id"]).strip()] = tuple(sorted(found))
    return out


def bind(obligations: Iterable[str], *, candidates: Mapping[str, Sequence[str]] | None,
         selected: Iterable[str], advisory: Iterable[str] = ()) -> Binding:
    """Bind each obligation to the selected components that enforce it.

    `obligations` are guardrail ids (a mapping cell may also state one in prose, which carries no
    id and is therefore unenforceable by construction). `selected` are the component ids step 21
    chose. `advisory` are the obligations a human has explicitly excused — named by the caller and
    never inferred, because inferring it would mean an obligation nothing enforces silently becomes
    one nothing needs to.

    `candidates` comes from `candidates()` above and may not be None, for the same reason the
    corpora may not: nothing to bind against and nothing selected produce the same answer.
    """
    if candidates is None:
        raise EnforcementError("the candidate enforcement points must be supplied — see "
                               "`enforcement.candidates()`; an absent map binds nothing and reads "
                               "as a design that selected nothing")

    enforcers = candidates
    chosen, excused = set(selected), set(advisory)
    bound: dict[str, tuple[str, ...]] = {}
    unbound: list[str] = []
    unenforceable: list[str] = []

    for obligation in sorted({str(o).strip() for o in obligations if str(o).strip()}):
        able = enforcers.get(obligation)
        if not able:
            # No guardrail of that id, or one whose capability reaches no component. Either way the
            # corpus cannot bind it, and calling it advisory would hide the artifact defect.
            unenforceable.append(obligation)
        elif carried := tuple(c for c in able if c in chosen):
            bound[obligation] = carried
        elif obligation in excused:
            continue
        else:
            unbound.append(obligation)

    return Binding(bound=bound, unbound=tuple(unbound), unenforceable=tuple(unenforceable),
                   advisory=tuple(sorted(excused - set(unenforceable))))
