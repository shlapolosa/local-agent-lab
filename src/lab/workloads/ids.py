"""Stable identifiers — ONE home for the id rules that must agree across modules.

Element and relation ids are what ADOIT matches on at re-import: a relation whose id changes
between runs is a DUPLICATE in the repository, so the id must be a pure function of the
relation's endpoints and type, computed the same way wherever a relation is minted (the
workflow's own path and the Architect's accumulator tools). Pure, deterministic, no I/O.
"""
from __future__ import annotations

import hashlib

from lab.platform.filetypes import file_slug

__all__ = ["rid", "slug"]


def rid(src: str, rtype: str, tgt: str) -> str:
    """Stable relation id from its endpoints + type, so the same relationship keeps its id across
    runs/updates (the engine otherwise auto-numbers r1, r2… positionally)."""
    return "r-" + hashlib.md5(f"{src}|{rtype}|{tgt}".encode()).hexdigest()[:10]


def slug(text: str) -> str:
    """The prompt's element-id rule: lowercase, ASCII only (accents folded, the rest dropped),
    runs of spaces/punctuation -> one dash, no leading/trailing dash. "" when nothing survives.

    The kernel's `file_slug` IS this rule; an element id differs only in taking no length cap and in answering
    "" rather than a placeholder, so both are arguments rather than a second copy of the transformation."""
    return file_slug(text, default="", limit=len(text) + 1)
