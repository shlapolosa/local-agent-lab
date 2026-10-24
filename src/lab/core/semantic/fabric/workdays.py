"""Working time, as the forum counts it: Monday to Friday, in UTC, every hour of those days.

FR-17 (user decision 24 Oct 2026): a term extracted from a document waits for its AUTHOR, and vocabulary
must never block the forum — after ONE WORKING DAY it goes on to a steward, marked unconfirmed. "Working
day" is the product's word, so the clock skips Saturday and Sunday: a term extracted on Friday afternoon
times out on Monday afternoon, not on Saturday.

Deliberately simple: whole weekdays, UTC, no public holidays and no office hours. A tenant that needs a
holiday calendar or a local timezone extends THIS function, and nothing that calls it changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["working_hours_between"]


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def working_hours_between(start: datetime, end: datetime) -> float:
    """Hours of weekday time from `start` to `end` (0 when `end` is not after `start`)."""
    a, b = _utc(start), _utc(end)
    if b <= a:
        return 0.0
    total = 0.0
    cursor = a
    while cursor < b:
        next_midnight = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        segment_end = min(next_midnight, b)
        if cursor.weekday() < 5:                       # Monday=0 … Friday=4
            total += (segment_end - cursor).total_seconds() / 3600
        cursor = segment_end
    return total
