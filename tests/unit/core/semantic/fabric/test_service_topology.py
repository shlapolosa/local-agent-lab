"""The fabric's own view of one record: built from the CURRENT graph, drawn by whoever can."""
import pytest
from rdflib import Dataset, URIRef

from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.rungs import EXTRACTED
from lab.core.semantic.fabric.service import FabricService
from lab.core.semantic.fabric.vocabulary import build as vocab
from lab.core.viz import PROPOSED, VOCABULARY, TopologyView

SCHEME = vocab(name="cafe", title="CAFÉ",
               concepts=[{"id": "AIAgent", "name": "AI agent"}, {"id": "UseCase", "name": "Use case"}],
               relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])


@pytest.fixture
def fab():
    ds = Dataset(default_union=True)
    ds.graph(URIRef(f"urn:lab:semantic:vocab:{SCHEME.name}")).__iadd__(SCHEME.graph())
    return FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {SCHEME.name: SCHEME})


def _record(svc, title, term="AI agent"):
    iri = svc.catalog_upsert({"source": "collab", "handle": f"collab://item/{title}"}, title=title)["iri"]
    svc.vocab_link(iri, [term], schemes=["cafe"])
    return iri


def test_the_view_is_the_record_what_it_is_about_and_what_the_vocabulary_adds(fab):
    iri = _record(fab, "Agent design note")
    v = fab.topology(iri, as_of="2026-09-29T07:00:00Z")
    assert isinstance(v, TopologyView) and v.focus == iri and v.title == "Agent design note"
    assert v.node(str(SCHEME.uri("AIAgent"))).status == EXTRACTED       # a label match is extracted, not guessed
    assert v.node(str(SCHEME.uri("UseCase"))).status == VOCABULARY      # nobody linked it; the ontology did
    assert {e.label for e in v.edges} == {"about", "realises"} and v.as_of.startswith("2026")


def test_a_derived_neighbour_is_on_the_picture_at_the_rung_that_produced_it(fab):
    one, two = _record(fab, "Agent design note"), _record(fab, "Use-case intake", term="Use case")
    assert fab.derive()["rules"]["concept-path"] >= 1
    v = fab.topology(one)
    other = v.node(two)
    assert (other.kind, other.status, other.label) == ("artifact", "D", "Use-case intake")
    assert any(e.target == two and e.label == "relatedTo" for e in v.edges)


def test_a_term_the_vocabulary_lacks_is_drawn_as_a_gap_rather_than_left_out(fab):
    v = fab.topology(_record(fab, "Agent design note"), proposed=["Widget"])
    assert next(n for n in v.nodes if n.status == PROPOSED).label == "Widget"


def test_the_ontology_ring_can_be_turned_off_for_the_record_alone(fab):
    v = fab.topology(_record(fab, "Agent design note"), ontology_ring=False)
    assert str(SCHEME.uri("UseCase")) not in {n.id for n in v.nodes}


def test_the_picture_reads_every_vocabulary_the_derivation_reads(fab):
    """The two must not disagree: an edge derived through a scheme the picture skipped is an edge on the page
    that nothing on the page explains."""
    other = vocab(name="risk", title="Risk",
                  concepts=[{"id": "AIAgent", "name": "AI agent"}, {"id": "Control", "name": "Control"}],
                  relationships=[{"subject": "AIAgent", "predicate": "mitigatedBy", "object": "Control"}])
    fab.ds.graph(URIRef("urn:lab:semantic:vocab:risk")).__iadd__(other.graph())
    fab._schemes = lambda: {"cafe": SCHEME, "risk": other}
    assert [sc.name for sc in fab._relational_schemes()] == ["cafe", "risk"]
    v = fab.topology(_record(fab, "Agent design note"))
    assert {e.label for e in v.edges} >= {"realises", "mitigatedBy"}


def test_a_record_the_catalogue_does_not_hold_is_a_refusal_naming_it(fab):
    with pytest.raises(LookupError, match="nope"):
        fab.topology("urn:fabric:artifact:nope")


# --------------------------------------------------- what else RELATES to this, through the ontology

PHARMA = vocab(name="pharma", title="Pharmacy", concepts=[
    {"id": "Prescription", "name": "Prescription"},
    {"id": "PrescriptionItem", "name": "Prescription item"},
    {"id": "Dispense", "name": "Dispense"},
    {"id": "Sibling", "name": "Sibling", "parent": "Prescription"}],   # hierarchy only — never a domain statement
    relationships=[{"subject": "Prescription", "predicate": "contains", "object": "PrescriptionItem"}])


@pytest.fixture
def pharma():
    ds = Dataset(default_union=True)
    ds.graph(URIRef(f"urn:lab:semantic:vocab:{PHARMA.name}")).__iadd__(PHARMA.graph())
    svc = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {PHARMA.name: PHARMA})
    return svc


def _about(svc, title, term):
    iri = svc.catalog_upsert({"source": "collab", "handle": f"collab://item/{title}"}, title=title)["iri"]
    svc.vocab_link(iri, [term], schemes=["pharma"])
    return iri


def test_RELATED_finds_a_record_sharing_NO_concept_when_the_ONTOLOGY_connects_them(pharma):
    """The question this was built for. A document about `Prescription` and a spreadsheet about
    `Prescription item` share no subject at all — a shared-concept ranking returns nothing — but the
    vocabulary states `Prescription contains Prescription item`, so they are about connected things.

    `derive`'s concept-path rule already writes that edge at rung D. This reads it rather than
    re-deriving it, so the rule keeps one home, and recovers the predicate the derivation drops: D's
    provenance records only the near concept, never the far one or the predicate that joined them."""
    doc = _about(pharma, "Dispensing rules", "Prescription")
    sheet = _about(pharma, "Item catalogue", "Prescription item")
    _about(pharma, "Dispense log", "Dispense")                      # unrelated: nothing joins it
    assert pharma.related(doc) == [], "before the derivation there is nothing to read"

    assert pharma.derive()["rules"]["concept-path"] >= 1
    out = pharma.related(doc)
    assert [r["iri"] for r in out] == [sheet], f"only the ontology-connected record, got {out}"
    row = out[0]
    assert row["via_kind"] == "derived"
    assert (row["via"], row["via_predicate"], row["via_object"]) == (
        str(PHARMA.uri("Prescription")), "contains", str(PHARMA.uri("PrescriptionItem")))
    assert row["via_label"] == "Prescription" and row["via_object_label"] == "Prescription item"
    assert row["shared"] == [] and row["title"] == "Item catalogue"


def test_RELATED_does_not_connect_two_records_merely_SIBLING_in_the_hierarchy(pharma):
    """`skos:broader` is not a statement about the domain, which is why the derivation filters on
    `?p a rdf:Property`. Two documents under one parent are not thereby about connected things, and
    a ranking that said they were would make every taxonomy branch a false neighbourhood."""
    doc = _about(pharma, "Dispensing rules", "Prescription")
    _about(pharma, "Sibling note", "Sibling")
    pharma.derive()
    assert pharma.related(doc) == []


def test_RELATED_ranks_a_SHARED_concept_above_a_derived_path(pharma):
    """Both are evidence; one is stronger. A record about the same concept is about the same thing,
    while a derived neighbour is about something the vocabulary says is connected — so shared wins
    regardless of how rare the derived path's concepts are. No discount factor: the two are ordered
    by KIND first, then each by specificity, so neither needs a number to sit beside the other."""
    doc = _about(pharma, "Dispensing rules", "Prescription")
    same = _about(pharma, "Second opinion", "Prescription")
    sheet = _about(pharma, "Item catalogue", "Prescription item")
    pharma.derive()
    out = pharma.related(doc)
    assert [r["iri"] for r in out] == [same, sheet]
    assert [r["via_kind"] for r in out] == ["shared", "derived"]
