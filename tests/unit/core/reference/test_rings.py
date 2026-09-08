"""CR-18 — shared artifact changes are released progressively and rate-limited across instances.

A change to the criticality taxonomy or the role rate registry alters every open business case at
once. Release rings are what stop a bad edit reaching all of them simultaneously: it lands in the
pilot ring, soaks, and only then moves outward.

Pure arithmetic over timestamps, so the whole rule is testable without a database, which is the
point of keeping it here rather than in the publisher.
"""
from datetime import datetime, timedelta, timezone

import pytest

from lab.core.reference.rings import (
    RINGS,
    RingError,
    ReleaseDecision,
    can_release,
    next_ring,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
SOAK = timedelta(hours=24)


def test_the_pilot_ring_can_be_released_to_immediately():
    """Something has to go first, and the pilot ring is what "first" means."""
    out = can_release(0, previous_released_at=None, now=NOW, soak=SOAK)
    assert out.allowed is True


def test_a_wider_ring_waits_for_the_one_below_it_to_soak():
    just_now = NOW - timedelta(minutes=30)
    out = can_release(1, previous_released_at=just_now, now=NOW, soak=SOAK)
    assert out.allowed is False
    assert "soak" in out.reason.lower()


def test_a_wider_ring_opens_once_the_soak_has_elapsed():
    long_ago = NOW - timedelta(hours=25)
    assert can_release(1, previous_released_at=long_ago, now=NOW, soak=SOAK).allowed is True


def test_a_wider_ring_cannot_be_released_to_before_the_one_below_it_at_all():
    """Skipping a ring is not a faster rollout, it is no rollout — the soak never happened."""
    out = can_release(2, previous_released_at=None, now=NOW, soak=SOAK)
    assert out.allowed is False
    assert "ring 1" in out.reason


def test_a_defect_recorded_against_the_version_stops_it_going_wider():
    out = can_release(1, previous_released_at=NOW - timedelta(days=3), now=NOW, soak=SOAK,
                      defects=("a business case costed against it double-counted the run cost",))
    assert out.allowed is False
    assert "defect" in out.reason.lower()


def test_a_roll_back_is_always_allowed_however_recent_the_release():
    """The one direction that must never be rate-limited. A soak on rolling BACK would keep a
    known-bad artifact in front of every instance for exactly as long as it took to notice."""
    out = can_release(2, previous_released_at=NOW, now=NOW, soak=SOAK, rollback=True)
    assert out.allowed is True


def test_a_roll_back_is_allowed_even_with_defects_recorded():
    out = can_release(2, previous_released_at=NOW, now=NOW, soak=SOAK, rollback=True,
                      defects=("anything at all",))
    assert out.allowed is True


def test_an_unpublished_ring_refuses():
    with pytest.raises(RingError):
        can_release(9, previous_released_at=None, now=NOW, soak=SOAK)


def test_every_decision_carries_a_reason_a_person_can_act_on():
    for ring, previous in ((0, None), (1, NOW), (1, NOW - timedelta(days=2))):
        out = can_release(ring, previous_released_at=previous, now=NOW, soak=SOAK)
        assert isinstance(out, ReleaseDecision)
        assert out.reason.strip()


def test_the_rings_run_from_pilot_outward():
    assert RINGS[0] < RINGS[-1]
    assert next_ring(0) == 1
    assert next_ring(RINGS[-1]) is None
