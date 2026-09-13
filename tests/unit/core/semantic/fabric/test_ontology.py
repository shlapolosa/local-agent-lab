"""The fabric's ontology and document-type scheme LOAD — the Turtle parses, the registry accepts them, and
the lifecycle states the shapes name are the ones the ontology declares. (A bad statement in fab.ttl once
passed every other test because nothing parsed the file.)"""
from rdflib import RDF, URIRef

from lab.core.semantic.fabric.catalog import STATE_IRI
from lab.core.semantic.fabric.ontology import FAB, DocumentTypes, FabricOntology
from lab.core.semantic.ontology import Ontology, Registry, SemanticStore


def test_both_entries_satisfy_the_ontology_protocol_and_parse():
    fab, dt = FabricOntology(), DocumentTypes()
    assert isinstance(fab, Ontology) and isinstance(dt, Ontology)
    assert fab.summary()["classes"] >= 10 and fab.summary()["triples"] > 50
    assert dt.summary() == {"kind": "skos", "name": "doc-types", "base": str(dt.ns), "concepts": 6}


def test_every_catalog_state_is_a_lifecycle_state_of_the_ontology():
    g = FabricOntology().graph()
    declared = {str(s) for s in g.subjects(RDF.type, FAB.LifecycleState)}
    assert set(STATE_IRI.values()) == declared


def test_doc_types_name_the_producing_process():
    dt = DocumentTypes()
    assert dt.for_process("transcript_to_minutes") == "urn:fabric:scheme:doc-types#minutes"
    assert dt.for_process("no_such_process") is None
    assert all(t["label"] for t in dt.types().values())


def test_a_store_over_the_registry_holds_both_graphs():
    r = Registry(); r.add(FabricOntology()); r.add(DocumentTypes())
    st = SemanticStore(r)
    assert len(st.ds.graph(URIRef("urn:lab:semantic:vocab:fabric"))) > 50
    assert len(st.ds.graph(URIRef("urn:lab:semantic:vocab:doc-types"))) > 6


def test_a_document_type_resolves_by_iri_label_or_alt_label_and_names_the_choices_otherwise():
    import pytest
    dt = DocumentTypes()
    assert dt.resolve("urn:fabric:scheme:doc-types#minutes") == "urn:fabric:scheme:doc-types#minutes"
    assert dt.resolve("Decision record") == dt.resolve("adr") == "urn:fabric:scheme:doc-types#decision-record"
    assert dt.resolve("MEETING MINUTES").endswith("#minutes")
    with pytest.raises(ValueError, match="Decision record"):
        dt.resolve("shopping list")
    assert dt.types() is dt.types() or dt.types() == dt.types()          # cached load, one parse per process
