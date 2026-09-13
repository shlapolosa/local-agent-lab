"""The derived rung D — inferred edges, recomputed, never asserted (BR-7: an answer can say WHY it believes).

Two rules, each a SELECT that binds the derived subject, object and the record it was derived THROUGH, read over
the trusted rungs only (C, X, H — never S: a wrong suggestion must not derive a confident edge). Graph D is
rebuilt from scratch on every call, so it is idempotent and never stale by more than one derivation; every
derived triple carries a PROV record at rung D with method `rule:<name>` and `prov:wasDerivedFrom` the record
it came through. Pure over the Dataset; the service persists."""
from __future__ import annotations

from rdflib import RDF, BNode, Dataset, Graph, Literal, URIRef

from lab.core import ids
from lab.core.semantic.fabric.graph import ASSERTION, FAB, PROV, _now
from lab.core.semantic.fabric.rungs import CONFIRMED, CONSTRUCTED, DERIVED, EXTRACTED, PROV_GRAPH, graph_iri

__all__ = ["RULES", "derive", "clear"]

#: the rungs a derivation may read: what was looked up, found in content, or confirmed — never suggested
READS: tuple[str, ...] = (CONSTRUCTED, EXTRACTED, CONFIRMED)

PREFIX = "PREFIX fab: <urn:fabric:ont#>\n"

#: (name, predicate derived, SELECT binding ?s ?o ?via)
RULES: tuple[tuple[str, URIRef, str], ...] = (
    # A references B, and B was delivered under context K ⇒ A is RELATED to K (through B).
    ("references-context", FAB.relatedTo, PREFIX + """
        SELECT DISTINCT ?s ?o ?via WHERE { ?s fab:references ?via . ?via fab:deliveredUnder ?o . }"""),
    # A decision record synthesised from minutes inherits the minutes' delivery context — unless it already has one.
    ("synthesised-context", FAB.deliveredUnder, PREFIX + """
        SELECT DISTINCT ?s ?o ?via WHERE { ?s fab:synthesisedFrom ?via . ?via fab:deliveredUnder ?o .
                                           FILTER NOT EXISTS { ?s fab:deliveredUnder ?any } }"""),
)


def _trusted(ds: Dataset) -> Graph:
    g = Graph()
    for r in READS:
        g += ds.graph(graph_iri(r))
    return g


def clear(ds: Dataset) -> int:
    """Drop graph D and every PROV record at rung D. Returns how many triples left."""
    d = ds.graph(graph_iri(DERIVED))
    n = len(d)
    d.remove((None, None, None))
    prov = ds.graph(PROV_GRAPH)
    for aid in list(prov.subjects(FAB.rung, Literal(DERIVED))):
        stmt = prov.value(aid, FAB.asserts)
        prov.remove((aid, None, None))
        if stmt is not None:
            prov.remove((stmt, None, None))
    return n


def derive(ds: Dataset) -> dict:
    """Rebuild graph D from the trusted rungs. Returns counts only: {"derived": n, "rules": {name: n}}."""
    clear(ds)
    source, d, prov = _trusted(ds), ds.graph(graph_iri(DERIVED)), ds.graph(PROV_GRAPH)
    counts: dict[str, int] = {}
    for name, predicate, query in RULES:
        n = 0
        for s, o, via in source.query(query):
            if (s, predicate, o) in source or (s, predicate, o) in d:
                continue                                  # already asserted, or derived by an earlier rule
            d.add((s, predicate, o))
            aid = URIRef(ASSERTION + ids.ulid())
            stmt = BNode()
            prov.add((stmt, RDF.type, RDF.Statement)); prov.add((stmt, RDF.subject, s))
            prov.add((stmt, RDF.predicate, predicate)); prov.add((stmt, RDF.object, o))
            prov.add((aid, RDF.type, FAB.Assertion)); prov.add((aid, FAB.asserts, stmt))
            prov.add((aid, FAB.rung, Literal(DERIVED))); prov.add((aid, FAB.method, Literal(f"rule:{name}")))
            prov.add((aid, PROV.generatedAtTime, _now())); prov.add((aid, PROV.wasDerivedFrom, via))
            n += 1
        counts[name] = n
    return {"derived": sum(counts.values()), "rules": counts}
