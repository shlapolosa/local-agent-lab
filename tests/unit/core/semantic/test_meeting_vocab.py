"""The meeting vocabulary — a second metamodel, registered beside ArchiMate, entirely as DATA.

Concept-centred by decision: keywords and decisions are what the semantic layer is for, and who said
them is thin attribution. A meeting is PROVENANCE rather than a container, which is the property that
lets a `WorkItem` hub arrive later without re-parenting anything.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/semantic/test_meeting_vocab.py
"""
import copy
import json
import os
import tempfile

import pytest

from lab.core.semantic.meeting import build
from lab.core.semantic.meeting import vocab as mv
from lab.core.semantic.model_rdf import spec_to_triples
from lab.core.semantic.ontology import Ontology
from lab.core.semantic.service import SemanticService

V = build()


@pytest.fixture(scope="module")
def svc():
    return SemanticService(reference_dir=tempfile.mkdtemp(prefix="meeting-vocab-"))


def test_it_satisfies_the_ontology_protocol_like_every_other_kind():
    assert isinstance(V, Ontology)
    assert V.summary()["kind"] == "metamodel" and V.name == "meeting-1.0"


def test_it_is_registered_beside_archimate(svc):
    assert {"archimate-3.1", "meeting-1.0"} <= set(svc.registry.names())


# ------------------------------------------------------------------ the matrix is the contract
LEGAL = [("Decision", "Concerns", "Concept"), ("ActionItem", "Concerns", "Concept"),
         ("ActionItem", "Implements", "Decision"), ("ActionItem", "OwnedBy", "Person"),
         ("Decision", "DecidedBy", "Person"), ("Decision", "Resolves", "Decision"),
         ("Decision", "RaisedIn", "Meeting"), ("Concept", "RaisedIn", "Meeting"),
         ("Concept", "BroaderThan", "Concept"), ("Person", "Attended", "Meeting")]

ILLEGAL = [("Person", "OwnedBy", "ActionItem"),      # the likeliest mapper bug: wrong direction
           ("Meeting", "Concerns", "Concept"),       # a meeting owns nothing
           ("Decision", "Concerns", "Person"),       # a decision is about a concept, not a human
           ("Concept", "Implements", "Decision")]


@pytest.mark.parametrize("src,rel,tgt", LEGAL)
def test_legal_edges(svc, src, rel, tgt):
    assert svc.check(src, rel, tgt, vocab="meeting-1.0")["ok"]


@pytest.mark.parametrize("src,rel,tgt", ILLEGAL)
def test_illegal_edges_are_refused(svc, src, rel, tgt):
    assert not svc.check(src, rel, tgt, vocab="meeting-1.0")["ok"]


def test_provenance_points_from_the_durable_thing_to_its_evidence():
    """The direction is the whole design. If a Meeting owned its decisions, adding a WorkItem later
    would mean re-parenting every one of them."""
    assert ("Decision", "Meeting") in V.permitted
    assert ("Meeting", "Decision") not in V.permitted


# ------------------------------------------------------------------ the extension guarantee
WORK_ITEM_DIFF = {
    "natures": {"container": "A unit of managed work that concepts and commitments hang off."},
    "elements": {"WorkItem": {"nature": "container", "pii": "none",
                              "definition": "A managed unit of work — an epic, an ADR, a change request.",
                              "examples": ["EPIC-412", "ADR-17"]}},
    "relations": {"Manages": {"definition": "A work item is the accountable home of a concept.",
                              "category": "knowledge"}},
    "permitted": {"WorkItem": {"Concept": ["Manages"]},
                  "Decision": {"WorkItem": ["RaisedIn"]},
                  "ActionItem": {"WorkItem": ["RaisedIn"]},
                  "Concept": {"WorkItem": ["RaisedIn"]}},
}


def _with_work_item(tmp_path):
    """Apply the WorkItem diff to the taxonomy DATA and rebuild — no code changes at all."""
    tax = json.load(open(os.path.join(os.path.dirname(mv.__file__), "taxonomy.json"), encoding="utf-8"))
    merged = copy.deepcopy(tax)
    merged["natures"].update(WORK_ITEM_DIFF["natures"])
    merged["elements"].update(WORK_ITEM_DIFF["elements"])
    merged["relations"].update(WORK_ITEM_DIFF["relations"])
    for src, targets in WORK_ITEM_DIFF["permitted"].items():
        merged["permitted"].setdefault(src, {}).update(targets)
    d = tmp_path / "meeting"
    d.mkdir()
    (d / "taxonomy.json").write_text(json.dumps(merged), encoding="utf-8")
    saved = mv.HERE
    mv.HERE = str(d)
    try:
        return mv.build()
    finally:
        mv.HERE = saved


def test_the_work_item_hub_arrives_as_a_data_change_and_undoes_nothing(tmp_path):
    """THE test for this design. Adding the intended long-term hub must be a taxonomy edit — no
    Python, no re-parenting, and every edge that was legal before is still legal."""
    after = _with_work_item(tmp_path)
    for pair, rels in V.permitted.items():
        assert after.permitted.get(pair, set()) >= rels, f"{pair} lost {rels}"
    assert "Manages" in after.permitted[("WorkItem", "Concept")]
    assert "RaisedIn" in after.permitted[("Decision", "WorkItem")]
    assert "WorkItem" in after.classes and after.classes["WorkItem"]["nature"] == "container"


def test_a_meeting_spec_built_before_the_change_still_validates_after_it(svc, tmp_path):
    spec = {"name": "m", "elements": [
        {"id": "c1", "type": "Concept", "name": "Claims Adjudication"},
        {"id": "d1", "type": "Decision", "name": "Retire the portal"}],
        "relations": [{"src": "d1", "tgt": "c1", "type": "Concerns"}]}
    assert svc.validate_model(spec, "meeting-1.0")["illegal"] == []


# ------------------------------------------------------------------ what registration buys free
def test_classify_reads_the_definitions_nobody_coded(svc):
    assert svc.classify("we agreed to retire the legacy portal", vocab="meeting-1.0")[0]["type"] == "Decision"


def test_validation_reports_an_illegal_edge_in_a_real_spec(svc):
    spec = {"name": "m", "elements": [
        {"id": "p1", "type": "Person", "name": "organiser"},
        {"id": "a1", "type": "ActionItem", "name": "draft the plan"}],
        "relations": [{"src": "p1", "tgt": "a1", "type": "OwnedBy"}]}   # backwards on purpose
    assert svc.validate_model(spec, "meeting-1.0")["illegal"]


def test_the_archimate_interface_warnings_stay_silent_here(svc):
    """The service runs ArchiMate-specific service/interface warnings against ANY vocabulary. No
    meeting type name ends in Service or Interface so they cannot fire — asserted, not assumed."""
    spec = {"name": "m", "elements": [{"id": "c1", "type": "Concept", "name": "X"}], "relations": []}
    assert svc.validate_model(spec, "meeting-1.0")["warnings"] == []


def test_it_derives_nothing_because_its_relation_names_are_its_own():
    """Reusing an ArchiMate relation name would silently fire the derivation engine and mint triples
    with semantics this model never asked for."""
    spec = {"name": "m", "elements": [
        {"id": "c1", "type": "Concept", "name": "A"}, {"id": "c2", "type": "Concept", "name": "B"}],
        "relations": [{"src": "c1", "tgt": "c2", "type": "BroaderThan"}]}
    assert not [t for t in spec_to_triples(spec, V, "m1") if "derived" in str(t[1])]


def test_every_class_declares_both_facets():
    for name, c in V.classes.items():
        assert c["nature"] in V.facets["nature"], name
        assert c["pii"] in V.facets["pii"], name


def test_only_the_person_class_is_marked_identifying():
    """The privacy rule is DATA: a writer consults this facet rather than a comment."""
    assert {n for n, c in V.classes.items() if c["pii"] == "identifying"} == {"Person"}


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
