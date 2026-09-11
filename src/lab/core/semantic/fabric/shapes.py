"""SHACL validation of the fabric's metadata — the metadata-only rule (NFR-2) and the owner-provenance rule
(NFR-3) as executable checks, run in CI over fixtures and by semantic-mcp on every write."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pyshacl import validate as _validate
from rdflib import Dataset, Graph

HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def shapes_graph() -> Graph:
    """Parsed once per process: the shapes are data on disk and validation runs on every write."""
    g = Graph()
    g.parse(HERE / "fab-shapes.ttl", format="turtle")
    return g


@dataclass(frozen=True)
class Report:
    conforms: bool
    messages: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.conforms


def validate(data: Graph | Dataset) -> Report:
    """Validate a graph — or a whole Dataset, so the SPARQL constraint can see WHICH named graph holds a
    triple — against the fabric's shapes. Returns a Report; never raises on a violation, so a caller
    decides whether to refuse (a write) or fail (a build)."""
    conforms, _graph, text = _validate(data, shacl_graph=shapes_graph(), inference="none",
                                       abort_on_first=False, allow_warnings=False)
    messages: list[str] = []
    if not conforms:
        for line in str(text).splitlines():
            line = line.strip()
            if line.startswith("Message:"):
                messages.append(line[len("Message:"):].strip())
    return Report(bool(conforms), tuple(messages))


__all__ = ["validate", "shapes_graph", "Report"]
