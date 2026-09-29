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
           "ARTIFACT", "CONCEPT"]

#: statuses that are not a provenance rung. A rung says how the FABRIC knows something; these three say what a
#: node is FOR: the thing being looked at, a term nobody has admitted yet, and the vocabulary's own structure.
FOCUS, PROPOSED, VOCABULARY = "focus", "proposed", "vocabulary"

#: what a node IS. Constants for the same reason the statuses are: the renderer BRANCHES on this across a
#: tier boundary, and a typo there would draw every artifact as a concept without anything failing.
ARTIFACT, CONCEPT = "artifact", "concept"


@dataclass(frozen=True)
class Node:
    """One thing in the picture. `kind` is what it is; `status` is how it is known — a rung (S, X, C, H, D) or
    one of FOCUS / PROPOSED / VOCABULARY."""
    id: str
    label: str
    kind: str                       # ARTIFACT | CONCEPT
    status: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.label:
            raise ValueError(f"a node carries an id and a label: {self!r}")


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
