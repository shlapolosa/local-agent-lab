"""valuation-mcp — cost and benefit as governed tools.

The arithmetic is tested in `tests/unit/core/usecase`. What is tested here is what the SERVER adds,
and all of it is about refusing to produce a confident number: a component with no catalogue line
is a gap flag and never a proxy price; a build cost states its provenance; a driver nobody supplied
inputs for is `requires_input`; every answer names the catalogue VERSION it was costed against,
and reads it under the caller's PIN — there is no packaged sheet to fall back on.
"""
import pytest
from fastmcp.exceptions import ToolError

from fixtures.reference import FakeReferenceLibrary
from fixtures.usecase_corpus import corpus, seeded
from lab.platform.contracts import ValuationTools
from lab.substrate.mcp.valuation import server as S

_PIN: dict = {}


@pytest.fixture(autouse=True)
def governed_pin():
    library = FakeReferenceLibrary([seeded(a) for a in ValuationTools.READS])
    with S.server.container.reference.override(library):
        pin = library.pin()
        _PIN.clear()
        _PIN.update(pin_id=pin.pin_id, run_id="wfr-t", process="use_case_design", field="cost")
        yield library


def pinned(**over):
    return {**_PIN, **over}


def _component(name: str) -> str:
    return next(r["component"] for r in corpus()["component-prices"] if r["component_name"] == name)


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
    from lab.platform.contracts import DecisionTools
    assert ValuationTools.SERVER != DecisionTools.SERVER
    assert not (ValuationTools.names() & DecisionTools.names())


def test_the_rules_table_reads_exactly_what_the_contract_says_it_reads():
    assert {a for a, _ in S.RULES.values()} == set(ValuationTools.READS)


# ---------------------------------------------------------------- step 23

def test_a_cost_model_joins_the_selected_components_onto_the_pinned_catalogue():
    out = S.valuation_cost(component_ids=[_component("Key Vault"), _component("Compute hosts")],
                           envelope="expected", volume={"runs_per_month": 6000}, **pinned())
    assert {l["component_name"] for l in out["lines"]} == {"Key Vault", "Compute hosts"}
    assert out["monthly"]["expected"] > 0 and out["year_one"]["expected"] >= out["monthly"]["expected"]
    assert out["rules_source"]["kind"] == "governed corpus"
    assert out["sheet_version"] == "v0.27", "the catalogue version the join read, from the pin"


def test_a_component_with_no_catalogue_line_is_a_gap_flag_and_never_a_proxy_price():
    out = S.valuation_cost(component_ids=["cmp-nobody-priced"], **pinned())
    assert out["gap_flags"] == ["cmp-nobody-priced"] and out["lines"] == []
    assert any("gap flag" in r for r in out["requires_input"])


def test_a_driven_line_with_no_captured_volume_is_excluded_and_named_not_guessed():
    out = S.valuation_cost(component_ids=[_component("App Insights")], envelope="expected",
                           volume={}, **pinned())
    assert out["lines"] == [] and any("runs_per_month" in r for r in out["requires_input"])


def test_a_derivation_with_no_pin_refuses_and_says_how_to_get_one():
    with pytest.raises(ToolError) as e:
        S.valuation_cost(component_ids=[_component("Key Vault")])
    assert "reference_pin" in str(e.value) and "component-prices" in str(e.value)


def test_a_build_cost_must_say_whether_it_is_a_quote_or_an_estimate():
    quoted = S.valuation_cost(component_ids=[_component("Key Vault")], build_amount=50000,
                              build_provenance="vendor quote", **pinned())
    assert quoted["build"]["provenance"] == "vendor quote"
    with pytest.raises(ToolError) as e:
        S.valuation_cost(component_ids=[_component("Key Vault")], build_amount=50000,
                         build_provenance="a number somebody mentioned", **pinned())
    assert "vendor quote" in str(e.value)


def test_a_missing_build_cost_is_declared_rather_than_read_as_zero():
    out = S.valuation_cost(component_ids=[_component("Key Vault")], **pinned())
    assert out["build"] is None and any("build cost" in r for r in out["requires_input"])
    assert out["year_one"]["expected"] == out["monthly"]["expected"] * 12


def test_an_unknown_envelope_refuses():
    with pytest.raises(ToolError):
        S.valuation_cost(component_ids=[_component("Key Vault")], envelope="huge", **pinned())


# ---------------------------------------------------------------- step 24

def _benefit(**kw):
    args = {"effort": [{"role": "nurse", "headcount": 4, "frequency_per_week": 20,
                        "current_minutes": 30, "expected_minutes": 10}],
            "role_rates": {"nurse": 120.0},
            "build_cost": 50000.0, "monthly_run_cost": 1000.0}
    return S.valuation_benefit(**(args | kw))
