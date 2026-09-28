"""The domain vocabulary the fabric OWNS — concepts with alt labels and TYPED relationships between them.

Two things separate this from the reference schemes already in the registry. Its ids come from the SOURCE and
stay stable, because the use-case pipeline joins on them and a label-hash id would move the day somebody fixes a
typo. And it carries real predicates between concepts: `skos:related` cannot say HOW two concepts relate, and the
whole point of an ontology over a taxonomy is that it can.
"""
import pytest
from rdflib import RDF, Literal

from lab.core.semantic.fabric.vocabulary import DomainScheme, build
from lab.core.semantic.ontology import META, Ontology
from lab.core.semantic.skos import SKOS

CONCEPTS = [
    {"id": "Referral", "name": "Referral", "module": "CARE", "kind": "entity", "parent": "",
     "definition": "A request to transfer a patient's care."},
    {"id": "UrgentReferral", "name": "Urgent referral", "module": "CARE", "kind": "entity",
     "parent": "Referral", "definition": ""},
    {"id": "DigitalPlatform", "name": "Digital platform", "module": "ENG", "kind": "reference", "parent": ""},
]
RELATIONSHIPS = [
    {"subject": "Referral", "predicate": "raisedOn", "object": "DigitalPlatform", "cardinality": "1..n"},
    {"subject": "UrgentReferral", "predicate": "escalates", "object": "Referral"},
]


def scheme(**over):
    args = {"name": "cafe", "title": "CAFÉ domain ontology", "concepts": CONCEPTS,
            "relationships": RELATIONSHIPS, "source": "cafe-artifacts.xlsx", "version": "v0.30"}
    return build(**{**args, **over})


def test_it_is_a_vocabulary_the_registry_can_hold():
    s = scheme()
    assert isinstance(s, (DomainScheme, Ontology)) and isinstance(s, Ontology)
    assert s.summary()["kind"] == "skos-scheme" and s.summary()["concepts"] == 3
    assert s.version == "v0.30" and s.base.startswith("urn:") and s.uri("Referral") == s.ns["Referral"]


def test_ids_come_from_the_source_and_the_hierarchy_is_levelled():
    s = scheme()
    assert set(s.concepts) == {"Referral", "UrgentReferral", "DigitalPlatform"}      # never a label hash
    assert s.concepts["UrgentReferral"]["parent"] == "Referral"
    assert (s.concepts["Referral"]["level"], s.concepts["UrgentReferral"]["level"]) == (1, 2)
    assert s.concepts["Referral"]["module"] == "CARE" and s.concepts["Referral"]["label"] == "Referral"
    assert sorted(s.roots(kind="entity")) == ["Referral"]


def test_a_concept_without_an_id_or_a_name_is_refused_and_a_cycle_does_not_hang():
    with pytest.raises(ValueError, match="id"):
        scheme(concepts=[{"name": "no id"}])
    with pytest.raises(ValueError, match="name"):
        scheme(concepts=[{"id": "X"}])
    with pytest.raises(ValueError, match="parent"):
        scheme(concepts=[{"id": "X", "name": "X", "parent": "Nope"}], relationships=[])
    cyclic = [{"id": "A", "name": "A", "parent": "B"}, {"id": "B", "name": "B", "parent": "A"}]
    with pytest.raises(ValueError, match="cycle"):
        scheme(concepts=cyclic, relationships=[])


def test_find_matches_a_preferred_or_an_alternative_label_case_folded():
    s = scheme(concepts=[{**CONCEPTS[0], "alt": ["referral request", "RFR"]}], relationships=[])
    assert [c["id"] for c in s.find("Referral")] == ["Referral"]
    assert [c["id"] for c in s.find("  referral REQUEST ")] == ["Referral"]
    assert [c["id"] for c in s.find("rfr")] == ["Referral"]
    assert s.find("nothing here") == []


def test_resolve_takes_an_id_a_label_or_an_alt_and_names_the_choices_otherwise():
    s = scheme(concepts=[{**CONCEPTS[0], "alt": ["RFR"]}], relationships=[])
    assert s.resolve("Referral") == "Referral" and s.resolve("rfr") == "Referral"
    assert s.resolve(str(s.uri("Referral"))) == "Referral"
    with pytest.raises(ValueError, match="Referral"):
        s.resolve("shopping list")


def test_relationships_are_typed_predicates_in_the_graph_not_skos_related():
    s = scheme()
    g = s.graph()
    assert (s.uri("Referral"), s.predicate("raisedOn"), s.uri("DigitalPlatform")) in g
    assert (s.uri("UrgentReferral"), s.predicate("escalates"), s.uri("Referral")) in g
    assert not list(g.triples((None, SKOS.related, None)))          # untyped would lose the point
    assert (s.predicate("raisedOn"), RDF.type, RDF.Property) in g   # the predicate is declared
    assert (s.predicate("raisedOn"), META.cardinality, Literal("1..n")) in g


def test_the_graph_carries_labels_definitions_modules_and_the_hierarchy():
    s = scheme(concepts=[{**CONCEPTS[0], "alt": ["RFR"]}, CONCEPTS[1]],
               relationships=[RELATIONSHIPS[1]])          # the edge whose ends are both here
    g = s.graph()
    u, child = s.uri("Referral"), s.uri("UrgentReferral")
    assert (u, SKOS.prefLabel, Literal("Referral")) in g and (u, SKOS.altLabel, Literal("RFR")) in g
    assert (u, SKOS.definition, Literal("A request to transfer a patient's care.")) in g
    assert (u, META.module, Literal("CARE")) in g
    assert (child, SKOS.broader, u) in g and (u, SKOS.narrower, child) in g


def test_an_edge_naming_an_unknown_concept_is_refused_rather_than_dropped():
    with pytest.raises(ValueError, match="Ghost"):
        scheme(relationships=[{"subject": "Referral", "predicate": "x", "object": "Ghost"}])
    with pytest.raises(ValueError, match="predicate"):
        scheme(relationships=[{"subject": "Referral", "predicate": "", "object": "Referral"}])


def test_relations_of_answers_what_a_concept_is_connected_to():
    s = scheme()
    assert s.relations_of("Referral") == [("raisedOn", "DigitalPlatform", "out"),
                                          ("escalates", "UrgentReferral", "in")]
    assert s.relations_of("Nope") == []


def test_columns_the_fabric_does_not_model_are_carried_not_dropped():
    """The fabric becomes the MASTER of this vocabulary, so what it publishes back must not be narrower than what
    it seeded from. The real master carries authoritative_source, fhir, guild_reference, platforms, sources,
    status and used_by — none of which the fabric models today, and all of which would vanish on a round trip."""
    s = scheme(concepts=[{**CONCEPTS[0], "authoritative_source": "ADHDS TSA v1", "status": "accepted",
                          "fhir": "ServiceRequest"}], relationships=[])
    c = s.concepts["Referral"]
    assert c["extra"] == {"authoritative_source": "ADHDS TSA v1", "status": "accepted", "fhir": "ServiceRequest"}
    assert "id" not in c["extra"] and "definition" not in c["extra"]      # what is modelled is not duplicated
    assert s.rows()[0]["fhir"] == "ServiceRequest" and s.rows()[0]["id"] == "Referral"
    assert set(s.rows()[0]) >= {"id", "name", "module", "kind", "parent", "definition", "fhir"}
