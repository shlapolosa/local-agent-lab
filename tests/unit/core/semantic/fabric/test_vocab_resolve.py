"""`vocab_resolve` — the three tiers of the classifier's subject match as ONE decision.

The intake workload used to run them itself: link by label, ask the semantic tier what each miss MEANS,
park what is left for a steward. That made the workload choose a strategy, which the TO-BE architecture
puts below the seam (24 Oct 2026): a tool returns the DECISION, not the inputs to one. These tests pin the
semantics the workload had, so moving the loop changes nothing a record sees.

Pure: a Dataset and a Catalog in memory. No store, no HTTP.
"""
import pytest
from rdflib import Dataset, URIRef

from fixtures.embed import HashEmbedder
from fixtures.skos import scheme
from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.service import FabricService

DOC = {"source": "collab", "handle": "collab://site/drive/doc7", "version": "2"}
C1 = "urn:lab:semantic:ref:syn#c1"


@pytest.fixture
def fab():
    ds = Dataset(default_union=True)
    sc = scheme()
    ds.graph(URIRef("urn:lab:semantic:vocab:syn-v1")).__iadd__(sc.graph())
    return FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                         embedder=HashEmbedder(dim=8))


def _candidate(fab, label):
    return next(c for c in fab.vocab_candidates() if c["label"] == label)


def test_a_label_match_links_and_a_miss_becomes_ONE_candidate_proposed_for_this_artifact(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    out = fab.vocab_resolve(a, ["Care Delivery", "dispense confirmation callback"], scheme="syn-v1",
                            actor="classifier-agent", definition="proposed while classifying doc7")
    assert [l["term"] for l in out["linked"]] == ["Care Delivery"]
    assert out["missed"] == ["dispense confirmation callback"]
    assert [p["label"] for p in out["proposed"]] == ["dispense confirmation callback"]
    row = _candidate(fab, "dispense confirmation callback")
    assert row["proposed_for"] == [a]


def test_a_miss_the_semantic_tier_recognises_is_proposed_as_a_WORD_FOR_that_concept(fab, monkeypatch):
    a = fab.catalog_upsert(DOC)["iri"]
    asked = []
    monkeypatch.setattr(fab, "concept_match",
                        lambda term, scheme="": asked.append((term, scheme)) or {"concept": C1})
    fab.vocab_resolve(a, ["clinical review workflow"], scheme="syn-v1", actor="classifier-agent")
    assert asked == [("clinical review workflow", "syn-v1")]
    assert _candidate(fab, "clinical review workflow")["alias_of"] == C1


def test_a_semantic_tier_that_FAILS_still_parks_the_term_it_only_costs_the_suggestion(fab, monkeypatch):
    """An unavailable tier means the steward is asked the expensive question, not that the word is lost."""
    a = fab.catalog_upsert(DOC)["iri"]

    def broken(term, scheme=""):
        raise RuntimeError("embedder down")
    monkeypatch.setattr(fab, "concept_match", broken)
    out = fab.vocab_resolve(a, ["clinical review workflow"], scheme="syn-v1", actor="classifier-agent")
    assert [p["label"] for p in out["proposed"]] == ["clinical review workflow"]
    assert not _candidate(fab, "clinical review workflow").get("alias_of")


def test_the_link_answer_survives_whole_so_retractions_and_conflicts_still_reach_the_run(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    fab.vocab_resolve(a, ["Care Delivery", "Triage"], scheme="syn-v1", actor="classifier-agent")
    out = fab.vocab_resolve(a, ["Triage"], scheme="syn-v1", actor="classifier-agent")
    assert "retracted" in out and "conflicts" in out
    assert out["proposed"] == []


def test_a_proposal_names_who_proposed_it(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    with pytest.raises(ValueError):
        fab.vocab_resolve(a, ["something new"], scheme="syn-v1", actor="")
