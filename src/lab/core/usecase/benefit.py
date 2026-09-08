"""Step 24 — benefit drivers, financial summary and the recommendation.

Published formulas, so a deviation is a defect and not a variance. What actually needs care here is
the refusal to produce a number:

* **CR-22** — no benefit or cost figure is fabricated. Every figure traces to a published formula
  over intake data, or a cited avoided cost, or it is marked `requires_input`.
* **CR-22a** — a requires-input marker becomes a GATE CONDITION in the approvals section. It is
  never resolved by estimation and never left in the working, where a reader would not find it.
* **CR-22b** — exactly three drivers enter the ROI. A fourth does not make a richer case, it makes
  an incomparable one, and comparability is the whole reason the structure is fixed.
* **FR-37** — driver 3 is qualitative unless a specific avoided cost is CITED. A fine value
  inferred from a regulatory flag is fabricated however plausible it looks beside the other two.

The distinction the code keeps everywhere: a driver worth zero and a driver nobody supplied data
for are different answers. Only one of them can be fixed by asking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

__all__ = [
    "BenefitError", "Driver", "FinancialSummary", "Recommendation", "RecommendationOutcome",
    "WEEKS_PER_YEAR", "YEAR_ONE_DISCOUNT",
    "compliance_reduction", "financial_summary", "operational_efficiency", "quality_improvement",
    "recommend",
]

#: The published constant in driver 1's formula: "headcount × frequency per week × 50".
WEEKS_PER_YEAR = 50

#: Driver 1 carries a Year-1 discount "where the underlying data is not fully digital" — the saving
#: is real but not realised in the first year while the data is still being cleaned up.
YEAR_ONE_DISCOUNT = 0.5

#: CR-22b, as a number rather than a hope.
MAX_DRIVERS = 3

_EFFORT_FIELDS = ("headcount", "frequency_per_week", "current_minutes", "expected_minutes")
_QUALITY_FIELDS = ("current_volume", "error_rate", "expected_reduction", "error_class")


class BenefitError(ValueError):
    """A figure was asked for that cannot honestly be produced."""


class Recommendation(StrEnum):
    PROCEED = "proceed"
    PROCEED_WITH_CONDITIONS = "proceed with conditions"
    DEFER = "defer"


@dataclass(frozen=True)
class Driver:
    """One of the three admitted benefit drivers.

    `requires_input` is not "worth nothing" — it is "nobody supplied what this needs", and it
    travels all the way to the approvals section rather than being smoothed into a zero."""
    name: str
    amount: float = 0.0
    basis: str = ""
    note: str = ""
    requires_input: bool = False
    qualitative: bool = False

    def __post_init__(self) -> None:
        if self.requires_input and self.amount:
            raise BenefitError(f"{self.name}: a driver that requires input cannot carry a figure")


def _number(value: Any) -> float | None:
    """A usable number, or None. A bool is not a number here — `True` as a headcount is malformed
    data, and Python would otherwise quietly read it as 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ---------------------------------------------------------------- driver 1

def operational_efficiency(effort: Sequence[Mapping[str, Any]], rates: Mapping[str, float],
                           *, data_fully_digital: bool = True) -> Driver:
    """annual hours saved = headcount × frequency per week × 50 × (current − expected) ÷ 60,
    then × the role's hourly rate from the registry."""
    name = "operational efficiency"
    if not effort:
        return Driver(name, requires_input=True,
                      note="no effort table was captured at intake; driver 1 cannot be computed")

    total = 0.0
    for row in effort:
        role = str(row.get("role", "")).strip()
        values = {f: _number(row.get(f)) for f in _EFFORT_FIELDS}
        missing = [f for f, v in values.items() if v is None]
        if missing or not role:
            return Driver(name, requires_input=True,
                          note=f"effort row {role or '(unnamed role)'} is missing {missing or ['role']}")
        if values["expected_minutes"] > values["current_minutes"]:            # type: ignore[operator]
            return Driver(name, requires_input=True,
                          note=f"effort row {role}: expected minutes exceed current minutes, "
                               f"which is a saving in the wrong direction")
        rate = rates.get(role)
        if rate is None:
            return Driver(name, requires_input=True,
                          note=f"no hourly rate for {role!r} in the role rate registry — a rate is "
                               f"never assumed")
        hours = (values["headcount"] * values["frequency_per_week"] * WEEKS_PER_YEAR
                 * (values["current_minutes"] - values["expected_minutes"]) / 60)   # type: ignore[operator]
        total += hours * float(rate)

    if data_fully_digital:
        return Driver(name, amount=total, basis="published formula over the intake effort table")
    return Driver(name, amount=total * (1 - YEAR_ONE_DISCOUNT),
                  basis=f"published formula with the Year-1 discount of "
                        f"{YEAR_ONE_DISCOUNT:.0%} applied — the underlying data is not fully digital")


# ---------------------------------------------------------------- driver 2

def quality_improvement(baseline: Mapping[str, Any] | Sequence[Any],
                        error_costs: Mapping[str, float]) -> Driver:
    """annual quality saving = current volume × error rate × expected reduction × cost per error."""
    name = "quality and accuracy"
    if not baseline or not isinstance(baseline, Mapping):
        return Driver(name, requires_input=True,
                      note="no quality baseline was captured at intake; driver 2 cannot be computed")

    values = {f: baseline.get(f) for f in _QUALITY_FIELDS}
    numbers = {f: _number(values[f]) for f in ("current_volume", "error_rate", "expected_reduction")}
    missing = [f for f, v in numbers.items() if v is None]
    if missing:
        return Driver(name, requires_input=True, note=f"quality baseline is missing {missing}")
    for rate_field in ("error_rate", "expected_reduction"):
        if not 0 <= numbers[rate_field] <= 1:                       # type: ignore[operator]
            return Driver(name, requires_input=True,
                          note=f"{rate_field} of {values[rate_field]!r} is not a proportion "
                               f"between 0 and 1")

    error_class = str(values["error_class"] or "").strip()
    cost = error_costs.get(error_class)
    if cost is None:
        return Driver(name, requires_input=True,
                      note=f"no published cost for error class {error_class!r} — a cost per error "
                           f"is never assumed")
    amount = (numbers["current_volume"] * numbers["error_rate"]                 # type: ignore[operator]
              * numbers["expected_reduction"] * float(cost))                   # type: ignore[operator]
    return Driver(name, amount=amount,
                  basis=f"published formula against the cost-per-error reference for "
                        f"{error_class!r}")


# ---------------------------------------------------------------- driver 3

def compliance_reduction(*, sensitivity_flags: Sequence[str],
                         cited_avoided_cost: float | None = None,
                         citation: str = "") -> Driver:
    """Qualitative by default; quantified ONLY against a specific cited avoided cost.

    The sensitivity flags anchor the qualitative statement — they never produce a figure. A number
    inferred from "this is regulated" is the fabrication CR-22 exists to stop, and it is the most
    tempting one in the whole model because it sits beside two real figures.
    """
    name = "compliance and risk reduction"
    if cited_avoided_cost is None:
        return Driver(name, qualitative=True,
                      basis=f"qualitative — anchored on the sensitivity flags "
                            f"{list(sensitivity_flags)}; no avoided cost was cited at intake")
    if not citation.strip():
        raise BenefitError(
            "an avoided cost of "
            f"{cited_avoided_cost} was supplied with no citation. Driver 3 is quantified only "
            "against a specific cited avoided fine or audit-hour reduction; a figure inferred from "
            "a regulatory flag alone is fabricated.")
    return Driver(name, amount=float(cited_avoided_cost),
                  basis=f"cited avoided cost — {citation}")


# ---------------------------------------------------------------- the summary

@dataclass(frozen=True)
class FinancialSummary:
    annual_benefit: float
    year_one_investment: float
    payback_months: float | None
    three_year_roi: float
    drivers: tuple[Driver, ...] = ()
    requires_input: tuple[str, ...] = ()


def financial_summary(drivers: Sequence[Driver], *, build_cost: float,
                      monthly_run_cost: float) -> FinancialSummary:
    """Total annual benefit, Year-1 investment, payback in months, three-year ROI multiple."""
    if len(drivers) > MAX_DRIVERS:
        raise BenefitError(
            f"{len(drivers)} drivers were supplied; exactly {MAX_DRIVERS} enter the ROI. Value "
            f"identified outside them is captured qualitatively and stated as excluded.")

    annual_benefit = sum(d.amount for d in drivers)
    investment = float(build_cost) + 12 * float(monthly_run_cost)
    monthly_net = annual_benefit / 12 - float(monthly_run_cost)
    payback = investment / monthly_net if monthly_net > 0 else None
    roi = (3 * annual_benefit - investment) / investment if investment else 0.0
    return FinancialSummary(
        annual_benefit=annual_benefit, year_one_investment=investment,
        payback_months=payback, three_year_roi=roi, drivers=tuple(drivers),
        requires_input=tuple(f"{d.name}: {d.note}" for d in drivers if d.requires_input))


# ---------------------------------------------------------------- the recommendation

@dataclass(frozen=True)
class RecommendationOutcome:
    verdict: Recommendation
    rationale: str
    gate_conditions: tuple[str, ...] = field(default_factory=tuple)


def recommend(summary: FinancialSummary, *,
              open_conditions: Sequence[str] = ()) -> RecommendationOutcome:
    """Proceed, proceed with conditions, or defer.

    Proceed is unavailable while any requires-input marker or open readiness condition remains
    (FR-37d, OA-9) — and every one of them is listed as a gate condition, because the approver has
    to see what is still open rather than find it in the working.
    """
    conditions = tuple(summary.requires_input) + tuple(open_conditions)
    repays = summary.payback_months is not None and summary.three_year_roi > 0

    # Order matters, and this is the subtle one. A requires-input marker means the BENEFIT side is
    # understated — the missing figure can only ever raise it. Deferring on that ROI would reject a
    # use case on a number we already know is incomplete, so an unresolved marker outranks the
    # repayment test. An open READINESS condition is different: it does not touch the arithmetic,
    # so a case that genuinely does not repay still defers.
    if conditions and summary.requires_input:
        return RecommendationOutcome(
            Recommendation.PROCEED_WITH_CONDITIONS,
            "figures are still open, so the return cannot yet be judged — the missing drivers can "
            "only raise the benefit, and deferring on an incomplete benefit side would reject the "
            "use case on a number nobody has finished",
            conditions)
    if not repays:
        return RecommendationOutcome(
            Recommendation.DEFER,
            "the design does not repay its Year-1 investment over the appraisal horizon — a sound "
            "design that does not repay is a correct outcome and a decision not to build",
            conditions)
    if conditions:
        return RecommendationOutcome(
            Recommendation.PROCEED_WITH_CONDITIONS,
            "the case repays, but figures or readiness conditions remain open and must close "
            "before the investment is committed",
            conditions)
    return RecommendationOutcome(
        Recommendation.PROCEED,
        f"every figure carries a source, and the case repays in "
        f"{summary.payback_months:.1f} months", ())
