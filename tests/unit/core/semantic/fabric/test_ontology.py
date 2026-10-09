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
    summary = dt.summary()
    assert (summary["kind"], summary["name"], summary["base"]) == ("skos", "doc-types", str(dt.ns))
    assert summary["concepts"] >= 8          # MEMBERSHIP, not an exact set: the scheme grows (CLAUDE.md)


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


def test_a_person_can_answer_that_no_type_fits_and_it_resolves_to_the_sentinel():
    """The honest answer must be ANSWERABLE. The gate asked "is the document type right?", the
    classifier had already said `unknown` as a fact, and `none` was then refused — which closed the
    card and stranded the record (9 Oct 2026). `dt:unknown` is a concept so the answer travels the
    same path as any other: one doc-types IRI, coerced, shaped and queryable."""
    dt = DocumentTypes()
    unknown = "urn:fabric:scheme:doc-types#unknown"
    assert dt.resolve("unknown") == dt.resolve("none") == dt.resolve("No type fits") == unknown
    assert dt.resolve("OTHER") == unknown


def test_a_requirements_specification_is_a_document_type():
    """A BRS/FRS is the document kind the lab reads most and could not name."""
    dt = DocumentTypes()
    want = "urn:fabric:scheme:doc-types#requirements-specification"
    assert dt.resolve("BRS") == dt.resolve("frs") == dt.resolve("Requirements specification") == want
    assert dt.for_process("artifact_intake") is None     # a person's answer, not a process's product


def test_the_sentinel_is_answerable_by_a_person_but_never_offered_to_the_classifier():
    """An agent given "none of these fits" as a listed choice takes it. The classifier's honest path for
    not knowing is already an EMPTY document_type, which the gate turns into a question for a person —
    and the person is the one who may answer with the sentinel."""
    dt = DocumentTypes()
    assert dt.SENTINEL in dt.types() and dt.SENTINEL not in dt.suggestable()
    assert dt.resolve("unknown") == dt.SENTINEL                  # ...but still answerable
    assert set(dt.suggestable()) | {dt.SENTINEL} == set(dt.types())
