"""Resolving a citation in a document's prose to the RECORD it names.

Impact answers "what does this change break?" by walking INBOUND over `fab:references`, and until 12 Oct
2026 the only thing that ever produced that edge was a synthesised draft pointing back at its source. So
a human-authored document that cited another in plain prose produced no edge at all, and impact over it
returned nothing — not because the graph was empty but because nothing had ever looked. Measured on three
eRx documents that cite each other by name: `references=0` on all of them.

A citation is TEXT, and the record it names is addressed by custody. There is no reliable bridge between
the two, so this rule is strict and says so when it cannot cross: **a wrong edge is worse than a missing
one.** A missing reference loses a path through the graph; a wrong one puts a document inside the blast
radius of a change that cannot affect it, and nothing on screen would reveal the mistake. The link is
asserted at rung X — EXTRACTED, which is what it is: read out of the text, not confirmed by anybody.
"""
from __future__ import annotations

import re

#: Strip a file extension before comparing: records are titled by FILE NAME and prose cites a HEADING,
#: which is the single commonest shape ("ADR-041 Prescription identifier format" naming
#: `ADR-041-prescription-identifier.md`).
_EXT = re.compile(r"\.(md|markdown|docx?|pdf|txt|json|html?)$", re.I)
_SEP = re.compile(r"[^a-z0-9]+")
#: Below this many characters a "title" is too generic to carry a citation — "notes", "brs", "v2".
MIN_CHARS = 8


def norm(s: str) -> str:
    """Lowercase, extension dropped, every run of punctuation and space collapsed to ONE space."""
    return _SEP.sub(" ", _EXT.sub("", str(s or "")).lower()).strip()


def resolve(citation: str, candidates: list[dict], *, exclude: str = "") -> str | None:
    """The IRI the citation names, or None. `candidates` is what a bounded search proposed —
    [{iri, title}] — so the fuzzy half is the SEARCH and the decision here is a pure rule.

    A candidate matches when its normalised title and the normalised citation are equal, or one is a
    whole-word PREFIX of the other. Prefix, not substring: 'Dispensing rules' must not match 'Rules for
    dispensing controlled substances', where the words coincide and the documents do not.

    **Exactly one match wins.** Two candidates matching is the duplicate-title case the fabric exists to
    surface, and linking either would be a coin toss presented as a fact — the same reason `vocab_link`
    refuses a term that two concepts in one scheme both claim.

    What it deliberately does NOT do is expand an acronym or score a similarity. 'eRx Business
    Requirements Specification' against `eRx-BRS.md` is a real citation this rule cannot prove, and it
    stays unlinked rather than become a relationship nobody can check.
    """
    want = norm(citation)
    if len(want) < MIN_CHARS:
        return None
    hits = []
    for c in candidates or []:
        iri = str(c.get("iri") or "")
        if not iri or iri == exclude:
            continue
        have = norm(c.get("title"))
        if len(have) < MIN_CHARS:
            continue
        if have == want or _prefix(have, want) or _prefix(want, have):
            hits.append(iri)
    return hits[0] if len(set(hits)) == 1 else None


def _prefix(short: str, long: str) -> bool:
    """`short` is a WHOLE-WORD prefix of `long` — 'adr 041 prescription identifier' of
    'adr 041 prescription identifier format', but not 'rule' of 'rules'."""
    return len(short) < len(long) and long.startswith(short + " ")


__all__ = ["resolve", "norm", "MIN_CHARS"]
