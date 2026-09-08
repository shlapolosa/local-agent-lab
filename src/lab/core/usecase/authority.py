"""Step 26b's routing — which delegated authority may approve this investment.

**The delegation-of-authority thresholds are one of three artifacts neither published source
supplies**, and that shapes everything here. The framework names the mechanism and the tenant sets
the numbers, so this module's most important behaviour is what it does with no table at all: it
ESCALATES and says why, rather than shipping a plausible band structure that would route real money
by a figure this lab invented.

The asymmetry is the whole argument. Routing too HIGH wastes a board's time and is corrected in one
meeting. Routing too LOW commits money nobody was authorised to commit, and produces no observable
event afterwards — nobody is notified that a decision was taken at the wrong level, because from
the inside it looks exactly like a decision taken at the right one. So every uncertainty here
resolves upward: no table, no figure, or an open gate condition all move the decision up.

Pure, injectable, no I/O. The table arrives as rows the caller read from the governed corpus (or
from `.env` while nobody has published one), so setting the policy never means changing this code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = ["AuthorityError", "Routing", "UNSET", "route"]

#: What the authority is called when nobody has configured who it is. Deliberately not a role that
#: exists — a placeholder that reads like a real signer would get acted on.
UNSET = "unassigned — no delegation-of-authority table is configured"


class AuthorityError(ValueError):
    """The table itself is malformed. Not a routing outcome: a broken table cannot route anything,
    and answering from one would be worse than refusing."""


@dataclass(frozen=True)
class Routing:
    authority: str
    escalated: bool
    reason: str
    band: float | None = None


def _bands(table: Sequence[Mapping[str, Any]]) -> list[tuple[float | None, str]]:
    """The table as ordered bands, validated. `limit` is the amount the band covers UP TO AND
    INCLUDING; exactly one band carries `None`, meaning "everything above"."""
    bands = [(row.get("limit"), str(row.get("authority") or "").strip()) for row in table]
    if any(not name for _, name in bands):
        raise AuthorityError("every band must name the authority that signs it")
    finite = [limit for limit, _ in bands if limit is not None]
    if len(finite) != len(bands) - 1 or bands[-1][0] is not None:
        raise AuthorityError(
            "exactly one band — the last — must be open-topped, naming who signs for the largest "
            "amount; a table whose bands run out leaves the most expensive case unrouted")
    if finite != sorted(finite) or len(set(finite)) != len(finite):
        raise AuthorityError("the bands must ascend and must not repeat a limit")
    return [(float(limit) if limit is not None else None, name) for limit, name in bands]


def route(year_one_investment: float | None, table: Sequence[Mapping[str, Any]] = (),
          *, open_conditions: Sequence[str] = ()) -> Routing:
    """Which authority may approve this, and whether the answer was reached by escalation.

    `year_one_investment` of `None` means the cost model could not be computed. That escalates to
    the top band: defaulting to the lowest would fund the cases we understand least well.
    """
    if not table:
        return Routing(UNSET, True,
                       "no delegation-of-authority table is configured, so no threshold can say "
                       "who may sign this; the decision goes to whoever owns that policy",
                       year_one_investment)

    bands = _bands(table)
    if year_one_investment is None:
        return Routing(bands[-1][1], True,
                       "the investment carries no year-one figure, so no band applies; the "
                       "decision goes to the highest authority rather than the lowest",
                       None)

    index = next(i for i, (limit, _) in enumerate(bands)
                 if limit is None or year_one_investment <= limit)

    if open_conditions:
        # FR-37d. One level, not to the top: an open condition is a reason for more scrutiny, not
        # a reason to send every incomplete case to the board.
        raised = min(index + 1, len(bands) - 1)
        return Routing(bands[raised][1], True,
                       f"the case carries unresolved conditions ({', '.join(open_conditions)}), "
                       f"so it is not one a delegated signer should close out; routed one level "
                       f"above the band its figure falls in",
                       year_one_investment)
    return Routing(bands[index][1], False,
                   f"the year-one investment falls in the band this authority signs for",
                   year_one_investment)
