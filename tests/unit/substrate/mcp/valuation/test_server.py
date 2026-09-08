"""valuation-mcp — cost and benefit as governed tools.

The arithmetic is tested in `tests/unit/core/usecase`. What is tested here is what the SERVER adds,
and all of it is about refusing to produce a confident number:

* a resource with no price line raises a GAP FLAG and never a proxy price — a proxy is
  indistinguishable from a real figure once it is inside a total;
* a build cost states its provenance, and a quote is not an estimate;
* a driver nobody supplied inputs for is `requires_input`, which is not the same as zero;
* every answer names the sheet VERSION it was costed against, because an estimate against a
  superseded sheet is wrong in a way nothing downstream can see.
"""
import pytest
from fastmcp.exceptions import ToolError

from lab.platform.contracts import ValuationTools
from lab.substrate.mcp.valuation import server as S

RESOURCES = ["Container Apps", "AI Search (Basic)"]


# ---------------------------------------------------------------- the contract

def test_the_server_registers_exactly_the_catalogue_it_declares():
    import asyncio
    import inspect
    tools = S.server.mcp.list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    registered = {t.name for t in (tools.values() if isinstance(tools, dict) else tools)}
    assert registered == ValuationTools.names()


def test_nothing_here_writes():
    assert not hasattr(ValuationTools, "WRITE")


def test_it_is_a_separate_server_from_the_architecture_derivations():
    """The split is by artifact OWNER: finance releases the price sheet, architecture governance
    releases the guardrails, and neither release may require the other's redeploy."""
    from lab.platform.contracts import DecisionTools
    assert ValuationTools.SERVER != DecisionTools.SERVER
    assert not (ValuationTools.names() & DecisionTools.names())


# ---------------------------------------------------------------- step 23

def test_a_cost_model_prices_the_lines_the_design_switched_on():
    out = S.valuation_cost(resources=["Container Apps"])
    assert out["lines"] and out["monthly"]["expected"] >= 0
    assert out["year_one"]["expected"] >= out["monthly"]["expected"]


def test_a_resource_with_no_price_line_is_a_gap_flag_and_never_a_proxy_price():
    out = S.valuation_cost(resources=["a service nobody has priced"])
    assert out["gap_flags"] == ["a service nobody has priced"]
    assert any("gap flag" in r for r in out["requires_input"])


def test_the_estimate_names_the_sheet_version_it_was_costed_against():
    out = S.valuation_cost(resources=["Container Apps"])
    assert out["sheet_version"]
    assert out["caveat"], "the seeded sheet is marked illustrative and must say so"


def test_a_build_cost_must_say_whether_it_is_a_quote_or_an_estimate():
    """FR-34. An approver reads "quote" as a number somebody will be held to."""
    quoted = S.valuation_cost(resources=["Container Apps"], build_amount=50000,
                              build_provenance="vendor quote")
    assert quoted["build"]["provenance"] == "vendor quote"
    with pytest.raises(ToolError) as e:
        S.valuation_cost(resources=["Container Apps"], build_amount=50000,
                         build_provenance="a number somebody mentioned")
    assert "vendor quote" in str(e.value)


def test_a_missing_build_cost_is_declared_rather_than_read_as_zero():
    out = S.valuation_cost(resources=["Container Apps"])
    assert out["build"] is None
    assert any("build cost" in r for r in out["requires_input"])
    assert out["year_one"]["expected"] == out["monthly"]["expected"] * 12


# ---------------------------------------------------------------- step 24

def _benefit(**kw):
    args = {"effort": [{"role": "nurse", "headcount": 4, "frequency_per_week": 20,
                        "current_minutes": 30, "expected_minutes": 10}],
            "role_rates": {"nurse": 120.0},
            "build_cost": 50000.0, "monthly_run_cost": 1000.0}
    return S.valuation_benefit(**(args | kw))


def test_the_benefit_case_carries_the_summary_and_a_verdict():
    out = _benefit()
    assert out["summary"]["annual_benefit"] > 0
    assert out["recommendation"]["verdict"] in ("proceed", "proceed with conditions", "defer")
    assert out["recommendation"]["rationale"]


def test_a_driver_nobody_supplied_inputs_for_is_declared_not_scored_as_zero():
    """"Nobody supplied what this needs" and "this is worth nothing" produce the same number and
    mean opposite things — only one of them should reach a funding decision."""
    out = _benefit(effort=[], role_rates={})
    efficiency = [d for d in out["drivers"] if "efficiency" in d["name"]][0]
    assert efficiency["requires_input"]
    assert efficiency["annual_value"] == 0


def test_an_incomplete_benefit_side_never_produces_a_confident_proceed():
    """The understatement runs one way: a case with an unsupplied driver is worth AT LEAST what was
    computed, so the honest answer is conditions, never a defer dressed up as arithmetic."""
    out = _benefit(effort=[], role_rates={}, build_cost=500000.0)
    assert out["recommendation"]["verdict"] == "proceed with conditions"


def test_a_role_with_no_rate_is_declared_rather_than_priced_at_the_nearest_rate():
    out = _benefit(role_rates={"clinician": 300.0})
    efficiency = [d for d in out["drivers"] if "efficiency" in d["name"]][0]
    assert efficiency["requires_input"]


def test_the_authority_the_decision_needs_is_named_with_the_number():
    """26b routes by delegated authority, and the routing is only as good as the figure it reads."""
    out = _benefit()
    assert out["summary"]["year_one_investment"] > 0


# ---------------------------------------------------------------- what a span may carry

def test_no_span_attribute_carries_a_figure_or_a_role(monkeypatch):
    """Counts and shapes only. Spans reach a collector this lab does not authenticate, and a
    year-one investment on one is a budget disclosed to whoever can open the trace."""
    recorded = {}

    class Span:
        def set_attribute(self, k, v): recorded[k] = v
        def set_attributes(self, kv): recorded.update(kv)

    monkeypatch.setattr(S, "span", lambda: Span())
    S.valuation_cost(resources=["Container Apps"], build_amount=50000,
                     build_provenance="vendor quote")
    _benefit()
    assert recorded
    for key, value in recorded.items():
        assert isinstance(value, (int, bool)), f"{key} carries {value!r}"
        assert "cost" not in key.split(".")[-1] or isinstance(value, int)
    assert not any(k.endswith(("investment", "benefit", "amount", "rate")) for k in recorded)
