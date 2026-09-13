"""The derived rung D: two rules over the trusted rungs, rebuilt idempotently, every triple with a PROV record
that names the rule and what it was derived through. Nothing derives from a suggestion."""
from rdflib import Dataset, Literal, URIRef

from lab.core.semantic.fabric import derive as D
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric.rungs import CONFIRMED, CONSTRUCTED, DERIVED, EXTRACTED, PROV_GRAPH, SUGGESTED, graph_iri

A, B, DR, M, K = (URIRef(f"urn:fabric:artifact:{x}") for x in ("A", "B", "DR", "M", "K"))
CTX = URIRef("urn:fabric:context:meeting:AAMk1")


def _ds():
    ds = Dataset(default_union=True)
    G.assert_triple(ds, B, G.FAB.deliveredUnder, CTX, rung=CONSTRUCTED, method="run-context")
    G.assert_triple(ds, A, G.FAB.references, B, rung=EXTRACTED, method="link-extraction")
    G.assert_triple(ds, M, G.FAB.deliveredUnder, CTX, rung=CONSTRUCTED, method="run-context")
    G.assert_triple(ds, DR, G.FAB.synthesisedFrom, M, rung=CONSTRUCTED, method="drafted-from")
    return ds


def test_the_two_rules_derive_a_related_context_and_an_inherited_delivery_context():
    ds = _ds()
    out = D.derive(ds)
    d = ds.graph(graph_iri(DERIVED))
    assert (A, G.FAB.relatedTo, CTX) in d and (DR, G.FAB.deliveredUnder, CTX) in d
    assert out == {"derived": 2, "rules": {"references-context": 1, "synthesised-context": 1}}
    prov = ds.graph(PROV_GRAPH)
    methods = {str(m) for m in prov.objects(None, G.FAB.method)}
    assert {"rule:references-context", "rule:synthesised-context"} <= methods
    aid = next(a for a in prov.subjects(G.FAB.method, Literal("rule:references-context")))
    assert prov.value(aid, G.PROV.wasDerivedFrom) == B and str(prov.value(aid, G.FAB.rung)) == "D"


def test_derivation_is_idempotent_and_rebuilt_from_scratch():
    ds = _ds()
    D.derive(ds); first = set(ds.graph(graph_iri(DERIVED)))
    D.derive(ds)
    assert set(ds.graph(graph_iri(DERIVED))) == first
    prov = ds.graph(PROV_GRAPH)
    assert len(list(prov.subjects(G.FAB.rung, Literal("D")))) == 2            # no duplicate records
    G.retract(ds, A, G.FAB.references, B, actor="x", reason="wrong")
    assert D.derive(ds)["derived"] == 1 and (A, G.FAB.relatedTo, CTX) not in ds.graph(graph_iri(DERIVED))


def test_nothing_derives_from_a_suggestion_or_duplicates_an_asserted_edge():
    ds = Dataset(default_union=True)
    G.assert_triple(ds, B, G.FAB.deliveredUnder, CTX, rung=SUGGESTED, method="nn", confidence=0.9)
    G.assert_triple(ds, A, G.FAB.references, B, rung=EXTRACTED, method="link")
    assert D.derive(ds)["derived"] == 0
    ds = _ds()
    G.assert_triple(ds, DR, G.FAB.deliveredUnder, CTX, rung=CONFIRMED, method="review", actor="p")   # already has one
    out = D.derive(ds)
    assert out["rules"]["synthesised-context"] == 0 and (DR, G.FAB.deliveredUnder, CTX) not in ds.graph(graph_iri(DERIVED))


def test_impact_reaches_a_record_only_through_a_derived_edge():
    ds = _ds()
    D.derive(ds)
    hits = {str(n) for n, _, _ in G.impact(ds, CTX)}
    assert str(DR) in hits                                 # the decision record, delivered under CTX only at D
    assert "D" in {r for _, _, r in G.impact(ds, CTX)}
