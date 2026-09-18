"""What a design still OWES, in the order a reviewer needs to hear it.

A conformance approval hands a person a package of twenty-five sections and asks them to judge it.
Run 8 (15 Sep 2026) proceeded with four obligations bound to no enforcement point, eleven components
that could not be priced, a benefit that could not be computed and three building blocks left out of
the drawing — every one of them recorded in the package, and none of them in front of the reviewer,
whose summary was literally empty. A design that reads well is not a design that is complete; this is
the module that says the difference out loud.

Pure: it reads the package and returns lines. Ordered by what would be worst to miss — an obligation
nobody enforces first (Q5.3 makes that a stop), then what the architect was asked to resolve and did
not, then the figures, then what is merely absent from a picture.
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["counts", "owed"]


def _list(value) -> list[str]:
    return [str(v).strip() for v in (value or ()) if str(v).strip()]


def owed(package: Mapping[str, Any]) -> list[str]:
    """One line per thing outstanding, worst first. Empty means nothing is."""
    composition = package.get("composition") or {}
    selection = package.get("component_selection") or {}
    cost = package.get("cost") or {}
    benefit = (package.get("benefit") or {}).get("summary") or {}
    views = package.get("views") or {}
    out: list[str] = []

    # Composition move 5 FIRST: an obligation nothing in the deployment enforces. The two ways it
    # can fail have different owners and the reviewer is who acts on the difference.
    binding = package.get("enforcement") or {}
    for guardrail in _list(binding.get("unbound")):
        out.append(f"{guardrail} is required by this design and NO SELECTED COMPONENT enforces it — "
                   f"an obligation nobody enforces is the one failure this assessment exists to stop")
    if _list(binding.get("unenforceable")):
        out.append(f"{', '.join(_list(binding['unenforceable']))}: the pinned corpus binds these to "
                   f"no component at all — a gap in the framework, not in this design, and no "
                   f"selection here can close it")
    # Move 3, and it says so. A family is a SHAPE; an obligation covered by a present family may
    # still have nothing enforcing it, so calling this "no enforcement point" told a reviewer a
    # stronger thing than the data supported while the real answer above sat unread in the package.
    for guardrail in _list(composition.get("unbound")):
        out.append(f"{guardrail} is required by this design and no family this composition "
                   f"requires carries it")
    for violation in (package.get("obligations") or {}).get("violations") or ():
        if isinstance(violation, Mapping):
            out.append(f'step {violation.get("step")}: {violation.get("reason")}')
    out += [f"unresolved: {u}" for u in _list(selection.get("unresolved"))]
    out += [f"cost: {r}"[:300] for r in _list(cost.get("requires_input"))]
    if cost.get("gap_flags"):
        out.append(f"{len(cost['gap_flags'])} selected component(s) have no line in the price "
                   f"catalogue — the run cost is the priced part only")
    out += [f"benefit: {r}" for r in _list(benefit.get("requires_input"))]
    for number, why in sorted((package.get("pending_steps") or {}).items()):
        out.append(f"step {number} did not run: {why}")
    for number, why in sorted((package.get("defaulted_steps") or {}).items()):
        out.append(f"step {number} recorded a declared default: {why}")
    if views.get("cafe_unplaced"):
        out.append(f"{len(views['cafe_unplaced'])} building block(s) are not in the solution view — "
                   f"they sit outside the reference architecture's zones and somebody else owns them")
    out += [f"view: {w}"[:300] for w in _list(views.get("warnings"))]
    return out


def counts(package: Mapping[str, Any]) -> dict:
    """The headline a reviewer reads before the lines — and the figures they judge them against."""
    composition = package.get("composition") or {}
    cost = package.get("cost") or {}
    benefit = (package.get("benefit") or {}).get("summary") or {}
    recommendation = (package.get("benefit") or {}).get("recommendation") or {}
    selected = (package.get("component_selection") or {}).get("selected") or []
    model = package.get("model") or {}
    priced = len(selected) - len(cost.get("gap_flags") or ())
    binding = package.get("enforcement")
    return {"owed": owed(package),
            # M4's exit test, as one word. None for a package staged before the binding existed —
            # those approvals stay open, and False would accuse them of something never checked.
            "obligations_bound": (None if binding is None else bool(binding.get("complete"))),
            "recommendation": recommendation.get("verdict", ""),
            # The run cost covers the components the price catalogue carries. Presenting a figure
            # that priced five of sixteen as "the cost" is the same failure as a summary that says
            # nothing: it reads complete (run 8, 15 Sep 2026 — eleven components with no line).
            "components_priced": max(priced, 0),
            "topology": composition.get("topology", ""),
            "families": len(composition.get("families") or ()),
            "components": len(selected),
            "year_one_cost": (cost.get("year_one") or {}).get("expected"),
            "annual_benefit": benefit.get("annual_benefit"),
            "payback_months": benefit.get("payback_months"),
            "elements": len(model.get("elements") or ()),
            "relations": len(model.get("relations") or ())}
