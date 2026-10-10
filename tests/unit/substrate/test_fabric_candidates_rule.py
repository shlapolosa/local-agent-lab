"""The candidate-cleanup RULE: which open `concept-admission` cards a steward should never have been asked.

`scripts/fabric_candidates.py` is an operator script and scripts are coverage-exempt, but `classify` DECLINES
a person's card, so the rule has the same blast radius as `fabric_hygiene.is_working_file` and is tested the
same way — as a pure function over plain dicts, offline.

Measured 10 Oct 2026, the backlog this was written for: 71 open cards for 44 distinct labels, of which 25
cards across 7 labels name a term the vocabulary ALREADY HOLDS as a DOCUMENT TYPE (`Decision record` x12,
`Meeting minutes` x6, `Architecture model` x2, `Solution design` x2, `Architecture decision record`,
`Decision Record`, `Requirements`). The classifier had confused what a document IS with what it is ABOUT.
The rest are one card per proposal where one card per TERM was wanted.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import fabric_candidates as C  # noqa: E402

#: the live shape: `label` -> the vocabulary that holds it, which is also what the decline comment quotes
HELD = {"decision record": "doc-types", "meeting minutes": "doc-types",
        "architecture decision record": "doc-types (alt label of 'Decision record')"}


def rows(*labels):
    return [{"label": t, "request_id": f"apr-{i}"} for i, t in enumerate(labels)]


# ---------------------------------------------------------------- normalise


def test_normalise_casefolds_and_collapses_internal_whitespace():
    """ONE rule, in one place, because the matching of every surface depends on it. Case alone would have
    matched `Decision Record` to `Decision record` (`Scheme.find` already casefolds and strips), but NOT
    `Decision  record`: internal whitespace is exactly the difference between this rule and the vocabulary's
    own lookup, and it is why a term the vocabulary holds can still be sitting in the candidates."""
    assert C.normalise("Decision Record") == "decision record"
    assert C.normalise("  Decision   record\t") == "decision record"
    assert C.normalise("Decision\nrecord") == "decision record"
    assert C.normalise("") == ""
    assert C.normalise(None) == ""


# ------------------------------------------------------------ label_of_card


def test_the_label_is_read_off_the_cards_subject():
    """`approvals_get` deliberately withholds a card's `context` (an operator must not learn what a decision
    releases), so the term is recoverable only from the subject `fabric_vocabulary.ask_open` wrote."""
    assert C.label_of_card("'Decision record' has no concept — should the vocabulary gain one?") == "Decision record"
    assert C.label_of_card('"Patient\'s record" has no concept — should the vocabulary gain one?') == "Patient's record"


def test_a_conflict_card_is_not_a_candidate_card_and_yields_no_label():
    """`concept-admission` carries BOTH of the steward's questions: a candidate to admit and a word that means
    two things. A conflict is settled by naming the meaning to keep — never by this cleanup — so it must read
    as unparseable and be left alone, not matched on the term it happens to quote."""
    assert C.label_of_card("'Registry' means more than one thing — which meaning is it?") == ""
    assert C.label_of_card("") == ""


# ---------------------------------------------------------------- classify


def test_a_term_the_vocabulary_already_holds_is_held_and_names_its_holder():
    out = C.classify(rows("Decision record"), HELD)
    assert [r["verdict"] for r in out] == [C.HELD]
    assert "doc-types" in out[0]["reason"]


def test_held_is_matched_through_the_normalised_label():
    """The live backlog held `Decision record` x12 AND `Decision Record` x1 — the same term, asked twice."""
    assert [r["verdict"] for r in C.classify(rows("Decision Record", "Decision  record"), HELD)] == [C.HELD, C.HELD]


def test_a_later_card_for_the_same_term_is_a_duplicate_and_the_first_is_kept():
    """One card per PROPOSAL was raised where one per TERM was wanted: a steward answering the first settles
    the term, which is why the first survives and every later one is noise."""
    out = C.classify(rows("Golden record", "golden record", "Golden  record"), HELD)
    assert [r["verdict"] for r in out] == [C.KEEP, C.DUPLICATE, C.DUPLICATE]


def test_held_beats_duplicate_so_every_card_for_a_held_term_is_declined():
    """A held term's FIRST card must not be kept: there is nothing for a steward to admit, and `keep` is read
    as "a person still has to answer this"."""
    assert {r["verdict"] for r in C.classify(rows("Meeting minutes", "meeting minutes"), HELD)} == {C.HELD}


def test_a_genuinely_new_term_is_kept():
    out = C.classify(rows("Capability map", "Tariff schedule"), HELD)
    assert [r["verdict"] for r in out] == [C.KEEP, C.KEEP]


def test_a_row_with_no_label_is_kept_never_declined():
    """Silence is the safe answer: a card whose subject this rule cannot read is one a person decides. The
    alternative is declining somebody's question because a regex changed."""
    assert C.classify([{"label": "", "request_id": "apr-x"}], HELD)[0]["verdict"] == C.KEEP
    assert C.classify([{"request_id": "apr-x"}], HELD)[0]["verdict"] == C.KEEP


def test_classify_is_pure_and_order_preserving():
    """It returns a verdict per input row, in order, and mutates nothing — the shell pairs the verdicts back
    to the cards it read by position and by request id."""
    given = rows("Decision record", "Capability map", "capability map")
    before = [dict(r) for r in given]
    out = C.classify(given, HELD)
    assert given == before
    assert [r["request_id"] for r in out] == ["apr-0", "apr-1", "apr-2"]
    assert all("verdict" in r and r["reason"] for r in out)


def test_every_verdict_is_one_of_the_three_and_each_carries_a_reason():
    """An INVARIANT rather than an exact set: a new verdict may be added, but nothing may come back without a
    verdict the shell knows or without the sentence that goes in the decline comment."""
    out = C.classify(rows("Decision record", "Capability map", "capability map", ""), HELD)
    assert {r["verdict"] for r in out} <= {C.HELD, C.DUPLICATE, C.KEEP}
    assert all(r["reason"].strip() for r in out)
