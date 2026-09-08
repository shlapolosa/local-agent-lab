"""What any `ReferenceLibrary` must do, run against the in-memory double.

The plan is for this suite to run TWICE — here against `fixtures.reference.FakeReferenceLibrary`,
and again against the Postgres adapter with a fake connection once that lands. That is the point of
writing it against the port rather than the implementation: a double that drifts from the real
thing lets a test pass on behaviour that fails in production, which is the lesson
`tests/fixtures/workflow.py` already records for the gateway router.

Most of these are refusals. CR-12 is the reason: no all-clear may be inferred from a stale or
unavailable index, and an empty list is the most dangerous possible return value here because
"nothing matched" and "the corpus is not there" look identical to whoever iterates the result.
"""
from datetime import timedelta

import pytest

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from lab.core.reference.errors import (
    ArtifactUnverified,
    IndexUnavailable,
    PinExpired,
    ReferenceUnavailable,
    UnknownRecordType,
)
from lab.core.reference.model import ArtifactKind, RunRef
from lab.core.reference.port import ReferenceLibrary

RUN = RunRef(run_id="wfr-1", process="use_case_screening", field="criticality_class")


# Built per test, not shared at module scope: a `SeededArtifact` is mutable, and a test that flips
# `indexed` on a shared instance silently changes what the next test is exercising.
def mapping() -> SeededArtifact:
    return SeededArtifact(
        artifact_id="guardrail-mapping", kind=ArtifactKind.RECORD, title="Risk class mapping",
        record_type="risk-class", records=[
            {"record_id": "rec-e2", "risk_class": "E2", "mandatory": "G09, G17"},
            {"record_id": "rec-e3", "risk_class": "E3", "mandatory": "G09, G16"}])


def tradeoffs() -> SeededArtifact:
    return SeededArtifact(
        artifact_id="tradeoff-catalogue", kind=ArtifactKind.PROSE, title="Tradeoff catalogue",
        passages=[{"passage_id": "psg-1", "heading_path": ["Tradeoffs", "G23"],
                   "text": "idempotency key plus a compensating action"},
                  {"passage_id": "psg-2", "heading_path": ["Tradeoffs", "G18"],
                   "text": "human sampling at a declared rate plus an outcome assertion"}])


@pytest.fixture
def library():
    return FakeReferenceLibrary([mapping(), tradeoffs()])


# ---------------------------------------------------------------- the port itself

def test_the_double_satisfies_the_port(library):
    assert isinstance(library, ReferenceLibrary)


# ---------------------------------------------------------------- catalogue and pin

def test_the_catalogue_lists_what_this_ring_may_consult(library):
    assert {a.artifact_id for a in library.catalogue()} == {"guardrail-mapping",
                                                            "tradeoff-catalogue"}


def test_an_empty_catalogue_refuses_rather_than_answering_nothing():
    """A library with nothing in it is indistinguishable from a library that is not there."""
    with pytest.raises(ReferenceUnavailable):
        FakeReferenceLibrary([]).catalogue()


def test_an_artifact_released_only_to_a_narrower_ring_is_not_visible():
    pilot_only = SeededArtifact("pilot-thing", ArtifactKind.RECORD, record_type="x", ring=0)
    library = FakeReferenceLibrary([pilot_only], ring=0)
    assert library.catalogue()
    with pytest.raises(ReferenceUnavailable):
        FakeReferenceLibrary([SeededArtifact("later", ArtifactKind.RECORD, record_type="x",
                                             ring=2)], ring=1).pin(["later"])


def test_a_pin_freezes_one_version_per_artifact(library):
    pin = library.pin()
    assert pin.version_of("guardrail-mapping").version


def test_a_pin_refuses_wholesale_when_any_artifact_fails_verification():
    """A run must not begin with a partially trustworthy corpus, so one bad signature fails the
    whole pin rather than quietly dropping that artifact."""
    library = FakeReferenceLibrary([mapping(), SeededArtifact(
        "bad", ArtifactKind.RECORD, record_type="x", verified=False)])
    with pytest.raises(ArtifactUnverified):
        library.pin()


def test_an_expired_pin_refuses_rather_than_drifting_onto_a_newer_version(library):
    library.pin_ttl = timedelta(seconds=-1)
    pin = library.pin()
    with pytest.raises(PinExpired):
        library.lookup(pin, record_type="risk-class", key={"risk_class": "E2"}, run=RUN)


# ---------------------------------------------------------------- lookup: a miss is an answer

def test_an_exact_lookup_returns_the_record_and_a_citation(library):
    pin = library.pin()
    out = library.lookup(pin, record_type="risk-class", key={"risk_class": "E2"}, run=RUN)
    assert out.matched == 1
    assert out.records[0].body["mandatory"] == "G09, G17"
    assert out.citations[0].version and out.citations[0].master_ref


def test_a_miss_is_a_legitimate_answer_not_an_error(library):
    pin = library.pin()
    out = library.lookup(pin, record_type="risk-class", key={"risk_class": "E9"}, run=RUN)
    assert out.matched == 0


def test_a_near_miss_never_appears_among_the_records(library):
    """The nearly-right predicate this whole side of the corpus exists to prevent."""
    pin = library.pin()
    out = library.lookup(pin, record_type="risk-class",
                         key={"risk_class": "E2", "mandatory": "something else"}, run=RUN)
    assert out.matched == 0
    assert out.near


def test_an_unknown_record_type_refuses_and_names_the_known_ones(library):
    pin = library.pin()
    with pytest.raises(UnknownRecordType) as e:
        library.lookup(pin, record_type="not-a-type", key={"x": 1}, run=RUN)
    assert "risk-class" in str(e.value)


# ---------------------------------------------------------------- search: fails closed

def test_search_returns_passages_with_citations(library):
    pin = library.pin()
    out = library.search(pin, question="compensating action", run=RUN)
    assert out.passages
    assert out.citations[0].anchor


def test_an_unindexed_version_refuses_rather_than_returning_nothing(library):
    """The CR-12 case. An empty result set would read as "the corpus has nothing on this", which
    is the all-clear the control forbids inferring."""
    library.artifacts["tradeoff-catalogue"].indexed = False
    pin = library.pin()
    with pytest.raises(IndexUnavailable):
        library.search(pin, question="anything", run=RUN)


def test_a_query_embedded_by_a_different_model_refuses(library):
    """Comparing a query embedded by one model against passages embedded by another returns
    plausible nonsense — detectable only because the model is recorded per passage."""
    library.query_model = "some-other-embed"
    pin = library.pin()
    with pytest.raises(IndexUnavailable) as e:
        library.search(pin, question="anything", run=RUN)
    assert "some-other-embed" in str(e.value)


# ---------------------------------------------------------------- attribution and the reverse index

def test_every_read_records_its_consumption_inside_the_call(library):
    """There is deliberately no "report your sources afterwards" step for a run to forget."""
    pin = library.pin()
    library.lookup(pin, record_type="risk-class", key={"risk_class": "E2"}, run=RUN)
    rows = library.consumers(artifact_id="guardrail-mapping",
                             version=pin.version_of("guardrail-mapping").version)
    assert rows and rows[0].field == "criticality_class"


def test_a_miss_is_recorded_too(library):
    """"We consulted the price sheet and it had no line for this" is itself a derivation fact."""
    pin = library.pin()
    library.lookup(pin, record_type="risk-class", key={"risk_class": "E9"}, run=RUN)
    rows = library.consumers(artifact_id="guardrail-mapping",
                             version=pin.version_of("guardrail-mapping").version)
    assert rows and rows[0].hit is False


def test_a_cited_record_can_be_reopened_by_the_id_the_citation_carries(library):
    pin = library.pin()
    out = library.lookup(pin, record_type="risk-class", key={"risk_class": "E3"}, run=RUN)
    locator = out.citations[0].locator
    again = library.record(pin, artifact_id="guardrail-mapping", record_id=locator, run=RUN)
    assert again.body["mandatory"] == "G09, G16"
