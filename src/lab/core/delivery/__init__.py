"""The DELIVERY-CONTEXT port (docs/fabric/notes/2026-09-10-knowledge-graph-axes.md): the container delivery
work is filed under — a use case, a meeting, a submission, later a work item. One class of several; the
delivery axis of the graph hangs off it, identity does not. Core: imports nothing below it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

KINDS = ("usecase", "meeting", "submission", "workitem")
IRI_BASE = "urn:fabric:context:"


@dataclass(frozen=True)
class DeliveryContext:
    """`<kind>:<id>` plus what a person needs to recognise it. `owner` is a directory principal or ""."""
    kind: str
    id: str
    label: str = ""
    owner: str = ""
    source: str = ""          # which port knows it: "lab" (a run), "work" (a work-item adapter)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"delivery context kind must be one of {list(KINDS)}, not {self.kind!r}")
        if not isinstance(self.id, str) or not self.id.strip() or any(c.isspace() for c in self.id) or "://" in self.id:
            raise ValueError(f"a delivery context id is an opaque id, got {self.id!r}")

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def iri(self) -> str:
        return f"{IRI_BASE}{self.kind}:{self.id}"

    @classmethod
    def parse(cls, key: str, **fields) -> "DeliveryContext":
        kind, sep, ident = (key or "").partition(":")
        if not sep:
            raise ValueError(f"a delivery context key is <kind>:<id>, got {key!r}")
        return cls(kind, ident, **fields)


@runtime_checkable
class DeliveryRepository(Protocol):
    """What the fabric asks of whoever knows delivery containers."""

    def context(self, key: str) -> DeliveryContext | None: ...


__all__ = ["DeliveryContext", "DeliveryRepository", "KINDS", "IRI_BASE"]
