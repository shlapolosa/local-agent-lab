"""The CANDIDATE REGISTER — one row per term a steward must decide, not one per time it was met.

Measured on the live register, 10 Oct 2026, the first day anything reached a steward at all (the path had
been failing silently for weeks): **71 cards for 44 distinct labels**, and of those, **25 cards across 7
labels were for terms the vocabulary ALREADY HOLDS** — `Decision record` proposed twelve times, `Meeting
minutes` six, `Architecture model` and `Solution design` twice each. Every one of them is a DOCUMENT TYPE.

Two different defects, and only one is duplication:

  * a candidate was closed when its OWN scheme found the label, so a term parked under `cafe` was never
    checked against `doc-types`. The classifier is confusing what a document IS with what it is ABOUT — a
    decision record is not *about* "Decision record" — and the register repeated the confusion 25 times.
  * `vocab_propose` minted a fresh ULID per call with no count and no link to the proposing artifact, so N
    records using one unknown term produced N rows and a steward was asked N times. The artifact was named
    only inside a prose `definition` ("proposed while classifying screening.json"), which FR-1.1.5 cannot
    use: admitting a concept must re-match exactly the artifacts that proposed it.

Pure: a Dataset and a Catalog in memory. No store, no HTTP.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/semantic/fabric/test_candidates.py
"""
import pytest
from rdflib import Dataset, URIRef

from fixtures.embed import HashEmbedder
from fixtures.skos import scheme
from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.service import FabricService

A1 = "urn:fabric:artifact:01AAA"
A2 = "urn:fabric:artifact:01BBB"


@pytest.fixture
def fab():
    ds = Dataset(default_union=True)
    sc = scheme()
    ds.graph(URIRef("urn:lab:semantic:vocab:syn-v1")).__iadd__(sc.graph())
    return FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                         embedder=HashEmbedder(dim=8))


def _only(fab):
    cands = fab.vocab_candidates()
    assert len(cands) == 1, [c["label"] for c in cands]
    return cands[0]


def test_one_term_is_ONE_candidate_however_often_it_is_met(fab):
    """12 cards for `Decision record` asked one steward the same question twelve times."""
    first = fab.vocab_propose("Knowledge Agent", actor="classifier-agent", scheme="syn-v1", proposed_for=A1)
    again = fab.vocab_propose("Knowledge Agent", actor="classifier-agent", scheme="syn-v1", proposed_for=A2)
    assert first["iri"] == again["iri"]
    row = _only(fab)
    assert row["proposals"] == 2 and set(row["proposed_for"]) == {A1, A2}


def test_the_same_artifact_proposing_twice_counts_ONCE(fab):
    """A re-run of one record is not new evidence that a term matters."""
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    row = _only(fab)
    assert row["proposals"] == 1 and row["proposed_for"] == [A1]


def test_labels_match_on_MEANING_not_on_typing(fab):
    """`Decision record` and `Decision Record` were two rows on the live register."""
    fab.vocab_propose("Clinical Reviewer", actor="a", scheme="syn-v1", proposed_for=A1)
    fab.vocab_propose("  clinical   reviewer ", actor="a", scheme="syn-v1", proposed_for=A2)
    row = _only(fab)
    assert row["label"] == "Clinical Reviewer"        # the FIRST spelling is kept: a steward reads it
    assert row["proposals"] == 2


def test_the_same_word_in_two_vocabularies_is_two_questions(fab):
    """Schemes are never merged. One word may need a concept in each, and that is a steward's call twice."""
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="other-v1", proposed_for=A1)
    assert len({c["iri"] for c in fab.vocab_candidates()}) == 2


def test_a_term_ANY_vocabulary_already_holds_is_never_parked(fab):
    """The 25 cards. A document type is not a missing subject: it is the answer to a different question,
    and asking a steward to admit `Decision record` as a concept is asking them to duplicate the scheme."""
    out = fab.vocab_propose("Decision record", actor="classifier-agent", scheme="syn-v1", proposed_for=A1)
    assert out["held_by"] == "doc-types" and not out.get("iri")
    assert fab.vocab_candidates() == []
    # ...and an ALT label counts as held: `ADR` is `Decision record` under another name
    assert fab.vocab_propose("adr", actor="a", scheme="syn-v1", proposed_for=A1)["held_by"] == "doc-types"
    # ...as does a concept of a loaded scheme, which is the check that already existed
    assert fab.vocab_propose("Triage", actor="a", scheme="syn-v1", proposed_for=A1)["held_by"] == "syn-v1"
    assert fab.vocab_candidates() == []


def test_a_candidate_still_needs_a_label_and_an_author(fab):
    for bad in ({"label": "   "}, {"actor": ""}):
        with pytest.raises(ValueError):
            fab.vocab_propose(**{"label": "X", "actor": "a", "scheme": "syn-v1", "proposed_for": A1, **bad})


def test_a_DECLINED_candidate_stays_declined_across_a_restart(fab):
    """The defect that was actively generating the backlog, measured 10 Oct 2026: the reconciler's
    "already asked" memory is a set in the PROCESS, so every restart re-asked every still-open candidate
    with a fresh approval id. The open `concept-admission` cards went from 71 to 101 in one afternoon
    while a steward decided nothing, and a cleanup run would have been undone by the next deploy.

    A steward's "no" has to outlive the process that heard it. Recorded as `fab:Withdrawn` — the word
    the artifact lifecycle already uses for "this will not proceed" — so the register stops returning it
    and nothing re-asks."""
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    row = _only(fab)
    out = fab.vocab_decline(row["iri"], actor="steward@x", reason="a phrasing, not a concept")
    assert out["declined"] is True
    assert fab.vocab_candidates() == []

    # ...and it does not come back when the same word is met again: the answer was about the TERM
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A2)
    assert fab.vocab_candidates() == []


def test_declining_names_the_person_and_refuses_an_unknown_candidate(fab):
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    row = _only(fab)
    with pytest.raises(ValueError):
        fab.vocab_decline(row["iri"], actor="", reason="why")
    with pytest.raises(LookupError):
        fab.vocab_decline("urn:fabric:candidate:nope", actor="s@x", reason="why")


def test_a_row_from_before_the_count_existed_reports_NO_count_not_a_count_of_one(fab):
    """Caught by measuring the live register the minute this deployed, not by the test written to prevent it.

    `vocab_candidates` derived `proposals` as `len(proposed_for) or 1`, so a row from before the field
    existed reported ONE rather than nothing — and `ask_open`'s "a candidate with no count is always asked"
    guard never fired, because the count was present. All 46 surviving candidates would have been silenced
    at threshold 2, silently, on the deploy that introduced the threshold.

    Not recorded is not zero, and it is not one either."""
    g = fab.ds.graph(__import__("lab.core.semantic.fabric.rungs", fromlist=["x"]).CANDIDATES_GRAPH)
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    row = _only(fab)
    from rdflib import URIRef
    from lab.core.semantic.fabric.service import FAB
    g.remove((URIRef(row["iri"]), FAB.proposedFor, None))      # the shape every legacy row has
    legacy = _only(fab)
    assert legacy["proposals"] is None and legacy["proposed_for"] == []


def test_being_ASKED_is_recorded_on_the_candidate_and_is_idempotent(fab):
    """`fab:InReview` — Pending -> InReview -> Published|Withdrawn, the same ladder the artifacts climb.
    Idempotent because a tick that raised the card and failed to mark it will try again, and a candidate
    a steward has already ANSWERED must not be dragged back to "asked"."""
    fab.vocab_propose("Knowledge Agent", actor="a", scheme="syn-v1", proposed_for=A1)
    row = _only(fab)
    assert row["asked"] is False
    assert fab.vocab_asked(row["iri"], request_id="apr-1")["asked"] is True
    assert _only(fab)["asked"] is True                      # still VISIBLE: asked is not hidden
    assert fab.vocab_asked(row["iri"])["already"] is True    # twice is not an error

    fab.vocab_decline(row["iri"], actor="s@x", reason="no")
    assert fab.vocab_asked(row["iri"])["already"] is True    # an answered candidate is not re-asked
    with pytest.raises(LookupError):
        fab.vocab_asked("urn:fabric:candidate:nope")
