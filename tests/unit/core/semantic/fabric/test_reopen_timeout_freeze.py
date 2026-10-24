"""FR-16 reopen a decline, FR-17 the author's confirmation times out, FR-18 a ratified record's subjects
freeze (user decisions 24 Oct 2026, from SAF becoming a channel of the fabric).

Each is a PRODUCT rule, so each test states the rule it pins:
  * a decline is final until a STEWARD reopens it — with a reason, audited apart from the decline, and the
    evidence kept;
  * vocabulary never blocks the forum: a term the author has not confirmed within one WORKING day reaches
    the steward marked UNCONFIRMED, never silently confirmed;
  * once a record is ratified, no automated path changes what it is about; a steward still can.
"""
from datetime import datetime, timezone

import pytest
from rdflib import Dataset, URIRef

from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric import workdays
from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.rungs import CONFIRMED, EXTRACTED
from lab.core.semantic.fabric.service import FabricService
from lab.core.semantic.fabric.vocabulary import build

SUBJECT = "http://purl.org/dc/terms/subject"


def scheme():
    return build(name="cafe", title="CAFÉ",
                 concepts=[{"id": "AIAgent", "name": "AI agent"}, {"id": "UseCase", "name": "Use case"},
                           {"id": "Prescription", "name": "Prescription"}],
                 relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])


@pytest.fixture
def fab():
    sc = scheme()
    ds = Dataset(default_union=True)
    ds.graph(URIRef("urn:lab:semantic:vocab:cafe")).__iadd__(sc.graph())
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {"cafe": sc})
    f.scheme = sc                     # type: ignore[attr-defined]
    return f


def _doc(f, title="ADR-14"):
    return f.catalog_upsert({"source": "collab", "handle": f"collab://item/{title}"}, title=title)["iri"]


def _open(f):
    return {c["label"]: c for c in f.vocab_candidates()}


# ============================================================ FR-16 reopen a decline
def test_a_steward_may_REOPEN_a_declined_term_and_it_is_asked_again_with_its_evidence(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe", proposed_for="urn:fabric:artifact:a1")
    fab.vocab_asked(c["iri"], request_id="apr-1")
    fab.vocab_decline(c["iri"], actor="ea@x", reason="not a concept")
    assert "Model card" not in _open(fab)
    r = fab.vocab_reopen(c["iri"], actor="ea@x", reason="the forum changed its mind")
    assert r["reopened"] is True and r["state"] == "pending"
    row = _open(fab)["Model card"]
    assert row["asked"] is False                          # asked AFRESH, through the normal ask path
    assert row["proposed_for"] == ["urn:fabric:artifact:a1"]          # evidence kept


def test_a_reopen_is_audited_apart_from_the_decline_it_reopens(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.vocab_decline(c["iri"], actor="ea@x", reason="not a concept")
    r = fab.vocab_reopen("Model card", actor="admin@x", reason="appeal upheld", scheme="cafe")
    assert r["iri"] == c["iri"]                           # a LABEL names the candidate too
    hist = r["history"]
    assert hist["declined_by"] == "ea@x" and hist["decline_reason"] == "not a concept"
    assert hist["reopened_by"] == "admin@x" and hist["reopen_reason"] == "appeal upheld"


def test_only_a_declined_term_reopens_and_a_reopen_names_a_person_and_a_reason(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    with pytest.raises(ValueError, match="not declined"):
        fab.vocab_reopen(c["iri"], actor="ea@x", reason="r")
    fab.vocab_decline(c["iri"], actor="ea@x")
    with pytest.raises(ValueError, match="actor"):
        fab.vocab_reopen(c["iri"], actor="", reason="r")
    with pytest.raises(ValueError, match="reason"):
        fab.vocab_reopen(c["iri"], actor="ea@x", reason=" ")
    with pytest.raises(LookupError):
        fab.vocab_reopen("Never proposed", actor="ea@x", reason="r", scheme="cafe")


def test_an_AUTHOR_removal_reopens_too(fab):
    iri = _doc(fab)
    p = fab.vocab_propose("Dispense audit", actor="intake", scheme="cafe", proposed_for=iri, awaiting_author=True)
    fab.vocab_author_confirm(p["iri"], decision="remove", actor="author@x")
    assert fab.vocab_reopen(p["iri"], actor="ea@x", reason="author misread")["state"] == "pending"
    assert "Dispense audit" in _open(fab)


def test_a_declined_RELATION_reopens_and_is_open_again(fab):
    q = fab.vocab_relation_propose(scheme="cafe", subject="Prescription", predicate="realises", object="UseCase")
    fab.vocab_relation_decline(q["iri"], actor="ea@x", reason="no")
    assert not fab.vocab_relation_open()
    r = fab.vocab_reopen(q["iri"], actor="ea@x", reason="reconsidered")
    assert r["reopened"] is True
    assert [o["iri"] for o in fab.vocab_relation_open()] == [q["iri"]]


def test_reopening_twice_is_refused_because_it_is_no_longer_declined(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.vocab_decline(c["iri"], actor="ea@x")
    fab.vocab_reopen(c["iri"], actor="ea@x", reason="r")
    with pytest.raises(ValueError, match="not declined"):
        fab.vocab_reopen(c["iri"], actor="ea@x", reason="r")


def test_an_import_carries_REOPEN_history_idempotently(fab):
    rows = [{"label": "Model card", "scheme": "cafe", "status": "Reopened", "actor": "ea@x",
             "reason": "appeal upheld", "declined_by": "steward@x", "decline_reason": "not a concept"}]
    first = fab.vocab_candidates_import(rows, actor="operator")
    assert first["problems"] == [] and first["results"][0]["outcome"] == "reopened"
    assert "Model card" in _open(fab)
    again = fab.vocab_candidates_import(rows, actor="operator")
    assert again["problems"] == [] and again["results"][0]["outcome"] in ("reopened", "pending")
    assert len([c for c in fab.vocab_candidates() if c["label"] == "Model card"]) == 1


def test_a_decline_REPLACES_the_in_review_marker_so_the_state_is_unambiguous(fab):
    """A latent defect found on the way: `vocab_asked` wrote InReview and `vocab_decline` ADDED Withdrawn
    beside it, so a declined row carried two states and `value()` could report either."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.vocab_asked(c["iri"], request_id="apr-1")
    fab.vocab_decline(c["iri"], actor="ea@x")
    states = list(fab.ds.graph(URIRef("urn:fabric:graph:candidates")).objects(URIRef(c["iri"]),
                  URIRef("urn:fabric:ont#lifecycleState")))
    assert [str(s) for s in states] == ["urn:fabric:ont#Withdrawn"]


# ============================================================ FR-17 the author times out
MON_9 = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)        # a Monday


def test_working_hours_skip_the_weekend():
    fri_17 = datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc)
    mon_17 = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)
    assert workdays.working_hours_between(MON_9, datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)) == 24
    assert workdays.working_hours_between(fri_17, mon_17) == 24      # Fri 17:00 → Mon 17:00 is one working day
    assert workdays.working_hours_between(mon_17, fri_17) == 0       # backwards is nothing


def _awaiting(f, label="Dispense audit", at=MON_9):
    iri = _doc(f)
    p = f.vocab_propose(label, actor="intake", scheme="cafe", proposed_for=iri, awaiting_author=True, now=at)
    return p["iri"]


def test_a_term_the_author_never_confirms_reaches_the_steward_marked_UNCONFIRMED(fab):
    c = _awaiting(fab)
    assert fab.vocab_author_timeouts(hours=24, now=datetime(2026, 10, 19, 18, tzinfo=timezone.utc))["advanced"] == []
    out = fab.vocab_author_timeouts(hours=24, now=datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc))
    assert out["advanced"] == [c]
    row = _open(fab)["Dispense audit"]
    assert row["confirmation"] == "timeout"               # never silently "confirmed"


def test_a_friday_extraction_waits_out_the_weekend(fab):
    _awaiting(fab, at=datetime(2026, 10, 23, 16, tzinfo=timezone.utc))
    sunday = datetime(2026, 10, 25, 23, tzinfo=timezone.utc)
    assert fab.vocab_author_timeouts(hours=24, now=sunday)["advanced"] == []
    monday_late = datetime(2026, 10, 26, 16, 30, tzinfo=timezone.utc)
    assert len(fab.vocab_author_timeouts(hours=24, now=monday_late)["advanced"]) == 1


def test_the_timeout_pass_is_idempotent_and_leaves_confirmed_terms_alone(fab):
    c = _awaiting(fab)
    later = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
    fab.vocab_author_timeouts(hours=24, now=later)
    assert fab.vocab_author_timeouts(hours=24, now=later)["advanced"] == []
    other = _awaiting(fab, label="Audit trail")
    fab.vocab_author_confirm(other, decision="confirm", actor="author@x")
    rows = _open(fab)
    assert rows["Audit trail"]["confirmation"] == "author" and rows["Dispense audit"]["confirmation"] == "timeout"
    assert c


def test_a_person_s_proposal_is_recorded_as_confirmed_by_a_person(fab):
    c = _awaiting(fab)
    fab.vocab_propose("Dispense audit", actor="maria@x", scheme="cafe")
    assert _open(fab)["Dispense audit"]["confirmation"] == "person"
    assert c


def test_an_awaiting_term_from_before_the_clock_existed_starts_its_clock_rather_than_timing_out(fab):
    c = _awaiting(fab)
    g = fab.ds.graph(URIRef("urn:fabric:graph:candidates"))
    g.remove((URIRef(c), URIRef("urn:fabric:ont#awaitingSince"), None))     # a legacy row
    far = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert fab.vocab_author_timeouts(hours=24, now=far)["advanced"] == []
    assert fab.vocab_author_timeouts(hours=24, now=datetime(2027, 1, 6, tzinfo=timezone.utc))["advanced"] == [c]


# ============================================================ FR-18 a ratified record's subjects freeze
def test_a_FROZEN_record_is_not_relinked_by_the_classifier_and_says_so(fab):
    iri = _doc(fab)
    fab.vocab_link(iri, ["AI agent"])
    fab.catalog_freeze(iri, actor="ea@x", reason="ADR ratified")
    out = fab.vocab_link(iri, ["Use case"])               # a re-read would REPLACE AI agent with Use case
    assert out["frozen"] is True and out["linked"] == []
    assert out["frozen_skipped"] == ["Use case"]
    subjects = {str(o) for _r, (_s, _p, o) in G.find(fab.ds, URIRef(iri), URIRef(SUBJECT))}
    assert subjects == {str(fab.scheme.uri("AIAgent"))}  # nothing added, nothing retracted


def test_an_AUTOMATED_subject_assertion_on_a_frozen_record_is_reported_not_written(fab):
    iri = _doc(fab)
    fab.catalog_freeze(iri, actor="ea@x", reason="ratified")
    got = fab.graph_assert(iri, SUBJECT, str(fab.scheme.uri("UseCase")), rung=EXTRACTED, method="vocabulary-admission")
    assert got["frozen"] is True and got["assertion"] == ""
    assert not G.find(fab.ds, URIRef(iri), URIRef(SUBJECT))


def test_a_STEWARD_still_changes_a_frozen_record_at_rung_H(fab):
    iri = _doc(fab)
    fab.vocab_link(iri, ["AI agent"])
    fab.catalog_freeze(iri, actor="ea@x", reason="ratified")
    made = fab.graph_assert(iri, SUBJECT, str(fab.scheme.uri("UseCase")), rung=CONFIRMED, method="steward",
                            actor="ea@x")
    assert made["assertion"] and not made.get("frozen")
    assert fab.graph_retract(iri, SUBJECT, str(fab.scheme.uri("AIAgent")), actor="ea@x", reason="wrong subject")


def test_freezing_names_a_person_and_reports_its_state(fab):
    iri = _doc(fab)
    with pytest.raises(ValueError, match="actor"):
        fab.catalog_freeze(iri, actor="", reason="r")
    r = fab.catalog_freeze(iri, actor="ea@x", reason="ratified")
    assert r["frozen"] is True and r["actor"] == "ea@x"
    assert fab.catalog_freeze(iri, actor="ea@x", reason="again")["already"] is True
    assert fab.catalog_get(iri)["subjects_frozen"] is True


def test_only_dct_subject_freezes(fab):
    """A frozen record may still be related, typed or owned — the rule is about what it is ABOUT."""
    iri, other = _doc(fab), _doc(fab, "ADR-15")
    fab.catalog_freeze(iri, actor="ea@x", reason="ratified")
    got = fab.graph_assert(iri, "urn:fabric:ont#relatedTo", other, rung=EXTRACTED, method="rule")
    assert got["assertion"] and not got.get("frozen")
