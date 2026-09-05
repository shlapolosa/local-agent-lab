"""One content-addressed id formula for the whole semantic layer.

Extracted from the SKOS helper, which hardcoded a `cap-` prefix because capabilities were the only
thing that needed stable ids. Persons, decisions, concepts and action items need the same property —
the same content always yields the same id, so re-ingesting a meeting does not duplicate anything —
but they are not capabilities and should not carry a prefix that says they are.

The prefix is the caller's: it makes a bare id self-describing in a query result, which matters
because SPARQL results here are shortened to their fragment and the prefix is the only thing that
survives.
"""
from __future__ import annotations

import hashlib

__all__ = ["content_id"]


def content_id(prefix: str, *parts: str) -> str:
    """`<prefix><10 hex chars>` — deterministic, stable across processes and machines.

    Whatever is passed in `parts` defines identity: include the meeting to make something local to
    it, leave it out to make the node shared across every meeting that mentions it. That choice is
    the difference between "this decision" and "any decision worded like this", so it belongs to the
    caller rather than to a rule here.
    """
    return prefix + hashlib.md5("|".join(parts).encode()).hexdigest()[:10]
