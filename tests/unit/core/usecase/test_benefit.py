"""Step 24 — the benefit drivers, the financial summary and the recommendation.

Every arithmetic assertion here is a published formula, so a deviation is a defect and not a
variance. The rules that carry the most weight are the ones about NOT producing a number: CR-22
forbids fabricating any figure, CR-22a forbids resolving a requires-input marker by estimation, and
CR-22b admits exactly three drivers into the ROI. A business case that quietly filled a gap would
be indistinguishable from a good one.
"""
import pytest

from lab.core.usecase.benefit import (
    BenefitError,
    Recommendation,
    compliance_reduction,
    financial_summary,
    operational_efficiency,
    quality_improvement,
    recommend,
)

EFFORT = [{"role": "nurse", "headcount": 4, "frequency_per_week": 10,
           "current_minutes": 30, "expected_minutes": 10}]
RATES = {"nurse": 120.0}
QUALITY = {"current_volume": 10_000, "error_rate": 0.02, "expected_reduction": 0.5,
           "error_class": "clinical"}
ERROR_COSTS = {"clinical": 400.0}


# ---------------------------------------------------------------- driver 1

def test_operational_efficiency_follows_the_published_formula():
    # 4 x 10 x 50 x (30-10)/60 = 666.67 hours; x 120 = 80,000
    driver = operational_efficiency(EFFORT, RATES)
    assert driver.amount == pytest.approx(80_000, rel=1e-3)
    assert driver.requires_input is False


def test_a_year_one_discount_applies_where_the_data_is_not_fully_digital():
    full = operational_efficiency(EFFORT, RATES, data_fully_digital=True)
    partial = operational_efficiency(EFFORT, RATES, data_fully_digital=False)
    assert partial.amount < full.amount
    assert "discount" in partial.basis.lower()


def test_a_role_with_no_rate_in_the_registry_requires_input_rather_than_a_guessed_rate():
    driver = operational_efficiency(EFFORT, rates={})
    assert driver.requires_input is True
    assert driver.amount == 0
    assert "nurse" in driver.note


@pytest.mark.parametrize("missing", ["headcount", "frequency_per_week", "current_minutes"])
def test_an_incomplete_effort_row_requires_input(missing):
    row = {k: v for k, v in EFFORT[0].items() if k != missing}
    assert operational_efficiency([row], RATES).requires_input is True


def test_an_empty_effort_table_requires_input_rather_than_scoring_zero_benefit():
    """Zero is a claim. "Nobody told us" is a different claim, and only one of them can be fixed."""
    driver = operational_efficiency([], RATES)
    assert driver.requires_input is True


def test_expected_minutes_above_current_is_malformed_not_a_negative_saving():
    row = EFFORT[0] | {"expected_minutes": 90}
    assert operational_efficiency([row], RATES).requires_input is True


# ---------------------------------------------------------------- driver 2

def test_quality_improvement_follows_the_published_formula():
    # 10,000 x 0.02 x 0.5 x 400 = 40,000
    driver = quality_improvement(QUALITY, ERROR_COSTS)
    assert driver.amount == pytest.approx(40_000)


def test_an_error_class_with_no_published_cost_requires_input():
    driver = quality_improvement(QUALITY | {"error_class": "novel"}, ERROR_COSTS)
    assert driver.requires_input is True
    assert "novel" in driver.note


@pytest.mark.parametrize("field,value", [("error_rate", 1.5), ("expected_reduction", -0.1)])
def test_a_rate_outside_zero_to_one_is_malformed(field, value):
    assert quality_improvement(QUALITY | {field: value}, ERROR_COSTS).requires_input is True


# ---------------------------------------------------------------- driver 3

def test_compliance_reduction_is_qualitative_by_default():
    driver = compliance_reduction(sensitivity_flags=["health data", "regulated"])
    assert driver.amount == 0
    assert driver.qualitative is True
    assert driver.requires_input is False, "qualitative is a complete answer, not a gap"


def test_a_regulatory_flag_alone_never_produces_a_number():
    """CR-22 and FR-37 say so outright: a fine value inferred from the presence of a flag is
    fabricated, however plausible it looks next to the other two drivers."""
    driver = compliance_reduction(sensitivity_flags=["regulated", "financial"])
    assert driver.amount == 0


def test_a_cited_avoided_cost_is_quantified():
    driver = compliance_reduction(sensitivity_flags=["regulated"],
                                  cited_avoided_cost=250_000,
                                  citation="DoH circular 2026/14, s.4")
    assert driver.amount == 250_000
    assert driver.qualitative is False


def test_an_avoided_cost_without_a_citation_is_refused():
    with pytest.raises(BenefitError) as e:
        compliance_reduction(sensitivity_flags=["regulated"], cited_avoided_cost=250_000)
    assert "citation" in str(e.value).lower()


# ---------------------------------------------------------------- the financial summary

def test_the_financial_summary_follows_the_published_formulas():
    drivers = [operational_efficiency(EFFORT, RATES), quality_improvement(QUALITY, ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    summary = financial_summary(drivers, build_cost=200_000, monthly_run_cost=5_000)
    assert summary.annual_benefit == pytest.approx(120_000, rel=1e-3)
    assert summary.year_one_investment == pytest.approx(260_000)
    # payback = investment / monthly net benefit = 260,000 / (120,000/12 - 5,000)
    assert summary.payback_months == pytest.approx(260_000 / 5_000, rel=1e-3)
    # (3 x 120,000 - 260,000) / 260,000
    assert summary.three_year_roi == pytest.approx((360_000 - 260_000) / 260_000, rel=1e-3)


def test_only_three_drivers_are_admitted_into_the_roi():
    """CR-22b: the schema admits three driver fields only. A fourth is not a richer case, it is an
    incomparable one."""
    drivers = [operational_efficiency(EFFORT, RATES)] * 4
    with pytest.raises(BenefitError):
        financial_summary(drivers, build_cost=1, monthly_run_cost=1)


def test_a_benefit_that_never_repays_reports_no_payback_rather_than_a_negative_one():
    drivers = [compliance_reduction(sensitivity_flags=[])] * 3
    summary = financial_summary(drivers, build_cost=200_000, monthly_run_cost=5_000)
    assert summary.payback_months is None


def test_the_summary_carries_every_requires_input_marker_forward():
    drivers = [operational_efficiency([], RATES), quality_improvement(QUALITY, ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    summary = financial_summary(drivers, build_cost=1_000, monthly_run_cost=100)
    assert summary.requires_input


# ---------------------------------------------------------------- the recommendation

def _clean_summary():
    drivers = [operational_efficiency(EFFORT, RATES), quality_improvement(QUALITY, ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    return financial_summary(drivers, build_cost=100_000, monthly_run_cost=2_000)


def test_a_clean_case_that_repays_recommends_proceed():
    assert recommend(_clean_summary()).verdict == Recommendation.PROCEED


def test_proceed_is_unavailable_while_a_requires_input_marker_remains():
    """FR-37d and OA-9. The case can still recommend proceed WITH CONDITIONS — it cannot recommend
    proceed."""
    drivers = [operational_efficiency([], RATES), quality_improvement(QUALITY, ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    summary = financial_summary(drivers, build_cost=100_000, monthly_run_cost=2_000)
    out = recommend(summary)
    assert out.verdict == Recommendation.PROCEED_WITH_CONDITIONS
    assert out.gate_conditions


def test_an_open_readiness_condition_also_blocks_a_plain_proceed():
    out = recommend(_clean_summary(), open_conditions=["gate B closes 2026-10-31"])
    assert out.verdict == Recommendation.PROCEED_WITH_CONDITIONS
    assert any("gate B" in c for c in out.gate_conditions)


def test_an_incomplete_benefit_side_is_not_deferred_on_the_ratio_it_produces():
    """The precedence that matters. A requires-input marker understates the benefit — the missing
    figure can only raise it — so an ROI computed around the gap is not a basis for rejecting the
    use case. Deferring here would kill a case on a number nobody had finished."""
    drivers = [operational_efficiency([], RATES),          # marker: benefit understated
               quality_improvement(QUALITY, ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    summary = financial_summary(drivers, build_cost=500_000, monthly_run_cost=20_000)
    assert summary.three_year_roi < 0, "on the figures present, this looks like a loser"
    assert recommend(summary).verdict == Recommendation.PROCEED_WITH_CONDITIONS


def test_a_design_that_does_not_repay_is_deferred_and_that_is_a_correct_outcome():
    drivers = [compliance_reduction(sensitivity_flags=[])] * 3
    summary = financial_summary(drivers, build_cost=5_000_000, monthly_run_cost=90_000)
    assert recommend(summary).verdict == Recommendation.DEFER


def test_every_gate_condition_reaches_the_approvals_section_rather_than_the_working():
    """CR-22a: a requires-input marker is surfaced as a gate condition, never left in the working."""
    drivers = [operational_efficiency([], RATES), quality_improvement([], ERROR_COSTS),
               compliance_reduction(sensitivity_flags=[])]
    summary = financial_summary(drivers, build_cost=1_000, monthly_run_cost=10)
    out = recommend(summary)
    assert len(out.gate_conditions) >= 2
