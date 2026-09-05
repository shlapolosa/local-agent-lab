"""Stable ids for meeting knowledge. Content-addressed, so re-ingesting a meeting duplicates nothing.

The SCOPE of each id is the design decision, not an implementation detail:

  * a **concept** is scoped to its canonical label alone, so "Claims Adjudication" is ONE node in
    every meeting that mentions it — that is what makes cross-meeting questions answerable;
  * a **decision** and an **action** are scoped to their meeting, because the same sentence said in
    two meetings is two commitments, not one;
  * a **person** is scoped to their directory identity when there is one, and to the canonical tag
    otherwise, with a different prefix for each so a query can never mistake a human's free-text
    guess for a directory fact.
"""
from __future__ import annotations

from lab.core.canon import canonical
from lab.core.semantic.ids import content_id

__all__ = ["CONCEPT", "DECISION", "ACTION", "MEETING", "PEOPLE",
           "concept_iri", "decision_iri", "action_iri", "meeting_iri", "person_iri"]

CONCEPT = "urn:lab:semantic:concept#"
DECISION = "urn:lab:semantic:decision#"
ACTION = "urn:lab:semantic:action#"
MEETING = "urn:lab:semantic:meeting-instance#"
PEOPLE = "urn:lab:semantic:people#"


def concept_iri(label: str) -> str:
    """Shared across every meeting — the join that the whole concept-centred model rests on."""
    return CONCEPT + content_id("cpt-", canonical(label))


def decision_iri(meeting_id: str, statement: str) -> str:
    return DECISION + content_id("dec-", meeting_id, canonical(statement))


def action_iri(meeting_id: str, commitment: str, owner: str) -> str:
    return ACTION + content_id("act-", meeting_id, canonical(commitment), owner)


def meeting_iri(meeting_id: str) -> str:
    return MEETING + content_id("mtg-", meeting_id)


def person_iri(identity: str = "", tag: str = "") -> str:
    """`per-` for a directory identity, `tag-` for a free-text one.

    Two prefixes on purpose. Results here are shortened to their fragment, so the prefix is the only
    thing that survives to tell a reader whether a node is a directory fact or a human's guess — and
    a query that cannot tell them apart will eventually treat one as the other.
    """
    if identity.strip():
        return PEOPLE + content_id("per-", identity.strip().lower())
    if tag.strip():
        return PEOPLE + content_id("tag-", canonical(tag))
    raise ValueError("a person needs a directory identity or a tag")
