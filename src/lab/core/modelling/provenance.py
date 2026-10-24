"""What ties a modelled element or relation to the input it came from (ADR 2026-10-24, D5).

`{source_ref, location, quote}`: which input, where in it, and the words that justify the item. The
quote is held against the source's text with the fabric's measured grounding rule, which tolerates
whitespace and nothing else. A quote that does not hold is FLAGGED as an open question (D5). It is
never a failure: the architect at the modelling gate decides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from lab.core.semantic.fabric.concepts import ground

__all__ = ["LOCATION_KEYS", "Provenance", "Source", "check"]

#: Where in a source: a page (PDF), a paragraph (prose), a figure (embedded image), a shape (diagram).
LOCATION_KEYS = ("page", "paragraph", "figure", "shape")
#: Locations read by vision or a diagram parse, whose words a prose source does not hold.
VISUAL_LOCATIONS = ("figure", "shape")


@dataclass(frozen=True)
class Source:
    """One input the run read. `ref` is the opaque key provenance points at. `text` is what a quote is
    held against, and None when the input has no text (an image read by vision). `aliases` are other
    names for the same artifact, such as a fabric catalogue IRI or a collaboration handle."""
    ref: str
    name: str
    media_type: str
    text: str | None = None
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """The envelope's listing. Never the text: an envelope rides approvals and records."""
        return {"ref": self.ref, "name": self.name, "media_type": self.media_type,
                "aliases": list(self.aliases)}


@dataclass(frozen=True)
class Provenance:
    source_ref: str
    location: Mapping[str, Any]
    quote: str

    def __post_init__(self):
        if not str(self.source_ref or "").strip():
            raise ValueError("provenance needs a source_ref")
        if not str(self.quote or "").strip():
            raise ValueError("provenance needs a verbatim quote")
        loc = dict(self.location or {})
        if not loc or set(loc) - set(LOCATION_KEYS):
            raise ValueError(f"location must name at least one of {LOCATION_KEYS} and nothing else; "
                             f"got {sorted(loc)}")
        object.__setattr__(self, "location", loc)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Provenance":
        return cls(source_ref=str(d.get("source_ref") or ""), location=d.get("location") or {},
                   quote=str(d.get("quote") or ""))

    def to_dict(self) -> dict:
        return {"source_ref": self.source_ref, "location": dict(self.location), "quote": self.quote}


def check(p: Provenance, sources: Mapping[str, Source]) -> str | None:
    """None when the quote holds in its source; otherwise the open-question KIND to raise.

    The kinds are "unknown-source" (the ref is not among the run's inputs), "quote-not-found" (the
    words are not in the source's text) and "unverifiable" (the source has no text to check against,
    such as an image, OR the location is a figure/shape whose words are not in the prose). An image-read
    item is never treated as confirmed: the architect verifies it at the modelling gate (user, 24 Oct)."""
    source = sources.get(p.source_ref)
    if source is None:
        return "unknown-source"
    if source.text is None or set(p.location) & set(VISUAL_LOCATIONS):
        return "unverifiable"
    return None if ground(p.quote, source.text) else "quote-not-found"
