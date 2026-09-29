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
