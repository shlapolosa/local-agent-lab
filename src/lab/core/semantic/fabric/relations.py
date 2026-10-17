"""Relation candidates from a structured diagram — the feeder for the vocabulary's TOPOLOGY.

Every other input tells the fabric what a document is ABOUT. A diagram tells it how the things it is about are
CONNECTED: the boxes are terms and the arrows are relations, which makes it the one artifact that can grow the
half of a vocabulary a classifier never touches. Steward A decides membership; this is what steward B has to
work from.

Pure, like `concepts` and `citations`: the vocabulary arrives as two seams — `resolve` (a term to a concept id,
or "") and `states` (does the vocabulary already say this?) — so the rules are testable without a scheme, a
parser or a store, and the same function serves a `.vsdx`, a Lucidchart export or anything else that yields
boxes and arrows.

Two things it will not do, both deliberate:
- **It never names an unlabelled arrow.** The diagram says two concepts connect; it does not say how, and a
  typed predicate is precisely what the derived rung needs. Inventing one would put an edge in the vocabulary
  that no author drew, so the candidate carries none and says it needs one.
- **It proposes; it never writes.** A relation enters the vocabulary through `vocab_relate`, which takes a
  steward's name — for the same reason admission does.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from lab.core.semantic.fabric.concepts import normalise

#: A bound on one call's arrows. Generous against a real diagram — the largest measured in this lab recovered
#: 44 connectors — and a REFUSAL rather than a truncation, because a silently halved diagram proposes a
#: topology nobody drew. It exists because the arrows arrive INLINE: CLAUDE.md's measured invariant is that a
#: large nested object passed as a tool argument is emitted only stochastically, so the by-ref door
#: (`arrows_ref`, as `archimate_render` takes `spec_ref`) is the upgrade the moment a model rather than a
#: deterministic surface is the caller.
MAX_ARROWS = 500

__all__ = ["candidates", "normalise", "MAX_ARROWS"]


def _ends(arrow: Mapping[str, Any]) -> tuple[str, str]:
    return str(arrow.get("from") or "").strip(), str(arrow.get("to") or "").strip()


def candidates(arrows: Iterable[Mapping[str, Any]], *, resolve: Callable[[str], str],
               states: Callable[[str, str, str], bool]) -> tuple[list[dict], list[str]]:
    """The relations a diagram proposes, collapsed and ordered — and the boxes that resolved to NOTHING.

    Both halves always, because the gaps are the useful half of a diagram the vocabulary has not caught up
    with. A box named nowhere is not an error: it is a term a steward can admit, and dropping it silently is
    how a diagram stops being evidence of anything.

    One row per distinct (subject, predicate, object), counting the arrows that drew it: the same relation on
    four pages is one decision, and four identical rows would bury the few that differ — the lesson the
    conflict record and the approval backlog both taught. Ordered on the triple, so the same diagram yields
    the same list twice and a reviewer can diff two runs."""
    arrows = list(arrows)
    if len(arrows) > MAX_ARROWS:
        raise ValueError(f"{len(arrows)} arrows in one call, above the {MAX_ARROWS} this takes inline — "
                         "split the diagram by page, or pass it by reference")
    found: dict[tuple[str, str, str], dict] = {}
    missing: dict[str, None] = {}
    for arrow in arrows:
        src, tgt = _ends(arrow)
        if not src or not tgt:
            continue                                  # an arrow with an end we cannot read says nothing
        sid, tid = resolve(src), resolve(tgt)
        for term, cid in ((src, sid), (tgt, tid)):
            if not cid:
                missing.setdefault(term, None)
        if not sid or not tid or sid == tid:
            # Resolving to ONE concept happens when a page carries both a preferred and an alt label: the
            # arrow is real and the relation is not, because a concept related to itself says nothing.
            continue
        predicate = str(arrow.get("label") or "").strip()
        if states(sid, predicate, tid):
            continue                                  # already stated; proposing it again asks for nothing
        # Case-folded in the KEY, first spelling kept as the value: "Realises" and "realises" are one
        # relation, exactly as "Agent" and "agent" are one ambiguity to the conflict record.
        key = (sid, predicate.casefold(), tid)
        row = found.get(key)
        if row is None:
            found[key] = {"subject": sid, "predicate": predicate, "object": tid,
                          "subject_term": src, "object_term": tgt, "arrows": 1,
                          "unnamed": not predicate}
        else:
            row["arrows"] += 1
    out = [found[k] for k in sorted(found)]      # ordered on the triple, so two runs are diffable
    return out, sorted(missing)
