"""What one artifact is about, and what that connects it to — built from the CURRENT graph, every time.

This is the fabric's half of the picture: it knows what a record's links mean and which rung each was made at,
and it hands a renderer a `TopologyView` that says so. Nothing here draws anything, and nothing that draws
knows what a rung is.

Three rings, because that is the question a person actually asks:
  the record itself · the concepts it is ABOUT · what those concepts connect it to
The third ring is where owning an ontology shows: a neighbouring concept, and any other record that is about it,
are on the picture because the vocabulary says the two concepts are related — not because anybody linked them.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from lab.core.semantic.fabric.ontology import SUBJECT, short
from lab.core.viz import ARTIFACT, CONCEPT, FOCUS, PROPOSED, VOCABULARY, Edge, Node, TopologyView

__all__ = ["view_of"]

#: the link that says what an artifact is ABOUT — the only one walked for vocabulary neighbours. Derived from the
#: ontology rather than spelled again, so it cannot drift from the predicate the rest of the fabric asserts.
_ABOUT = short(SUBJECT)


def _short(iri: str) -> str:
    """The last segment of an IRI, for a LABEL. Deliberately not `ontology.short`: this one also splits on ":", so
    `urn:fabric:artifact:A` reads as "A" rather than as the whole urn. A label is for a person, not for a lookup."""
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def view_of(record: Mapping[str, Any], *, schemes: Iterable[Any] = (), related: Iterable[Mapping[str, Any]] = (),
            proposed: Iterable[str] = (), as_of: str = "", ontology_ring: bool = True) -> TopologyView:
    """A view of one catalogue record. `schemes` are the vocabularies it was classified against (anything with
    `relations_of`/`concepts`/`uri`) — PLURAL, because the fabric may own more than one and a derivation that
    reads them all beside a picture that reads one would draw edges it cannot explain; `related` are other
    records the fabric derived a relation to; `proposed` are terms this record used that the vocabulary has no
    concept for — drawn, because a gap a person can see is a gap a steward can close. `ontology_ring` off draws
    the record and its subjects alone (it was once an int named `depth`, which promised rings it never walked)."""
    iri = str(record.get("iri") or "")
    title = str(record.get("title") or _short(iri))
    nodes: list[Node] = [Node(id=iri, label=title, kind=ARTIFACT, status=FOCUS,
                              note=str(record.get("state") or ""))]
    edges: list[Edge] = []
    seen = {iri}

    concept_ids: dict[str, str] = {}          # node id -> the scheme's concept id, for the second ring
    for link in record.get("links") or []:
        if link.get("predicate") != _ABOUT:
            continue
        cid = str(link.get("object") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        label = str(link.get("label") or _short(cid))
        nodes.append(Node(id=cid, label=label, kind=CONCEPT, status=str(link.get("rung") or VOCABULARY)))
        edges.append(Edge(source=iri, target=cid, label="about", status=str(link.get("rung") or VOCABULARY)))
        concept_ids[cid] = _short(cid)

    # Every scheme is asked about every concept: one that does not hold it answers with nothing (`relations_of`
    # returns []), so asking costs nothing and NOT asking loses a whole vocabulary's half of the picture.
    for scheme in (schemes if ontology_ring else ()):
        for cid, term in list(concept_ids.items()):
            for predicate, other, direction in scheme.relations_of(term):
                target = str(scheme.uri(other))
                if target not in seen:
                    concept = scheme.concepts.get(other) or {}
                    seen.add(target)
                    nodes.append(Node(id=target, label=str(concept.get("label") or other), kind=CONCEPT,
                                      status=VOCABULARY, note=str(concept.get("module") or "")))
                a, b = (cid, target) if direction == "out" else (target, cid)
                edges.append(Edge(source=a, target=b, label=predicate, status=VOCABULARY))

    for other in related:
        oid = str(other.get("iri") or "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        nodes.append(Node(id=oid, label=str(other.get("title") or _short(oid)), kind=ARTIFACT,
                          status=str(other.get("rung") or VOCABULARY), note=str(other.get("state") or "")))
        edges.append(Edge(source=iri, target=oid, label=str(other.get("predicate") or "related"),
                          status=str(other.get("rung") or VOCABULARY)))

    for term in proposed:
        node_id = f"proposed:{term}"
        if not term or node_id in seen:
            continue
        seen.add(node_id)
        nodes.append(Node(id=node_id, label=str(term), kind=CONCEPT, status=PROPOSED,
                          note="no concept for this yet"))
        edges.append(Edge(source=iri, target=node_id, label="about", status=PROPOSED))

    return TopologyView(title=title, focus=iri, nodes=tuple(nodes), edges=tuple(edges), as_of=as_of,
                        subtitle=str(record.get("document_type") and _short(record["document_type"]) or ""))
