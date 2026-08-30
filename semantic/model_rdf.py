"""Instance models -> RDF, with ArchiMate derivation rules.

A model spec (the JSON the adoit-mcp tools accept) becomes triples in its own named graph:
  model:eid  a  archimate:Type ; rdfs:label name ; rdfs:comment doc .
  model:src  archimate:<relation>  model:tgt .           (asserted)
  model:src  archimate:derived<Relation>  model:tgt .    (derived, see below)
plus one meta:Relationship node per relationship so queries can filter by type/id.

Derivation (ArchiMate 3.1 §5.7, the potential-derivation rules that matter for
traceability questions):
  * a chain of structural relations (composition, aggregation, assignment, realization)
    from A to B derives the WEAKEST relation in the chain  (e.g. component realizes service
    realizes capability realizes goal  ->  component derivedRealization goal)
  * a structural chain from A to B followed by a dependency (serving, access, influence)
    from B to C derives that dependency from A to C  (node composes system software that
    serves a component  ->  node derivedServing component)
"""
from rdflib import RDF, RDFS, BNode, Literal, URIRef

from .ontology import META

STRUCTURAL = ["Realization", "Assignment", "Aggregation", "Composition"]   # weakest -> strongest
DEPENDENCY = ["Serving", "Access", "Influence"]
MAX_CHAIN = 6


def model_iri(model_id: str) -> str:
    return f"urn:lab:semantic:model:{model_id}"


def spec_to_triples(spec: dict, vocab, model_id: str):
    base = model_iri(model_id) + "#"
    E = lambda eid: URIRef(base + eid)
    T = []
    T.append((URIRef(model_iri(model_id)), RDFS.label, Literal(spec.get("name", model_id))))
    for e in spec["elements"]:
        u = E(e["id"])
        T += [(u, RDF.type, vocab.cls(e["type"])), (RDFS.label and (u, RDFS.label, Literal(e["name"])))]
        T.append((u, META.id, Literal(e["id"])))
        if e.get("doc"):
            T.append((u, RDFS.comment, Literal(e["doc"])))
    for i, r in enumerate(spec.get("relations", [])):
        s, t = E(r["src"]), E(r["tgt"])
        T.append((s, vocab.rel(r["type"]), t))
        b = BNode()
        T += [(b, RDF.type, META.Relationship), (b, META.relSource, s), (b, META.relTarget, t),
              (b, META.relType, vocab.rel(r["type"])), (b, META.id, Literal(r.get("id") or f"r{i+1}"))]
        if r.get("accessType"):
            T.append((b, META.accessType, Literal(r["accessType"])))
    T += derive(spec, vocab, E)
    return T


def derive(spec, vocab, E):
    """Compute derived structural + dependency relations (bounded chain length)."""
    out_edges = {}
    for r in spec.get("relations", []):
        out_edges.setdefault(r["src"], []).append((r["type"], r["tgt"]))
    derived = set()

    def walk(start, node, weakest, depth):
        if depth >= MAX_CHAIN:
            return
        for rtype, nxt in out_edges.get(node, []):
            if rtype in STRUCTURAL:
                w = min(weakest, STRUCTURAL.index(rtype)) if weakest is not None else STRUCTURAL.index(rtype)
                if depth >= 1:                                # chains of length >= 2 produce derivations
                    derived.add((start, STRUCTURAL[w], nxt))
                walk(start, nxt, w, depth + 1)
            elif rtype in DEPENDENCY and depth >= 1:          # structural chain then dependency
                derived.add((start, rtype, nxt))

    for start in out_edges:
        walk(start, start, None, 0)
    asserted = {(r["src"], r["type"], r["tgt"]) for r in spec.get("relations", [])}
    T = []
    for s, rtype, t in derived - asserted:
        if s == t:
            continue
        T.append((E(s), vocab.ns["derived" + rtype], E(t)))
    return T
