"""The owner map — who is accountable for an artifact, LOOKED UP and never guessed (FR-2.2.2, BR-3, BR-6).

Three sources, in order of authority: a folder or drive rule (site/library/folder → owner), the producing run's
requester for a lab product, and — last, and only so a person has something to correct — the item's author as
the provider records it. Unresolved is an honest, visible state: the review asks the steward.
Pure: a dict in, a (owner, method) out; the file is read once by the composition root."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lab.core.collab.model import ContentHandle, HandleKind

__all__ = ["OwnerMap"]

REQUESTER = "requester"        # the lab rule that means "the person who asked for the run"


@dataclass(frozen=True)
class OwnerMap:
    collab: dict[str, str] = field(default_factory=dict)   # "<drive>" | "<drive>/<folder prefix>" -> owner
    lab: dict[str, str] = field(default_factory=dict)      # process -> owner | "requester"

    @classmethod
    def empty(cls) -> "OwnerMap":
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "OwnerMap":
        out = {}
        for section in ("collab", "lab"):
            rules = dict(data.get(section) or {})
            if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in rules.items()):
                raise ValueError(f"owner map {section!r}: every rule is a string key to a non-empty string owner")
            out[section] = {k.strip("/"): v for k, v in rules.items()}
        return cls(**out)

    @classmethod
    def load(cls, path: str) -> "OwnerMap":
        p = Path(path)
        return cls.from_dict(json.loads(p.read_text())) if p.exists() else cls.empty()

    def resolve(self, pointer: dict, *, produced_by: str = "", requester: str = "", path: str = "",
                author: str = "") -> tuple[str, str]:
        """(owner, method) — method names how the owner was found, which the assertion records at rung C."""
        source = pointer.get("source")
        if source == "lab":
            rule = self.lab.get(produced_by or "")
            if rule == REQUESTER:
                return (requester, REQUESTER) if requester else ("", "")
            return (rule, "owner-map") if rule else ("", "")
        handle = pointer.get("handle")
        if source == "collab" and handle:
            h = ContentHandle.parse(str(handle))
            if h.kind is HandleKind.ITEM:
                where = "/".join(p for p in (h.scope, path.strip("/")) if p)
                best = max((k for k in self.collab if where == k or where.startswith(k + "/")), key=len, default="")
                if best:
                    return self.collab[best], "owner-map"
        return (author, "item-author") if author else ("", "")
