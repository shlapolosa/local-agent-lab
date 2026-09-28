"""The derived rung D — inferred edges, recomputed, never asserted (BR-7: an answer can say WHY it believes).

Two rules, each a SELECT that binds the derived subject, object and the record it was derived THROUGH, read over
the trusted rungs only (C, X, H — never S: a wrong suggestion must not derive a confident edge). Graph D is
rebuilt from scratch on every call, so it is idempotent and never stale by more than one derivation; every
derived triple carries a PROV record at rung D with method `rule:<name>` and `prov:wasDerivedFrom` the record
it came through. Rules read the trusted rungs, never each other's output: they are non-transitive and
order-independent by construction — a rule that needs another rule's result needs a fixpoint loop, added then.
Pure over the Dataset; the service persists."""
from __future__ import annotations

from typing import Iterable

from rdflib import RDF, BNode, Dataset, Graph, Literal, URIRef

from lab.core import ids
from lab.core.semantic.fabric.graph import ASSERTION, FAB, PROV, now
from lab.core.semantic.fabric.rungs import CONFIRMED, CONSTRUCTED, DERIVED, EXTRACTED, PROV_GRAPH, graph_iri

__all__ = ["RULES", "derive", "clear"]

#: the rungs a derivation may read: what was looked up, found in content, or confirmed — never suggested
READS: tuple[str, ...] = (CONSTRUCTED, EXTRACTED, CONFIRMED)

PREFIX = ("PREFIX fab: <urn:fabric:ont#>\n"
          "PREFIX dct: <http://purl.org/dc/terms/>\n"
          "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n")

#: (name, predicate derived, SELECT binding ?s ?o ?via)
RULES: tuple[tuple[str, URIRef, str], ...] = (
    # A references B, and B was delivered under context K ⇒ A is RELATED to K (through B).
    ("references-context", FAB.relatedTo, PREFIX + """
        SELECT DISTINCT ?s ?o ?via WHERE { ?s fab:references ?via . ?via fab:deliveredUnder ?o . }"""),
    # A decision record synthesised from minutes inherits the minutes' delivery context — unless it already has one.
    ("synthesised-context", FAB.deliveredUnder, PREFIX + """
        SELECT DISTINCT ?s ?o ?via WHERE { ?s fab:synthesisedFrom ?via . ?via fab:deliveredUnder ?o .
                                           FILTER NOT EXISTS { ?s fab:deliveredUnder ?any } }"""),
    # A is about concept X, X is related to concept Y by one of the vocabulary's OWN predicates, and B is about
    # Y ⇒ A is related to B, through X. The path is followed in EITHER direction: the ontology states a
    # direction because `raisedOn` has one, but relatedness for a reader does not — a directional derivation
    # would make the same connection visible from one document and invisible from the other. This is what owning an ontology rather than a taxonomy buys: a document
    # arrives connected to what already exists, because the concepts it is about are connected. `?p a
    # rdf:Property` is the filter that matters — the vocabulary declares its own relationship types, so a
    # hierarchy (skos:broader) or a housekeeping triple cannot masquerade as a statement about the domain.
    ("concept-path", FAB.relatedTo, PREFIX + """
        SELECT DISTINCT ?s ?o ?via WHERE { ?s dct:subject ?via .
                                           { ?via ?p ?y } UNION { ?y ?p ?via }
                                           ?p a rdf:Property . ?o dct:subject ?y . FILTER (?s != ?o) }"""),
)


def _trusted(ds: Dataset, vocabulary: Iterable[URIRef] = ()) -> Graph:
    """The rungs a derivation may read, plus any VOCABULARY graphs given as context. The vocabulary is reference
    data, not an assertion about an artifact, so it is never written to and never carries a rung — it is read the
    way a rule reads a definition."""
    g = Graph()
    for r in READS:
        g += ds.graph(graph_iri(r))
    for iri in vocabulary:
        g += ds.graph(iri)
    return g


def clear(ds: Dataset) -> int:
    """Drop graph D and the PROV records of the derived triples still there. A D record a person PROMOTED (it
    carries prov:wasInvalidatedBy the H record) is kept: the audit chain must still say the confirmed edge
    began as an inference. Returns how many triples were removed."""
    d = ds.graph(graph_iri(DERIVED))
    n = len(d)
    d.remove((None, None, None))
    prov = ds.graph(PROV_GRAPH)
    for aid in list(prov.subjects(FAB.rung, Literal(DERIVED))):
        if prov.value(aid, PROV.wasInvalidatedBy) is not None:
            continue
        stmt = prov.value(aid, FAB.asserts)
        prov.remove((aid, None, None))
        if stmt is not None:
            prov.remove((stmt, None, None))
    return n


def derive(ds: Dataset, vocabulary: Iterable[URIRef] = ()) -> dict:
    """Rebuild graph D from the trusted rungs, reading `vocabulary` graphs as context. Returns counts only:
    {"derived": n, "rules": {name: n}}. Given no vocabulary, the concept rule simply finds nothing — the
    derivation is never wrong for want of context, only quieter."""
    clear(ds)
    vocabulary = tuple(vocabulary)
    source, d, prov = _trusted(ds, vocabulary), ds.graph(graph_iri(DERIVED)), ds.graph(PROV_GRAPH)
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
            prov.add((aid, PROV.generatedAtTime, now())); prov.add((aid, PROV.wasDerivedFrom, via))
            n += 1
        counts[name] = n
    return {"derived": sum(counts.values()), "rules": counts}
