"""CR-18 — progressive release of shared artifacts, and the rate limit across instances.

A shared artifact is not a deployment: changing the criticality taxonomy or the role rate registry
alters every OPEN business case at once, which is why the spec puts those artifacts under the same
staged publication rule as the derivation ones. Rings are how a bad edit is stopped from reaching
every instance simultaneously — it lands in the pilot ring, soaks while real runs consume it, and
only then moves outward.

"Current" is therefore per ring, not global: while a change rolls, ring 0 may resolve to v3 while
ring 2 still resolves to v2, and BOTH are the signed current version for the instance asking. That
is why the release table is keyed on (artifact, ring) rather than carrying a `status` column.

Pure arithmetic over timestamps, deliberately: the whole rule is then testable without a database,
and the publisher is its only caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

__all__ = ["RINGS", "ReleaseDecision", "RingError", "can_release", "next_ring"]

#: Pilot outward. Numbers rather than names because the ordering IS the meaning.
RINGS = (0, 1, 2)


class RingError(ValueError):
    """A ring outside the published set — there is no such audience to release to."""


@dataclass(frozen=True)
class ReleaseDecision:
    allowed: bool
    reason: str


def next_ring(ring: int) -> int | None:
    """The ring a version moves to after this one, or None at the widest."""
    if ring not in RINGS:
        raise RingError(f"{ring!r} is not a published ring; expected one of {list(RINGS)}")
    return ring + 1 if ring + 1 in RINGS else None


def can_release(ring: int, *, previous_released_at: datetime | None, now: datetime,
                soak: timedelta, defects: tuple[str, ...] = (),
                rollback: bool = False) -> ReleaseDecision:
    """May this version be released to `ring` now?

    `previous_released_at` is when the ring BELOW received this same version. A roll-back is never
    rate-limited — a soak on rolling back would hold a known-bad artifact in front of every
    instance for exactly as long as it took somebody to notice, which inverts the control.
    """
    if ring not in RINGS:
        raise RingError(f"{ring!r} is not a published ring; expected one of {list(RINGS)}")

    if rollback:
        return ReleaseDecision(True, "a roll-back is never rate-limited — withdrawing a bad "
                                     "artifact is the one direction that must not wait")
    if defects:
        return ReleaseDecision(False, f"a defect is recorded against this version and must be "
                                      f"resolved before it goes wider: {list(defects)}")
    if ring == RINGS[0]:
        return ReleaseDecision(True, "the pilot ring is where a version starts")

    if previous_released_at is None:
        return ReleaseDecision(False, f"ring {ring - 1} has not had this version, so it has not "
                                      f"soaked anywhere — skipping a ring is not a faster rollout")
    elapsed = now - previous_released_at
    if elapsed < soak:
        remaining = soak - elapsed
        return ReleaseDecision(False, f"ring {ring - 1} has held this version for {elapsed}, short "
                                      f"of the {soak} soak; {remaining} remaining")
    return ReleaseDecision(True, f"ring {ring - 1} has held this version for {elapsed}, past the "
                                 f"{soak} soak, with no defect recorded")
