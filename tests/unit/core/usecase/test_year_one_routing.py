"""The figure the delegated authority routes on must be the year-one cost the same run computed.

Audited 23 Sep 2026, two defects in one line:

* **capex was dropped.** `year_one_investment = build + 12 x monthly` never saw `capex`, while the
  cost model's own `year_one_total` includes it. A design with 400k capex and 10k/month showed the
  conformance reviewer 520k and routed the investment on 120k — under a 250k band that is a
  DIRECTOR instead of the board. `authority.py`'s own docstring calls routing down the direction
  that produces no observable event afterwards.
* **a missing build cost became 0.0.** `float(... or 0.0)` turned "nobody captured a build cost"
  into a number. `authority.route` handles `None` correctly — it escalates to the top band — and
  never received it. The live run had `build_provenance: ""`, so a 2M build would have routed on
  120k.

Both resolve the same way: every uncertainty about an amount resolves UPWARD, because routing too
high wastes a meeting and routing too low commits money nobody authorised.
"""
import pytest

from lab.core.usecase import benefit, cost


def _summary(**kw):
    return benefit.financial_summary(drivers=(benefit.Driver("d", amount=120_000.0),), **kw)


def test_capex_is_part_of_what_the_authority_routes_on():
    with_capex = _summary(build_cost=0.0, monthly_run_cost=10_000.0, capex=400_000.0)
    assert with_capex.year_one_investment == 400_000.0 + 12 * 10_000.0


def test_it_agrees_with_the_cost_model_s_own_year_one():
    """The two numbers are shown to two different people — the reviewer sees the cost model's, the
    authority routes on this one. They must be the same number."""
    monthly = cost.ThreePoint(8_000.0, 10_000.0, 14_000.0)
    model = cost.year_one_total(monthly, 50_000.0 + 400_000.0)
    summary = _summary(build_cost=50_000.0, monthly_run_cost=10_000.0, capex=400_000.0)
    assert summary.year_one_investment == model.expected


def test_an_uncaptured_build_cost_is_unknown_not_zero():
    """`None` is what makes `authority.route` escalate. 0.0 is a figure, and a figure routes."""
    summary = _summary(build_cost=None, monthly_run_cost=10_000.0)
    assert summary.year_one_investment is None


def test_a_zero_build_cost_that_was_actually_captured_is_still_zero():
    """Nothing to build is a real answer — it must not be confused with nobody having said."""
    summary = _summary(build_cost=0.0, monthly_run_cost=10_000.0)
    assert summary.year_one_investment == 120_000.0


def test_an_unknown_investment_cannot_be_used_to_compute_a_payback_or_an_roi():
    summary = _summary(build_cost=None, monthly_run_cost=10_000.0)
    assert summary.payback_months is None and summary.three_year_roi is None
