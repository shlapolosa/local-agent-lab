"""The DiagramRenderer port and the view it renders — what a picture of the knowledge graph IS, stated by the
domain and rendered by whoever can.

CLAUDE.md names `DiagramRenderer` as a domain port, and this is it: the domain says a topology view is a set of
nodes and labelled edges, each carrying HOW IT IS KNOWN, and an adapter decides whether that becomes SVG in a
page, an interactive graph, a draw.io file or a PNG. The alternative — a renderer that reaches into the fabric
and reads rung graphs itself — would put the provenance ladder's vocabulary inside a drawing library.

A view is built from the CURRENT graph every time it is asked for. There is no stored layout and no cached
picture: a knowledge graph that is worth drawing is one that changes, and a drawing of last week's state that
looks exactly like this week's is the failure mode worth designing out.

Pure: dataclasses and a Protocol. No rdflib, no HTTP, no files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Node", "Edge", "TopologyView", "Rendered", "GraphRenderer", "FOCUS", "PROPOSED", "VOCABULARY",
           "ARTIFACT", "CONCEPT", "PALETTE", "MEANING", "UNKNOWN", "colour", "meaning"]

#: statuses that are not a provenance rung. A rung says how the FABRIC knows something; these three say what a
#: node is FOR: the thing being looked at, a term nobody has admitted yet, and the vocabulary's own structure.
FOCUS, PROPOSED, VOCABULARY = "focus", "proposed", "vocabulary"

#: what a node IS. Constants for the same reason the statuses are: the renderer BRANCHES on this across a
#: tier boundary, and a typo there would draw every artifact as a concept without anything failing.
ARTIFACT, CONCEPT = "artifact", "concept"


#: status -> (fill, stroke, what it means IN WORDS). Here rather than in an adapter because it is the
#: fabric's visual LANGUAGE, not one renderer's styling: the words are the legend AND the words the bot is
#: told to answer with, so a picture and a sentence never disagree — and two adapters that coloured the same
#: rung differently would break that across two pages of the same record. The hex is presentation living in
#: the domain, deliberately: one shared table is worth more than the purity of keeping colour out of it.
PALETTE: dict[str, tuple[str, str, str]] = {
    FOCUS: ("#1f2a44", "#0b1020", "this record"),
    "C": ("#2e7d32", "#1b5e20", "looked up"),
    "X": ("#1565c0", "#0d47a1", "found in the content"),
    "H": ("#6a1b9a", "#4a148c", "confirmed by a person"),
    "S": ("#ef6c00", "#e65100", "suggested by AI"),
    "D": ("#00838f", "#006064", "derived by a rule"),
    VOCABULARY: ("#546e7a", "#37474f", "the vocabulary"),
    PROPOSED: ("#b71c1c", "#7f0000", "proposed, not admitted"),
}
UNKNOWN = ("#455a64", "#263238", "unclassified")
#: status -> the words alone, which is all a legend or a sentence needs.
MEANING: dict[str, str] = {k: v[2] for k, v in PALETTE.items()}


def colour(status: str) -> tuple[str, str, str]:
    """(fill, stroke, meaning) for a status — never a KeyError, because a rung this table has not met yet
    must still be drawn as something a person can see and ask about."""
    return PALETTE.get(status, UNKNOWN)


def meaning(status: str) -> str:
    return colour(status)[2]


@dataclass(frozen=True)
class Node:
    """One thing in the picture. `kind` is what it is; `status` is how it is known — a rung (S, X, C, H, D) or
    one of FOCUS / PROPOSED / VOCABULARY.

    `facets` are the (name, value) pairs a VIEWER may narrow by — lifecycle state, source, document type.
    A tuple of pairs rather than three named fields, and rather than a dict, for three reasons: the node
    stays frozen and hashable; a renderer builds its filter controls from the facets a view ACTUALLY
    contains, so it explains nothing a person cannot act on; and a new way to narrow is a new pair at the
    one place that knows the domain, not a change to this port and every adapter under it.

    It earned its place rather than being anticipated: drawing the whole corpus for the first time
    (10 Oct 2026) produced 107 edges of which two thirds were the lab's own test output, and a picture
    nobody could read until it could be narrowed to the documents a person actually wrote."""
    id: str
    label: str
    kind: str                       # ARTIFACT | CONCEPT
    status: str
    note: str = ""
    facets: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.label:
            raise ValueError(f"a node carries an id and a label: {self!r}")
        for pair in self.facets:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise ValueError(f"a facet is a (name, value) pair: {pair!r}")

    def facet(self, name: str, default: str = "") -> str:
        return next((v for k, v in self.facets if k == name), default)


@dataclass(frozen=True)
class Edge:
    """A labelled connection. The label is the PREDICATE in the words the vocabulary uses, because "related" on
    its own is the answer the fabric already had before it owned an ontology."""
    source: str
    target: str
    label: str
    status: str

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError(f"an edge says HOW two things are connected: {self!r}")


@dataclass(frozen=True)
class TopologyView:
    """What one artifact is about, and what that connects it to, as of now."""
    title: str
    focus: str
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    as_of: str = ""
    subtitle: str = ""

    def __post_init__(self) -> None:
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("two nodes share an id")
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in ids:
                    raise ValueError(f"edge {e.source} -{e.label}-> {e.target} names a node the view lacks: {end}")
        if self.focus and self.focus not in ids:
            raise ValueError(f"the focus {self.focus!r} is not one of the view's nodes")

    def node(self, nid: str) -> Node:
        return next(n for n in self.nodes if n.id == nid)

    @property
    def facet_names(self) -> tuple[str, ...]:
        """Every facet name present, in first-seen order — the filters a renderer may offer."""
        seen: list[str] = []
        for n in self.nodes:
            for name, _ in n.facets:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)

    def facet_values(self, name: str) -> tuple[str, ...]:
        """The distinct values of one facet, sorted — the choices under that filter. A node that carries
        the facet with an empty value is NOT a choice: "" means "not recorded", which is a thing to see
        rather than a thing to pick."""
        return tuple(sorted({v for n in self.nodes for k, v in n.facets if k == name and v}))

    @property
    def statuses(self) -> tuple[str, ...]:
        """Every status in the view, in first-seen order — what a legend must explain."""
        seen: list[str] = []
        for n in self.nodes:
            if n.status not in seen:
                seen.append(n.status)
        return tuple(seen)


@dataclass(frozen=True)
class Rendered:
    """Bytes plus what they are, so a caller can store or serve them without guessing."""
    content: bytes
    media_type: str
    suffix: str


@runtime_checkable
class GraphRenderer(Protocol):
    """Turn a view into something a person can open. An adapter is chosen by configuration, never imported by
    the domain — the same shape the store, the collaboration platform and the corpus already use."""

    name: str

    def render(self, view: TopologyView) -> Rendered: ...
