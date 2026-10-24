"""The closest valid names for a wrong one — what a refusal offers so a retry can correct itself.

A HINT, never a merge: nothing here decides that two names mean one thing (that is `lab.core.canon`'s
conservative job). It only ranks the published vocabulary against a near miss so the message an agent
reads names what it probably meant.
"""
from __future__ import annotations

import difflib

from lab.core.canon import squash

__all__ = ["suggest"]


def suggest(value: str, vocab: tuple[str, ...], n: int = 3) -> list[str]:
    """Closest valid names for a wrong one: exact match ignoring case/spaces/underscores first
    ("application component" -> ApplicationComponent), then difflib similarity, then any valid
    name containing the given word ("Component" -> ApplicationComponent, …)."""
    if not isinstance(value, str) or not value.strip():
        return []
    nv = squash(value)
    exact = [t for t in vocab if squash(t) == nv]
    if exact:
        return exact
    close = difflib.get_close_matches(value, vocab, n=n, cutoff=0.6)
    if close:
        return close
    return [t for t in vocab if nv and (nv in squash(t) or squash(t) in nv)][:n]
