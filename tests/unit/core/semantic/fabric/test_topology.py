"""The picture the fabric hands a renderer: what a record is about, and what that connects it to.

Built from the CURRENT graph on every call — there is no stored layout and no cached view, because a drawing of
last week's knowledge that looks exactly like this week's is the failure worth designing out.
"""
import pytest

from lab.core.semantic.fabric.topology import view_of
from lab.core.semantic.fabric.vocabulary import build
from lab.core.viz import FOCUS, PROPOSED, VOCABULARY, Edge, Node, TopologyView

SCHEME = build(name="cafe", title="t",
               concepts=[{"id": "AIAgent", "name": "AI agent", "module": "ENG"},
                         {"id": "UseCase", "name": "Use case", "module": "BIZ"},
                         {"id": "Lonely", "name": "Lonely"}],
               relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])
RECORD = {"iri": "urn:fabric:artifact:A", "title": "Agent design note", "state": "published",
          "document_type": "urn:fabric:scheme:doc-types#decision-record",
          "links": [{"predicate": "subject", "object": str(SCHEME.uri("AIAgent")), "rung": "X", "label": "AI agent"},
                    {"predicate": "documentType", "object": "urn:x#decision-record", "rung": "H"}]}


def test_the_record_is_the_focus_and_its_subjects_are_the_first_ring():
    v = view_of(RECORD, as_of="2026-09-28T10:00:00Z")
    assert isinstance(v, TopologyView) and v.focus == RECORD["iri"] and v.as_of.startswith("2026")
    assert v.title == "Agent design note" and v.subtitle == "decision-record"
    assert v.node(RECORD["iri"]).status == FOCUS and v.node(RECORD["iri"]).kind == "artifact"
    about = v.node(str(SCHEME.uri("AIAgent")))
    assert (about.label, about.kind, about.status) == ("AI agent", "concept", "X")
    assert [(e.label, e.status) for e in v.edges] == [("about", "X")]      # documentType is not about-ness


def test_the_vocabulary_supplies_the_second_ring_with_the_predicate_on_the_edge():
    v = view_of(RECORD, schemes=[SCHEME])
    ids = {n.id for n in v.nodes}
    assert str(SCHEME.uri("UseCase")) in ids and str(SCHEME.uri("Lonely")) not in ids
    edge = next(e for e in v.edges if e.label == "realises")
    assert (edge.source, edge.target) == (str(SCHEME.uri("AIAgent")), str(SCHEME.uri("UseCase")))
    assert edge.status == VOCABULARY and v.node(edge.target).note == "BIZ"
    assert view_of(RECORD, schemes=[SCHEME], ontology_ring=False).nodes == view_of(RECORD).nodes


def test_every_vocabulary_the_fabric_owns_is_asked_not_just_the_first():
    """A second relational scheme is one registry entry away, and a picture that reads one while the derivation
    reads all of them draws `relatedTo` edges it cannot explain."""
    other = build(name="risk", title="t",
                  concepts=[{"id": "AIAgent", "name": "AI agent"}, {"id": "Control", "name": "Control"}],
                  relationships=[{"subject": "AIAgent", "predicate": "mitigatedBy", "object": "Control"}])
    v = view_of(RECORD, schemes=[SCHEME, other])
    assert {e.label for e in v.edges} >= {"realises", "mitigatedBy"}
    assert str(other.uri("Control")) in {n.id for n in v.nodes}


def test_derived_neighbours_and_unadmitted_terms_both_appear():
    v = view_of(RECORD, schemes=[SCHEME], proposed=["Widget"],
                related=[{"iri": "urn:fabric:artifact:B", "title": "Use-case intake", "rung": "D",
                          "predicate": "relatedTo", "state": "pending"}])
    other = v.node("urn:fabric:artifact:B")
    assert (other.kind, other.status, other.note) == ("artifact", "D", "pending")
    gap = next(n for n in v.nodes if n.status == PROPOSED)
    assert gap.label == "Widget" and "no concept" in gap.note
    assert {e.label for e in v.edges} >= {"about", "realises", "relatedTo"}
    assert set(v.statuses) == {FOCUS, "X", VOCABULARY, "D", PROPOSED}


def test_a_view_refuses_to_be_internally_inconsistent():
    with pytest.raises(ValueError, match="node the view lacks"):
        TopologyView(title="t", focus="a", nodes=(Node(id="a", label="A", kind="artifact", status=FOCUS),),
                     edges=(Edge(source="a", target="ghost", label="about", status="X"),))
    with pytest.raises(ValueError, match="focus"):
        TopologyView(title="t", focus="nope", nodes=(Node(id="a", label="A", kind="artifact", status=FOCUS),))
    with pytest.raises(ValueError, match="share an id"):
        TopologyView(title="t", focus="a", nodes=(Node(id="a", label="A", kind="artifact", status=FOCUS),
                                                  Node(id="a", label="A again", kind="concept", status="X")))
    with pytest.raises(ValueError, match="HOW"):
        Edge(source="a", target="b", label="", status="X")
    with pytest.raises(ValueError, match="id and a label"):
        Node(id="a", label="", kind="concept", status="X")


def test_the_same_thing_named_twice_is_drawn_once():
    """A concept can be a subject AND the vocabulary's neighbour of another; a record can be related to
    itself through two concepts. Either would make two nodes of one thing, and a view refuses that."""
    twice = {**RECORD, "links": list(RECORD["links"]) * 2 + [{"predicate": "subject", "object": "", "rung": "X"}]}
    v = view_of(twice, schemes=[SCHEME], proposed=["Widget", "Widget", ""],
                related=[{"iri": "urn:fabric:artifact:B", "title": "B"}, {"iri": "urn:fabric:artifact:B"},
                         {"iri": ""}])
    assert len(v.nodes) == len({n.id for n in v.nodes})
    assert len([n for n in v.nodes if n.label == "Widget"]) == 1


def test_a_record_about_nothing_is_still_a_view():
    v = view_of({"iri": "urn:fabric:artifact:C", "title": "Untouched", "links": []}, schemes=[SCHEME])
    assert len(v.nodes) == 1 and v.edges == () and v.statuses == (FOCUS,)
