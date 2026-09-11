"""The competency questions (docs/fabric/competency-questions.md) as SPARQL over fixture triples — the
acceptance suite of the semantic layer, run before any production triple exists. Graph letters per note 005."""
import pytest
from rdflib import URIRef

from fixtures.fabric import A1, A2, A3, C_CARE, MEETING, USECASE, dataset

P = """
PREFIX fab:  <urn:fabric:ont#>
PREFIX dct:  <http://purl.org/dc/terms/>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX prov: <http://www.w3.org/ns/prov#>
"""
TRUSTED = "VALUES ?g { <urn:fabric:graph:C> <urn:fabric:graph:X> <urn:fabric:graph:H> <urn:fabric:graph:D> }"


@pytest.fixture(scope="module")
def ds():
    return dataset()


def rows(ds, q):
    return [tuple(r) for r in ds.query(P + q)]


def test_cq01_identity_resolves_to_custody(ds):
    got = rows(ds, f"SELECT ?url WHERE {{ GRAPH <urn:fabric:graph:C> {{ <{A1}> dcat:accessURL ?url }} }}")
    assert len(got) == 1 and str(got[0][0]).startswith("https://")


def test_cq02_lifecycle_states(ds):
    got = {str(a): str(s).rsplit("#", 1)[-1] for a, s in rows(ds, "SELECT ?a ?s WHERE { GRAPH <urn:fabric:graph:C> { ?a fab:lifecycleState ?s } }")}
    assert got[str(A1)] == "Published" and got[str(A3)] == "Pending"


def test_cq03_no_record_holds_content(ds):
    """Must answer NONE: the metadata-only fitness function as a query (the SHACL shape is the enforcement)."""
    got = rows(ds, "SELECT ?a WHERE { GRAPH ?g { ?a ?p ?o } FILTER (?p IN (fab:body, fab:content, fab:text)) }")
    assert got == []


def test_cq04_baseline(ds):
    got = rows(ds, f"SELECT ?v WHERE {{ GRAPH <urn:fabric:graph:C> {{ <{A1}> fab:baselineVersion ?v }} }}")
    assert len(got) == 1 and str(got[0][0]) == "3.0"


def test_cq05_delivered_under_trusted_only(ds):
    q = f"SELECT ?a WHERE {{ {TRUSTED} GRAPH ?g {{ ?a fab:deliveredUnder <{USECASE}> }} }}"
    got = {r[0] for r in rows(ds, q)}
    assert got == {A2}, "A3's suggested edge must not count"


def test_cq06_by_which_rung_and_confidence(ds):
    q = f"""SELECT ?g ?conf WHERE {{ GRAPH ?g {{ <{A3}> fab:deliveredUnder ?w }}
             OPTIONAL {{ GRAPH <urn:fabric:graph:prov> {{ ?asrt fab:asserts ?st ; fab:rung ?r ; fab:confidence ?conf .
               ?st <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> <{A3}> }} }} }}"""
    got = rows(ds, q)
    assert got and str(got[0][0]).endswith("graph:S") and float(got[0][1]) == pytest.approx(0.61)


def test_cq07_orphan_queue(ds):
    q = f"SELECT ?a WHERE {{ GRAPH <urn:fabric:graph:C> {{ ?a a fab:Artifact }} FILTER NOT EXISTS {{ {TRUSTED} GRAPH ?g {{ ?a fab:deliveredUnder ?w }} }} }}"
    assert {r[0] for r in rows(ds, q)} == {A3}


def test_cq10_impact_over_trusted_edges(ds):
    q = f"SELECT ?a WHERE {{ {TRUSTED} GRAPH ?g {{ ?a (fab:references|fab:deliveredUnder) <{A1}> }} }}"
    assert {r[0] for r in rows(ds, q)} == {A2}


def test_cq12_type_and_its_rung(ds):
    q = f"SELECT ?g ?t WHERE {{ GRAPH ?g {{ <{A2}> fab:documentType ?t }} }}"
    got = rows(ds, q)
    assert str(got[0][0]).endswith("graph:S") and str(got[0][1]).endswith("decision-record")


def test_cq13_owner_and_label_only_from_C(ds):
    q = "SELECT ?g WHERE { GRAPH ?g { ?a fab:ownedBy ?o } FILTER (?g != <urn:fabric:graph:C>) }"
    assert rows(ds, q) == [], "an owner outside C would be a guessed owner"


def test_cq15_concepts_of_an_artifact_with_rung(ds):
    q = f"SELECT ?g ?k WHERE {{ GRAPH ?g {{ <{A1}> dct:subject ?k }} }}"
    got = rows(ds, q)
    assert len(got) == 1 and str(got[0][0]).endswith("graph:X")


def test_cq16_narrower_closure(ds):
    q = f"""SELECT DISTINCT ?a WHERE {{ <{C_CARE}> skos:narrower* ?k .
             VALUES ?g {{ <urn:fabric:graph:X> <urn:fabric:graph:H> }} GRAPH ?g {{ ?a dct:subject ?k }} }}"""
    assert {r[0] for r in rows(ds, q)} == {A1, A2}, "A1 is about Triage (narrower of Care Delivery); A3 only suggested"


def test_cq17_candidate_queue_is_empty_in_the_fixture(ds):
    assert rows(ds, "SELECT ?c WHERE { GRAPH <urn:fabric:graph:candidates> { ?c ?p ?o } }") == []


def test_cq23_loop_guard_answers_none(ds):
    assert rows(ds, "SELECT ?e WHERE { ?e a fab:ArtifactChanged ; fab:enteredPipeline true }") == []
