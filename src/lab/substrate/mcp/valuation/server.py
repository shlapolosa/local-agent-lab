"""valuation-mcp — steps 23 and 24, the FINANCIAL derivations, as governed tools.

A separate service from `decision-mcp` for the reason the framework splits them: the artifacts
behind these two tools have a different OWNER and a different release cadence. The price sheet, the
role rate registry, the cost-per-error table and the delegation-of-authority thresholds belong to
finance; the guardrail set and the criticality taxonomy belong to architecture governance. Re-
releasing one must not mean redeploying the service that serves the other.

**Everything here refuses rather than rounding.** That is not caution for its own sake — a
financial derivation is read by somebody deciding whether to spend money, and every one of these
refusals exists because the alternative produces a number that is confident and wrong:

* a resource matching no price line raises a GAP FLAG, never a proxy price (FR-32). A proxy is
  indistinguishable from a real figure once it is inside a total, and no reader downstream could
  tell them apart;
* a build cost states its provenance — vendor quote, budget bucket or estimate (FR-34). An approver
  reads "quote" as a number somebody will be held to;
* a driver nobody supplied inputs for is `requires_input`, which is NOT zero. "Nobody supplied what
  this needs" and "this is worth nothing" produce the same figure and mean opposite things;
* every answer names the sheet VERSION it was costed against (CR-23, CR-24), because an estimate
  against a superseded sheet is wrong in a way nothing downstream can see. The seeded sheet is
  marked illustrative and says so in its own caveat.

The arithmetic itself is `lab.core.usecase.{cost,benefit}` — pure, offline, and shared with the
workload gates, because a workload may never import the substrate and the sums must not exist twice.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

from lab.core.usecase import benefit, cost
from lab.platform import config
from lab.platform.contracts import ValuationTools
from lab.substrate.mcp import pinned
from lab.substrate.mcpserver import LabServer, span

SERVICE = "valuation-mcp"
server = LabServer(SERVICE, config.VALUATION_MCP_PORT)

#: The finance artifact the cost join reads, by the key `pinned.rules` returns it under. Held
#: equal to `ValuationTools.READS` by a test, as decision-mcp's table is.
RULES = {"component_prices": ("component-prices", "component-price")}

#: The reference registries, read HERE rather than passed in by a caller — for the same reason the
#: price sheet is: they are finance's artifacts, at finance's release cadence, and a caller
#: supplying its own rate card would make two submissions incomparable while both looked priced.
#: A caller may still override for a what-if; the default is the tenant's published values.
def _registry(supplied, default: dict) -> dict:
    return dict(supplied) if supplied else dict(default)


def _three_point(point: cost.ThreePoint) -> dict:
    """A range, carried rather than collapsed (FR-31). The spread IS the estimate's only honest
    statement about its own uncertainty, and a single expected figure discards it."""
    return {"low": point.low, "expected": point.expected, "high": point.high}


def _driver(driver: benefit.Driver) -> dict:
    return {"name": driver.name, "annual_value": driver.amount, "basis": driver.basis,
            "note": driver.note, "requires_input": driver.requires_input,
            "qualitative": driver.qualitative}


@server.tool()
def valuation_cost(component_ids: list[str], envelope: str = "expected",
                   volume: dict | None = None, build_amount: float = 0.0,
                   build_provenance: str = "", design_version: str = "", pin_id: str = "",
                   run_id: str = "", process: str = "", field: str = "") -> dict:
    """Step 23 — the cost model for a composed design: a JOIN, not an estimate.

    `component_ids` are the catalogue ids step 21 selected (G04: a design admits components by
    identity); `envelope` follows the confirmed criticality class; `volume` is what intake
    captured (`runs_per_month`, `users`, `records`). Every catalogue variant the envelope may buy
    is priced, positioned in its band by the captured volume — a driven line with no captured
    volume is EXCLUDED and named, never guessed; a component with no line at this envelope is a
    gap flag, never a proxy price. Priced against the component-price catalogue at the caller's
    PINNED version (CR-23/24), through the governed corpus, attributed to the derived field.

    `build_provenance` must be a vendor quote, a budget bucket or an estimate; omit `build_amount`
    entirely and the build cost is declared MISSING rather than read as zero.
    """
    built = None
    if build_amount:
        try:
            built = cost.build_cost(build_amount, cost.Provenance(build_provenance))
        except ValueError as exc:
            raise ToolError(
                f"{build_provenance!r} is not a provenance this tool will record; a build cost "
                f"must state itself as one of "
                f"{[p.value for p in cost.Provenance]} — an estimate presented as a vendor quote "
                f"is read as a number somebody will be held to") from exc
    rules, provenance = pinned.rules(server.reference(), pin_id, run_id, process, field,
                                     table=RULES, needs=("component_prices",),
                                     reads=ValuationTools.READS)
    sheet_version = next((v["version"] for v in provenance["versions"]
                          if v["artifact_id"] == RULES["component_prices"][0]), "")
    try:
        model = cost.cost_model(list(component_ids or ()), cost.catalogue(rules["component_prices"]),
                                envelope=envelope, volume=dict(volume or {}), build=built,
                                design_version=design_version, sheet_version=sheet_version)
    except cost.CostError as exc:
        raise ToolError(str(exc)) from exc

    # Counts and shapes only. A year-one investment on a span is a budget disclosed to whoever can
    # open the trace, and this lab's collector authenticates nobody.
    span().set_attributes({"valuation.cost.lines": len(model.lines),
                           "valuation.cost.gaps": len(model.gap_flags),
                           "valuation.cost.open": len(model.requires_input)})
    return {"lines": [{"component": line.component, "component_name": line.component_name,
                       "variant": line.variant, "unit": line.unit,
                       "monthly": _three_point(line.monthly),
                       "volume_driver": line.volume_driver, "volume": line.volume,
                       "source_line": line.source_line, "note": line.note}
                      for line in model.lines],
            "monthly": _three_point(model.monthly),
            "year_one": _three_point(model.year_one),
            "capex": model.capex,
            "envelope": model.envelope,
            "gap_flags": list(model.gap_flags),
            "build": ({"amount": model.build.amount, "provenance": str(model.build.provenance),
                       "basis": model.build.basis} if model.build else None),
            "requires_input": list(model.requires_input),
            "sheet_version": model.sheet_version,
            "design_version": model.design_version,
            "caveat": model.caveat,
            "rules_source": provenance}


@server.tool()
def valuation_benefit(effort: list[dict] | None = None, role_rates: dict | None = None,
                      quality_baseline: dict | None = None, error_costs: dict | None = None,
                      sensitivity_flags: list[str] | None = None,
                      cited_avoided_cost: float | None = None, citation: str = "",
                      build_cost: float = 0.0, monthly_run_cost: float = 0.0,
                      data_fully_digital: bool = True,
                      open_conditions: list[str] | None = None) -> dict:
    """Step 24 — the three benefit drivers, the financial summary and the recommendation.

    Exactly three drivers enter the ROI: operational efficiency, quality and accuracy, and
    compliance and risk reduction. Value identified outside them is captured qualitatively and
    stated as excluded rather than added — a fourth driver invented for one submission makes that
    submission incomparable with every other one in the portfolio.

    A driver whose inputs are absent comes back `requires_input`, and that marker travels all the
    way to the verdict: `proceed` is unavailable while one is open (FR-37d, OA-9), and the case is
    NOT deferred on it either, because the missing figure can only raise the benefit.
    """
    rates = _registry(role_rates, config.ROLE_RATES)
    costs = _registry(error_costs, config.ERROR_COSTS)
    try:
        drivers = [
            benefit.operational_efficiency(effort or [], rates,
                                           data_fully_digital=data_fully_digital),
            benefit.quality_improvement(quality_baseline or {}, costs),
            benefit.compliance_reduction(sensitivity_flags=sensitivity_flags or [],
                                         cited_avoided_cost=cited_avoided_cost,
                                         citation=citation),
        ]
        summary = benefit.financial_summary(drivers, build_cost=build_cost,
                                            monthly_run_cost=monthly_run_cost)
        outcome = benefit.recommend(summary, open_conditions=open_conditions or [])
    except benefit.BenefitError as exc:
        raise ToolError(str(exc)) from exc

    span().set_attributes({"valuation.benefit.drivers": len(drivers),
                           "valuation.benefit.rates_configured": bool(rates),
                           "valuation.benefit.open": len(summary.requires_input),
                           "valuation.benefit.repays": summary.payback_months is not None})
    return {"drivers": [_driver(d) for d in drivers],
            "summary": {"annual_benefit": summary.annual_benefit,
                        "year_one_investment": summary.year_one_investment,
                        "payback_months": summary.payback_months,
                        "three_year_roi": summary.three_year_roi,
                        "requires_input": list(summary.requires_input)},
            "recommendation": {"verdict": str(outcome.verdict), "rationale": outcome.rationale,
                               "gate_conditions": list(outcome.gate_conditions)},
            # Said out loud for the same reason `decision_mcp` names its rules source: a driver
            # that is `requires_input` because nobody configured a registry is a DEPLOYMENT gap,
            # and a reader told only "no rate for 'nurse'" would go looking for the nurse.
            "registries": {"role_rates": bool(rates), "error_costs": bool(costs)}}


if __name__ == "__main__":
    server.serve()
