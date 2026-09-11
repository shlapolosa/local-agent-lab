"""Pure functions over an rdflib Dataset partitioned by provenance rung: assert, promote, retract,
traverse, impact, and (de)serialise one rung. No store, no HTTP, no Redis — the substrate wraps these.

Every assertion is a triple in the rung's named graph PLUS a PROV record (a `fab:Assertion`) in the
prov graph carrying rung, method, actor, confidence and time. Promotion moves the triple between rung
graphs and INVALIDATES the old record rather than deleting it (PROV-O `wasInvalidatedBy`), so the
audit chain (CQ-22) stays whole. Derived triples live in graph D and are recomputed, never captured."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from rdflib import RDF, XSD, BNode, Dataset, Graph, Literal, URIRef
from rdflib.namespace import Namespace

from lab.core import ids
from lab.core.semantic.fabric.rungs import (CONFIRMED, DERIVED, GRAPH_RUNGS, IMPACT_READS, PROV_GRAPH,
                                             SUGGESTED, graph_iri, weakest)

FAB = Namespace("urn:fabric:ont#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
ASSERTION = "urn:fabric:assertion:"


def _now() -> Literal:
    return Literal(datetime.now(timezone.utc).isoformat(timespec="seconds"), datatype=XSD.dateTime)


@dataclass(frozen=True)
class Assertion:
    id: URIRef
    subject: URIRef
    predicate: URIRef
    object: URIRef | Literal
    rung: str
    method: str
    actor: str = ""
    confidence: float | None = None


def assert_triple(ds: Dataset, s: URIRef, p: URIRef, o: URIRef | Literal, *, rung: str, method: str,
                  actor: str = "", confidence: float | None = None) -> Assertion:
    """Enter one assertion at `rung`. Refuses O (never a triple) and D (derived is computed, not asserted)."""
    if rung not in GRAPH_RUNGS or rung == DERIVED:
        raise ValueError(f"an assertion enters at S, X, C or H — not {rung!r}")
    if rung == SUGGESTED and confidence is None:
        raise ValueError("a suggestion carries a confidence")
    ds.graph(graph_iri(rung)).add((s, p, o))
    aid = URIRef(ASSERTION + ids.ulid())
    prov = ds.graph(PROV_GRAPH)
    stmt = BNode()
    prov.add((stmt, RDF.type, RDF.Statement)); prov.add((stmt, RDF.subject, s))
    prov.add((stmt, RDF.predicate, p)); prov.add((stmt, RDF.object, o))
    prov.add((aid, RDF.type, FAB.Assertion)); prov.add((aid, FAB.asserts, stmt))
    prov.add((aid, FAB.rung, Literal(rung))); prov.add((aid, FAB.method, Literal(method)))
    prov.add((aid, PROV.generatedAtTime, _now()))
    if actor:
        prov.add((aid, PROV.wasAttributedTo, Literal(actor)))
    if confidence is not None:
        prov.add((aid, FAB.confidence, Literal(float(confidence), datatype=XSD.double)))
    return Assertion(aid, s, p, o, rung, method, actor, confidence)


def find(ds: Dataset, s: URIRef | None = None, p: URIRef | None = None, o=None,
         rungs: tuple[str, ...] = GRAPH_RUNGS) -> list[tuple[str, tuple]]:
    """[(rung, (s, p, o))] over the chosen rung graphs."""
    out = []
    for r in rungs:
        for t in ds.graph(graph_iri(r)).triples((s, p, o)):
            out.append((r, t))
    return out


def _live_assertion(ds: Dataset, s, p, o, rung: str) -> URIRef | None:
    prov = ds.graph(PROV_GRAPH)
    for aid in prov.subjects(FAB.rung, Literal(rung)):
        if (aid, PROV.wasInvalidatedBy, None) in prov:
            continue
        stmt = prov.value(aid, FAB.asserts)
        if stmt is not None and (prov.value(stmt, RDF.subject), prov.value(stmt, RDF.predicate),
                                 prov.value(stmt, RDF.object)) == (s, p, o):
            return aid
    return None


def promote(ds: Dataset, s: URIRef, p: URIRef, o, *, to: str = CONFIRMED, actor: str, method: str) -> Assertion:
    """Move an assertion up the ladder — a CURATOR gate, so an actor is required. The old record is
    invalidated, never deleted; a new one is written at the target rung."""
    if not actor:
        raise ValueError("a promotion is a person's decision: actor is required")
    current = next((r for r, _ in find(ds, s, p, o)), None)
    if current is None:
        raise LookupError("nothing to promote: that triple is not asserted at any rung")
    if current == to:
        raise ValueError(f"already at rung {to}")
    ds.graph(graph_iri(current)).remove((s, p, o))
    old = _live_assertion(ds, s, p, o, current)
    new = assert_triple(ds, s, p, o, rung=to, method=method, actor=actor)
    if old is not None:
        prov = ds.graph(PROV_GRAPH)
        prov.add((old, PROV.wasInvalidatedBy, new.id)); prov.add((old, PROV.invalidatedAtTime, _now()))
    return new


def retract(ds: Dataset, s: URIRef, p: URIRef, o, *, actor: str, reason: str) -> bool:
    """Supersede an assertion (PROV invalidation); the triple leaves its rung graph. Returns False if absent."""
    if not actor:
        raise ValueError("a retraction is a person's or a rule's decision: actor is required")
    hit = find(ds, s, p, o)
    if not hit:
        return False
    for r, _ in hit:
        ds.graph(graph_iri(r)).remove((s, p, o))
        old = _live_assertion(ds, s, p, o, r)
        if old is not None:
            prov = ds.graph(PROV_GRAPH)
            prov.add((old, PROV.wasInvalidatedBy, Literal(f"{actor}: {reason}")))
            prov.add((old, PROV.invalidatedAtTime, _now()))
    return True


def traverse(ds: Dataset, start: URIRef, predicates: tuple[URIRef, ...], *, rungs: tuple[str, ...],
             depth: int = 3, inbound: bool = True) -> list[tuple[URIRef, int, str]]:
    """Breadth-first over the chosen rung graphs: [(node, distance, weakest rung on the path)].
    `inbound=True` follows edges INTO `start` (what references / is delivered with it) — impact's direction."""
    seen: dict[URIRef, tuple[int, str]] = {}
    frontier: list[tuple[URIRef, int, str]] = [(start, 0, CONFIRMED)]
    while frontier:
        node, dist, grade = frontier.pop(0)
        if dist >= depth:
            continue
        for r in rungs:
            g = ds.graph(graph_iri(r))
            for pred in predicates:
                neighbours = g.subjects(pred, node) if inbound else g.objects(node, pred)
                for n in neighbours:
                    if n == start or n in seen:
                        continue
                    seen[n] = (dist + 1, weakest(grade, r))
                    frontier.append((n, dist + 1, weakest(grade, r)))
    return [(n, d, gr) for n, (d, gr) in seen.items()]


def impact(ds: Dataset, changed: URIRef, *, depth: int = 3) -> list[tuple[URIRef, int, str]]:
    """What a change to `changed` may have invalidated: everything reachable INBOUND over the delivery
    and structural axes, on trusted rungs only (IMPACT_READS — never S)."""
    return traverse(ds, changed, (FAB.references, FAB.deliveredUnder), rungs=IMPACT_READS, depth=depth)


def graph_nquads(ds: Dataset, iri: URIRef) -> str:
    """One named graph as N-Quads — the unit of persistence (a rung, the prov graph, the candidates)."""
    g = Graph(identifier=iri)
    for t in ds.graph(iri):
        g.add(t)
    d = Dataset(); d.add_graph(g)
    return d.serialize(format="nquads")


def load_nquads(ds: Dataset, text: str) -> int:
    """Load persisted rung (or prov) graphs back into `ds`. Returns the number of quads loaded."""
    tmp = Dataset(); tmp.parse(data=text, format="nquads")
    n = 0
    for s, p, o, g in tmp.quads((None, None, None, None)):
        ds.graph(URIRef(str(g))).add((s, p, o)); n += 1
    return n


__all__ = ["Assertion", "assert_triple", "find", "promote", "retract", "traverse", "impact",
           "load_nquads", "graph_nquads", "FAB", "PROV", "DCT", "SKOS"]
