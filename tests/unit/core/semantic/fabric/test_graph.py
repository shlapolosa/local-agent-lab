"""Assertions enter at a rung, promote through a gate, retract by supersession, and impact never reads S."""
import pytest
from rdflib import Literal, URIRef

from fixtures.fabric import A1, A2, A3, FAB, MEETING, USECASE, dataset
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric.rungs import (CONFIRMED, CONSTRUCTED, DERIVED, OBSERVED, PROV_GRAPH, SUGGESTED,
                                             graph_iri, weakest)


def test_entry_rules():
    ds = dataset()
    with pytest.raises(ValueError):
        G.assert_triple(ds, A3, FAB.references, A1, rung=OBSERVED, method="x")
    with pytest.raises(ValueError):
        G.assert_triple(ds, A3, FAB.references, A1, rung=DERIVED, method="x")
    with pytest.raises(ValueError):
        G.assert_triple(ds, A3, FAB.references, A1, rung=SUGGESTED, method="similarity")   # no confidence
    a = G.assert_triple(ds, A3, FAB.references, A1, rung=SUGGESTED, method="similarity", confidence=0.4)
    assert a.rung == SUGGESTED and (A3, FAB.references, A1) in ds.graph(graph_iri(SUGGESTED))


def test_promotion_moves_the_triple_and_invalidates_the_old_record():
    ds = dataset()
    before = len(list(ds.graph(G.PROV_GRAPH).subjects(G.FAB.rung, Literal(SUGGESTED))))
    new = G.promote(ds, A3, FAB.deliveredUnder, USECASE, actor="steward@x.org", method="one-tap card")
    assert new.rung == CONFIRMED
    assert (A3, FAB.deliveredUnder, USECASE) in ds.graph(graph_iri(CONFIRMED))
    assert (A3, FAB.deliveredUnder, USECASE) not in ds.graph(graph_iri(SUGGESTED))
    prov = ds.graph(G.PROV_GRAPH)
    invalidated = [a for a in prov.subjects(G.PROV.wasInvalidatedBy, new.id)]
    assert len(invalidated) == 1, "the suggested record is superseded, never deleted"
    assert len(list(prov.subjects(G.FAB.rung, Literal(SUGGESTED)))) == before, "history kept"


def test_promotion_needs_an_actor_and_something_to_promote():
    ds = dataset()
    with pytest.raises(ValueError):
        G.promote(ds, A3, FAB.deliveredUnder, USECASE, actor="", method="card")
    with pytest.raises(LookupError):
        G.promote(ds, A3, FAB.references, MEETING, actor="a@x", method="card")
    with pytest.raises(ValueError):
        G.promote(ds, A2, FAB.deliveredUnder, USECASE, actor="a@x", method="card")   # already H


def test_retract_is_supersession():
    ds = dataset()
    assert G.retract(ds, A1, FAB.deliveredUnder, MEETING, actor="rule:link-removed", reason="link deleted at source")
    assert not G.find(ds, A1, FAB.deliveredUnder, MEETING)
    assert not G.retract(ds, A1, FAB.deliveredUnder, MEETING, actor="x", reason="again")
    prov = ds.graph(G.PROV_GRAPH)
    assert any("link deleted" in str(o) for o in prov.objects(None, G.PROV.wasInvalidatedBy))


def test_impact_reads_trusted_rungs_only():
    ds = dataset()
    hit = {n: (d, g) for n, d, g in G.impact(ds, A1)}
    assert A2 in hit, "A2 references A1 (extracted) — impact must find it"
    assert A3 not in hit, "A3 is linked to nothing trusted"
    # a suggested reference must not make A3 appear
    G.assert_triple(ds, A3, FAB.references, A1, rung=SUGGESTED, method="similarity", confidence=0.9)
    assert A3 not in {n for n, _, _ in G.impact(ds, A1)}
    # and a confirmed one must
    G.promote(ds, A3, FAB.references, A1, actor="steward@x.org", method="card")
    assert A3 in {n for n, _, _ in G.impact(ds, A1)}


def test_weakest_grade_travels_along_the_path():
    ds = dataset()
    hit = {n: g for n, _, g in G.impact(ds, USECASE, depth=3)}   # who is delivered under the use case
    assert hit[A2] == CONFIRMED
    assert weakest(CONFIRMED, "X") == "X" and weakest("C", "H") == "C"


def test_nquads_round_trip_per_rung():
    ds = dataset()
    text = G.graph_nquads(ds, graph_iri(CONSTRUCTED))
    fresh = G.load_nquads.__globals__["Dataset"](default_union=True)
    n = G.load_nquads(fresh, text)
    assert n == len(ds.graph(graph_iri(CONSTRUCTED)))
    assert (A1, FAB.deliveredUnder, MEETING) in fresh.graph(graph_iri(CONSTRUCTED))
    assert G.load_nquads(fresh, G.graph_nquads(ds, PROV_GRAPH)) > 0
