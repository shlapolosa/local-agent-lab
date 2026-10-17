"""The deterministic lane of the inverted classifier: ground, normalise, match.

A model reads the artifact and says what it is about in its own words. Everything after that is this
module, and it is pure on purpose — the fuzzy half (an embedding) is computed outside and handed in, so
the DECISIONS are testable without a model, a gateway or a vector store.

Parameters here are not guesses. `scripts/fabric_extraction_probe.py` measured them on live records
(17 Oct 2026): 97% of evidence spans appear VERBATIM in the excerpt, so grounding can be strict; and the
top1-top2 MARGIN separates a real match from an arbitrary one far better than an absolute score does —
'PHI/PII data handling boundaries' -> PII guardrail at 0.113, against 'proposed decision status' ->
Prior authorisation at 0.0016, which is nonsense an absolute threshold waves through.
"""
import pytest

from lab.core.semantic.fabric import concepts as C

EXCERPT = ("A dispense confirmation reaches the issuing system within five minutes of dispensing.\n"
           "Where the callback fails, the retry behaviour is settled in ADR-042.")


# ----------------------------------------------------------------------------- ground
def test_a_span_present_verbatim_is_grounded():
    assert C.ground("A dispense confirmation reaches the issuing system", EXCERPT) is True


def test_a_span_the_model_INVENTED_is_not_grounded():
    """The whole point. An extractor may NAME a concept the text never names — that is why it is a model
    and not a regex — but it may not invent the EVIDENCE. The term survives on inference; the span does
    not."""
    assert C.ground("the pharmacy must retain a paper copy", EXCERPT) is False


def test_whitespace_differences_do_not_break_grounding():
    """Measured: 1 span in 78 needed this. An excerpt is markdown-wrapped and hard-cut at 2000 chars, so
    a model quoting across a line break is quoting honestly."""
    assert C.ground("confirmation reaches   the issuing\nsystem", EXCERPT) is True


def test_an_empty_span_grounds_nothing():
    assert C.ground("", EXCERPT) is False
    assert C.ground("anything", "") is False


# ----------------------------------------------------------------------------- normalise
def test_normalise_is_SYMMETRIC_with_what_find_already_does():
    """`DomainScheme.find` compares `casefold().strip()` and nothing else. Normalising one side harder
    than the other LOWERS the hit rate — lemmatising 'referrals' to 'referral' only helps if the label is
    lemmatised too, and the labels are not ours to rewrite. So this does what `find` does, plus the one
    thing `find` cannot: a trailing plural."""
    assert C.normalise("  Prescription  ") == "prescription"
    assert C.normalise("The Prescription") == "prescription"
    assert C.normalise("Prescriptions") == C.normalise("prescription")


def test_normalise_does_not_mangle_a_word_that_merely_ends_in_s():
    """'Status' and 'Analysis' are not plurals. A naive trailing-s rule turns them into 'statu' and
    'analysi' and the term stops matching anything at all."""
    for word in ("Status", "Analysis", "Access", "Address", "Diagnosis"):
        assert C.normalise(word) == word.casefold(), word


# ----------------------------------------------------------------------------- match
def scored(*pairs):
    return [{"id": i, "score": s} for i, s in pairs]


def test_a_clear_winner_matches():
    assert C.match(scored(("PIIGuardrail", 0.78), ("Claim", 0.66)), floor=0.5, margin=0.05) == "PIIGuardrail"


def test_a_NARROW_margin_matches_NOTHING_however_high_the_score():
    """The finding that shapes this rule. 'proposed decision status' scored highest against *Prior
    authorisation* with a margin of 0.0016 — a coin toss between concepts that have nothing to do with
    each other, which an absolute threshold would have accepted as a fact at rung X."""
    assert C.match(scored(("PriorAuthorisation", 0.71), ("Claim", 0.7084)), floor=0.5, margin=0.05) is None


def test_a_score_below_the_FLOOR_matches_nothing_however_wide_the_margin():
    """A wide margin over two bad answers is still two bad answers."""
    assert C.match(scored(("Anything", 0.21), ("Other", 0.02)), floor=0.5, margin=0.05) is None


def test_nothing_to_choose_from_matches_nothing():
    assert C.match([], floor=0.5, margin=0.05) is None
    assert C.match(scored(("Only", 0.9)), floor=0.5, margin=0.05) == "Only"


def test_the_candidates_need_not_arrive_sorted():
    assert C.match(scored(("Low", 0.2), ("Best", 0.9), ("Mid", 0.5)), floor=0.5, margin=0.05) == "Best"
