"""What the mapper needs to know about a speaker — declared in the DOMAIN, importing nothing.

`lab.platform.contracts.SpeakerMap` is the APPROVAL contract: how a human's answer travels through
the gate and back. This is the domain's own, much smaller idea: a name to attribute a commitment to.
They are deliberately different types, and the workload translates between them at the edge, because
the tier rule is that `core` imports only `core` — and because the mapper should not care that the
answer arrived through an approval at all.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Speaker", "Speakers"]


@dataclass(frozen=True)
class Speaker:
    """One anonymous label resolved to a human: a directory identity, or else a free tag."""

    label: str
    identity: str = ""
    tag: str = ""

    def __post_init__(self) -> None:
        if not (self.label or "").strip():
            raise ValueError("a speaker needs the label it answers for")
        if bool(self.identity.strip()) == bool(self.tag.strip()):
            raise ValueError(f"{self.label}: give exactly one of identity or tag")

    @property
    def display(self) -> str:
        """What the graph and the transcript say — never the raw address."""
        return self.tag.strip() or self.identity.split("@")[0].strip()


@dataclass(frozen=True)
class Speakers:
    """Every speaker in one transcript, resolved together."""

    entries: tuple[Speaker, ...] = ()

    @classmethod
    def from_answer(cls, answer: dict) -> "Speakers":
        """The wire shape a human's answer arrives in — the one place the domain accepts it."""
        return cls(tuple(Speaker(label=k, identity=str((v or {}).get("identity") or ""),
                                 tag=str((v or {}).get("tag") or ""))
                         for k, v in (answer or {}).items()))

    def of(self, label: str) -> Speaker:
        for e in self.entries:
            if e.label == label:
                return e
        raise KeyError(f"{label} was never identified — every label the transcript uses must be answered")
