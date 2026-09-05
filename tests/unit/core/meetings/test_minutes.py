"""The MAPPER — gated minutes to a `meeting-1.0` spec. Where correctness lives, so tested alone.

Pure: no I/O, no gateway, no store. What is pinned is the identity SCOPE (which nodes are shared
across meetings and which are not), the referential checks, and the privacy rule that no directory
address reaches the graph.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/meetings/test_minutes.py
"""
import tempfile

import pytest

from lab.core.meetings import MinutesError, minutes_to_spec
from lab.core.meetings import ids
from lab.core.semantic.service import SemanticService
from lab.core.meetings import Speaker, Speakers

MAP = Speakers((Speaker("SPEAKER_00", identity="maria.perez@contoso.com"),
                  Speaker("SPEAKER_01", tag="the vendor's architect")))
MEETING = {"id": "mtg-1", "subject": "Architecture review", "date": "2026-09-04",
           "transcript_ref": "art://t/x.json"}
MINUTES = {
    "summary": "We agreed to retire the portal.",
    "concepts": [{"id": "c1", "label": "Claims Adjudication", "definition": "Deciding payable amounts."}],
    "decisions": [{"id": "d1", "statement": "Retire the legacy portal", "concerns": ["c1"],
                   "decided_by": ["SPEAKER_00"], "confidence": "high",
                   "evidence": [{"speaker": "SPEAKER_00", "start": 120, "end": 180}]}],
    "actions": [{"id": "a1", "commitment": "Draft the migration plan", "owner": "SPEAKER_01",
                 "due": "2026-10-12", "concerns": ["c1"], "implements": "d1"}],
}


@pytest.fixture(scope="module")
def svc():
    return SemanticService(reference_dir=tempfile.mkdtemp(prefix="minutes-map-"))


def _spec(minutes=None, meeting=None, speakers=MAP):
    return minutes_to_spec(minutes or MINUTES, meeting or MEETING, speakers)


def _by_id(spec):
    return {e["id"]: e for e in spec["elements"]}


def _edges(spec):
    return {(r["src"], r["type"], r["tgt"]) for r in spec["relations"]}


# ------------------------------------------------------------------ it produces a LEGAL model
def test_the_mapped_spec_is_legal_against_the_vocabulary(svc):
    """The mapper's real contract: whatever it emits must satisfy the matrix, or the load fails
    later where the cause is no longer obvious."""
    assert svc.validate_model(_spec(), "meeting-1.0")["illegal"] == []


def test_it_builds_the_edges_the_model_is_centred_on():
    e = _edges(_spec())
    assert ("d1", "Concerns", "c1") in e and ("a1", "Concerns", "c1") in e
    assert ("a1", "Implements", "d1") in e and ("a1", "OwnedBy", "SPEAKER_01") in e
    assert ("d1", "DecidedBy", "SPEAKER_00") in e


def test_provenance_points_from_the_durable_thing_to_the_meeting():
    e = _edges(_spec())
    assert {("c1", "RaisedIn", "meeting"), ("d1", "RaisedIn", "meeting"),
            ("a1", "RaisedIn", "meeting")} <= e
    assert not any(src == "meeting" and rel != "" for src, rel, _ in e if src == "meeting")


# ------------------------------------------------------------------ identity scope
def test_a_concept_is_the_same_node_in_every_meeting():
    """The join the concept-centred model rests on."""
    a = _by_id(_spec())["c1"]["iri"]
    b = _by_id(_spec(meeting={"id": "mtg-2", "subject": "Another"}))["c1"]["iri"]
    assert a == b == ids.concept_iri("Claims Adjudication")


def test_the_same_words_decided_in_two_meetings_are_two_commitments():
    a = _by_id(_spec())["d1"]["iri"]
    b = _by_id(_spec(meeting={"id": "mtg-2", "subject": "Another"}))["d1"]["iri"]
    assert a != b


def test_a_person_is_the_same_node_wherever_they_appear():
    a = _by_id(_spec())["SPEAKER_00"]["iri"]
    other = Speakers((Speaker("SPEAKER_07", identity="MARIA.PEREZ@contoso.com"),))
    b = _by_id(_spec(minutes={"summary": "s", "concepts": []}, speakers=other))["SPEAKER_07"]["iri"]
    assert a == b, "case and label differ; the human does not"


def test_a_directory_person_and_a_tagged_person_are_told_apart_by_prefix():
    """Results are shortened to their fragment, so the prefix is the only thing that survives to say
    whether a node is a directory fact or a human's free-text guess."""
    people = _by_id(_spec())
    assert "#per-" in people["SPEAKER_00"]["iri"] and "#tag-" in people["SPEAKER_01"]["iri"]
    assert people["SPEAKER_01"]["props"]["external"] == "true"
    assert people["SPEAKER_00"]["props"]["idKind"] == "upn"


# ------------------------------------------------------------------ privacy
def test_no_directory_address_reaches_the_graph():
    """A queryable graph is the wrong place for text nobody can redact later. The address is hash
    input and stays in the transcript; the graph gets a display name."""
    blob = repr(_spec())
    assert "maria.perez@contoso.com" not in blob and "@" not in _by_id(_spec())["SPEAKER_00"]["name"]
    assert _by_id(_spec())["SPEAKER_00"]["name"] == "maria.perez"


def test_evidence_is_offsets_never_a_quote():
    props = _by_id(_spec())["d1"]["props"]
    assert props["evidenceStart"] == "120" and props["evidenceEnd"] == "180"
    assert not any("retire" in str(v).lower() for k, v in props.items() if k.startswith("evidence"))


# ------------------------------------------------------------------ referential checks
def test_a_decision_about_a_concept_that_is_not_there_is_refused():
    bad = {**MINUTES, "decisions": [{"id": "d1", "statement": "x", "concerns": ["c9"]}]}
    with pytest.raises(MinutesError, match="c9"):
        _spec(minutes=bad)


def test_implementing_something_that_is_not_a_decision_is_refused():
    bad = {**MINUTES, "actions": [{"id": "a1", "commitment": "x", "owner": "SPEAKER_00",
                                   "concerns": ["c1"], "implements": "d9"}]}
    with pytest.raises(MinutesError, match="d9"):
        _spec(minutes=bad)


def test_an_unmapped_speaker_fails_naming_the_label():
    """The whole point of the human gate: an unattributed voice must never reach the minutes as
    SPEAKER_03."""
    bad = {**MINUTES, "actions": [{"id": "a1", "commitment": "x", "owner": "SPEAKER_03",
                                   "concerns": ["c1"]}]}
    with pytest.raises(KeyError, match="SPEAKER_03"):
        _spec(minutes=bad)


def test_a_meeting_without_an_id_is_refused():
    with pytest.raises(MinutesError, match="id"):
        _spec(meeting={"subject": "no id"})


def test_minutes_with_only_concepts_still_map():
    """A meeting that decided nothing is a real meeting; it still contributes what it was about."""
    spec = _spec(minutes={"summary": "we talked", "concepts": [{"id": "c1", "label": "Triage"}]})
    assert {e["type"] for e in spec["elements"]} == {"Meeting", "Person", "Concept"}


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
