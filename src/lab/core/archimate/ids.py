"""Stable identifiers — ONE home for the id rules that must agree across modules.

Element and relation ids are what ADOIT matches on at re-import: a relation whose id changes
between runs is a DUPLICATE in the repository, so the id must be a pure function of the
relation's endpoints and type, computed the same way wherever a relation is minted (the
workflow's own path and the Architect's accumulator tools). Pure, deterministic, no I/O.
"""
from __future__ import annotations

import hashlib
import re

from lab.core.canon import file_slug

__all__ = ["PREFIXES", "element_id", "prefix_for", "rid", "slug"]

#: Element-id prefixes the use-case mappers have always minted, kept so a model built by modelling and
#: one built by screening give the same element the same id. Every other type is prefixed by its
#: full kebab-case name (`prefix_for`): word initials collide (Driver, Device and Deliverable are all
#: "d"), full names cannot.
PREFIXES = {
    "BusinessActor": "ba-", "BusinessFunction": "bf-", "BusinessProcess": "bp-", "BusinessObject": "bo-",
    "Stakeholder": "stk-", "Driver": "drv-", "Goal": "goal-", "Outcome": "out-", "Requirement": "req-",
    "Constraint": "con-", "Capability": "cap-", "ApplicationService": "svc-",
    "ApplicationComponent": "ac-", "ApplicationFunction": "af-", "Node": "node-",
    "Deliverable": "dlv-", "WorkPackage": "wp-",
}


def prefix_for(atype: str) -> str:
    """The id prefix for an ArchiMate type: the table above, else the type's own name in kebab case."""
    return PREFIXES.get(atype) or "-".join(w.lower() for w in re.findall(r"[A-Z][a-z]*", atype)) + "-"


def element_id(atype: str, name: str) -> str:
    """A stable element id: the type's prefix plus a slug of the name. A pure function of both, so a
    re-run that keeps the name keeps the id. "" when the name has nothing to slug."""
    s = slug(name)
    return f"{prefix_for(atype)}{s}" if s else ""


def rid(src: str, rtype: str, tgt: str) -> str:
    """Stable relation id from its endpoints + type, so the same relationship keeps its id across
    runs/updates (the engine otherwise auto-numbers r1, r2… positionally)."""
    return "r-" + hashlib.md5(f"{src}|{rtype}|{tgt}".encode()).hexdigest()[:10]


def slug(text: str) -> str:
    """The prompt's element-id rule: lowercase, ASCII only (accents folded, the rest dropped),
    runs of spaces/punctuation -> one dash, no leading/trailing dash. "" when nothing survives.

    The core's `file_slug` IS this rule; an element id differs only in taking no length cap and in answering
    "" rather than a placeholder, so both are arguments rather than a second copy of the transformation."""
    return file_slug(text, default="", limit=len(text) + 1)
