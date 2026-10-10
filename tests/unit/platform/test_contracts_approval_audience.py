"""WHO an approval is for — `lab.platform.contracts` STEWARD_KINDS / OWNER_KINDS.

Measured on this lab's own stream 10 Oct 2026: 101 open `concept-admission` cards against ~37 of
everything else, all on one queue. An OWNER is asked about THEIR artifact (urgent, personal); a
STEWARD is asked about the VOCABULARY (deliberate, periodic). On one queue each buries the other:
a steward opening Teams saw a wall of term questions, and an owner had to scroll past them to find
their own card.

The split is by KIND and is declared ONCE, here, because the invariant is a PARTITION: a kind
claimed by both audiences is announced twice, a kind claimed by neither is announced to nobody, and
both failures are silent. These tests pin the partition, not a list — adding a kind is then an
additive change that cannot go unclassified.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_contracts_approval_audience.py
"""
from lab.platform.contracts import (OWNER_KINDS, STEWARD_KINDS, ApprovalAudience, ApprovalKind,
                                    approval_audience)


def test_the_two_audiences_partition_every_approval_kind():
    assert STEWARD_KINDS | OWNER_KINDS == set(ApprovalKind)
    assert not STEWARD_KINDS & OWNER_KINDS
    assert STEWARD_KINDS and OWNER_KINDS, "a split with an empty side is not a split"


def test_every_kind_resolves_to_the_audience_that_claims_it():
    for kind in ApprovalKind:
        want = ApprovalAudience.STEWARD if kind in STEWARD_KINDS else ApprovalAudience.OWNER
        assert approval_audience(kind) is want
        # the WIRE string, which is what the request stream actually carries
        assert approval_audience(kind.value) is want


def test_the_vocabulary_question_is_the_stewards_and_an_artifact_question_is_not():
    assert ApprovalKind.CONCEPT_ADMISSION in STEWARD_KINDS
    for kind in (ApprovalKind.DRAFT_REVIEW, ApprovalKind.ASSOCIATION, ApprovalKind.EA_IMPORT,
                 ApprovalKind.SPEAKER_MAPPING, ApprovalKind.IMPACT_NOTICE):
        assert kind in OWNER_KINDS, kind


def test_a_kind_nobody_has_classified_still_reaches_a_person():
    """An approval staged before the rename carries `adoit-import`, which is no enum member at all.
    The default must be OWNER: those are the channels that always existed, so an unclassified
    question is announced exactly where it would have been announced before — never nowhere. The
    same reasoning the kind rename itself used: nothing DISPATCHES on kind, so nothing may vanish
    because of it."""
    assert approval_audience("adoit-import") is ApprovalAudience.OWNER
    assert approval_audience("") is ApprovalAudience.OWNER
    assert approval_audience(None) is ApprovalAudience.OWNER
