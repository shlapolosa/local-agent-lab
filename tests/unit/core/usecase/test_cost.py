"""Step 23 — the cost JOIN. Components in, priced lines out, every refusal named.

Nothing here is a judgement: the catalogue says which variants an envelope may buy and what
drives a line, intake says the volume, the criticality class says the envelope. What is tested is
that the join is exact and that every place it cannot be exact says so rather than rounding.
"""
import pytest

from lab.core.usecase.cost import (
    CostError,
    PriceLine,
    Provenance,
    ThreePoint,
    build_cost,
    catalogue,
    cost_model,
    envelope_for,
    parse_estimate,
    position,
    volume_from_intake,
    year_one_total,
)


def row(**over):
    base = {"component": "cmp-a", "component_name": "Compute hosts", "variant": "container-apps",
            "unit": "vCPU-hour", "opex_low": "100.0", "opex_expected": "250.0", "opex_high": "400.0",
            "capex_once": "", "envelope_in": ["low", "expected", "high"],
            "volume_driver": "runs_per_month", "expected_at": "5000", "high_at": "50000",
            "source_line": "Container Apps", "note": "scales to zero"}
    return {**base, **over}


FLAT = row(component="cmp-b", component_name="Key Vault", variant="standard", opex_low="20",
           opex_expected="20", opex_high="20", volume_driver="none", expected_at="0", high_at="0")
PROVISIONED = row(component="cmp-m", component_name="Foundry model catalog",
                  variant="frontier-provisioned", opex_low="9200", opex_expected="9200",
                  opex_high="9200", envelope_in=["high"], volume_driver="none",
                  expected_at="0", high_at="0")
SMALL = row(component="cmp-m", component_name="Foundry model catalog", variant="small-consumption",
            opex_low="500", opex_expected="1250", opex_high="2000", envelope_in=["low", "expected"])
CATALOGUE = catalogue([row(), FLAT, PROVISIONED, SMALL])


# ---------------------------------------------------------------- typed rows

def test_a_catalogue_row_becomes_numbers_once_and_a_list_column_is_read_either_way():
    line = PriceLine.from_row(row(envelope_in="low; expected"))
    assert line.opex == ThreePoint(100.0, 250.0, 400.0) and line.envelope_in == ("low", "expected")
    assert line.capex is None and line.expected_at == 5000.0


@pytest.mark.parametrize("bad", [row(opex_expected="two hundred"), row(envelope_in=["huge"]),
                                 row(volume_driver="tokens"), row(component=""),
                                 row(expected_at="0", high_at="0"),      # driven, no bands
                                 row(expected_at="9000", high_at="100")])
def test_a_malformed_row_refuses_the_catalogue_rather_than_costing_around_it(bad):
    with pytest.raises(CostError):
        catalogue([bad])


@pytest.mark.parametrize("text,low,high", [("~175", 175, 175), ("~100–400", 100, 400),
                                           ("~9,200", 9200, 9200), ("Included", 0, 0)])
def test_the_sheet_s_estimates_still_parse_for_the_catalogue_generator(text, low, high):
    assert (parse_estimate(text).low, parse_estimate(text).high) == (low, high)


# ---------------------------------------------------------------- the two upstream decisions

@pytest.mark.parametrize("criticality,envelope", [("routine", "low"), ("business-critical", "expected"),
                                                  ("safety-of-life", "high")])
def test_the_envelope_follows_the_confirmed_criticality_class(criticality, envelope):
    assert envelope_for(criticality) == envelope


def test_an_unknown_class_has_no_envelope():
    with pytest.raises(CostError):
        envelope_for("")


def test_volume_is_read_from_the_intake_group_a_person_filled_in():
    intake = {"Volume assumptions": {"value": "about 5,000 runs a month for 40 users; 120000 records"},
              "Investment": {"value": "budget bucket AED 250k"}}
    assert volume_from_intake(intake) == {"runs_per_month": 5000.0, "users": 40.0, "records": 120000.0}
    assert volume_from_intake({"Scale and demand": {"value": "users: 12"}}) == {"users": 12.0}, \
        "a renamed group must not switch cost off"
    assert volume_from_intake({}) == {} and volume_from_intake(None) == {}


@pytest.mark.parametrize("text,expected", [
    ("about 5k users and 12,000 runs a month", {"users": 5000.0, "runs_per_month": 12000.0}),
    ("roughly 1.5k records processed weekly", {"records": 1500.0}),
    ("2,000 runs per day", {"runs_per_month": 60000.0}),
    ("40 users, each making 20 requests a day", {"users": 40.0, "runs_per_month": 600.0}),
    ("we operate 12 clinics; users of the system are nurses", {}),
    ("1.2m records, 300 runs / week", {"records": 1200000.0, "runs_per_month": 1299.0}),
])
def test_volume_reads_the_way_a_business_person_writes_it(text, expected):
    """`k` multiplies, a period normalises to the month, and a number never pairs with a word
    across a clause — every one of these was a silent thousand-fold or thirty-fold error."""
    assert volume_from_intake({"Volume": {"value": text}}) == expected


# ---------------------------------------------------------------- positioning

def test_a_driven_line_is_placed_in_its_band_by_the_captured_volume():
    line = PriceLine.from_row(row())
    assert position(line, {"runs_per_month": 100}).expected == 100.0
    assert position(line, {"runs_per_month": 20000}).expected == 250.0
    assert position(line, {"runs_per_month": 90000}).expected == 400.0
    assert position(line, {"runs_per_month": 90000}).low == 100.0, "the range is carried through"


def test_a_driven_line_with_no_captured_volume_is_not_positioned_by_guess():
    assert position(PriceLine.from_row(row()), {}) is None


def test_a_flat_line_ignores_volume():
    assert position(PriceLine.from_row(FLAT), {}).expected == 20.0


# ---------------------------------------------------------------- the join

def test_the_model_prices_every_variant_the_envelope_may_buy():
    model = cost_model(["cmp-m", "cmp-b"], CATALOGUE, envelope="high", volume={}, build=None)
    assert [l.variant for l in model.lines] == ["frontier-provisioned", "standard"]
    assert model.monthly.expected == 9200 + 20
    low = cost_model(["cmp-m"], CATALOGUE, envelope="low", volume={"runs_per_month": 100}, build=None)
    assert [l.variant for l in low.lines] == ["small-consumption"], "provisioned is a high-volume buy"


def test_a_component_with_no_line_at_this_envelope_is_a_gap_flag_and_never_a_proxy_price():
    model = cost_model(["cmp-nope", "cmp-b"], CATALOGUE, envelope="expected", volume={}, build=None)
    assert model.gap_flags == ("cmp-nope",)
    assert model.monthly.expected == 20.0
    assert any("gap flag" in r for r in model.requires_input)


def test_a_driven_line_whose_volume_was_not_captured_is_excluded_and_named():
    model = cost_model(["cmp-a"], CATALOGUE, envelope="expected", volume={}, build=None)
    assert model.lines == () and model.monthly.expected == 0.0
    assert any("runs_per_month" in r and "excluded" in r for r in model.requires_input)


def test_the_selection_order_and_duplicates_do_not_change_the_total():
    a = cost_model(["cmp-a", "cmp-b", "cmp-a"], CATALOGUE, envelope="expected",
                   volume={"runs_per_month": 6000}, build=None)
    b = cost_model(["cmp-b", "cmp-a"], CATALOGUE, envelope="expected",
                   volume={"runs_per_month": 6000}, build=None)
    assert a.monthly == b.monthly == ThreePoint(120.0, 270.0, 420.0)


def test_capex_the_catalogue_does_not_carry_is_named_not_zeroed():
    model = cost_model(["cmp-b"], CATALOGUE, envelope="expected", volume={}, build=None)
    assert model.capex == 0.0 and any("capex" in r for r in model.requires_input)
    with_capex = cost_model(["cmp-c"], catalogue([row(component="cmp-c", capex_once="1500",
                                                       volume_driver="none")]),
                            envelope="expected", volume={}, build=None)
    assert with_capex.capex == 1500.0 and with_capex.year_one.expected == 1500 + 250 * 12


# ---------------------------------------------------------------- the build cost

def test_a_vendor_quote_is_recorded_as_a_quote_and_an_estimate_never_as_one():
    assert build_cost(250_000, Provenance.QUOTE).provenance is Provenance.QUOTE
    assert "estimate" in build_cost(250_000, Provenance.ESTIMATE).basis.lower()
    with pytest.raises(CostError):
        build_cost(250_000, None)          # type: ignore[arg-type]


def test_no_build_cost_at_all_requires_input_rather_than_assuming_zero():
    model = cost_model(["cmp-b"], CATALOGUE, envelope="expected", volume={}, build=None)
    assert any("build cost" in r for r in model.requires_input)
    assert model.year_one.expected == model.monthly.expected * 12


def test_year_one_is_build_plus_twelve_months_and_keeps_the_range():
    total = year_one_total(ThreePoint(100, 200, 300), 12_000)
    assert (total.low, total.expected, total.high) == (13_200, 14_400, 15_600)


# ---------------------------------------------------------------- what the model says about itself

def test_the_model_stamps_the_catalogue_and_design_versions_and_its_caveat():
    model = cost_model(["cmp-b"], CATALOGUE, envelope="expected", volume={}, build=None,
                       sheet_version="v0.27", design_version="d-42")
    assert model.sheet_version == "v0.27" and model.design_version == "d-42"
    assert "illustrative" in model.caveat.lower() and model.envelope == "expected"


def test_every_costed_line_cites_the_catalogue_line_it_came_from():
    model = cost_model(["cmp-a", "cmp-b"], CATALOGUE, envelope="expected",
                       volume={"runs_per_month": 6000}, build=None)
    assert all(line.source_line and line.unit for line in model.lines)
    assert model.lines[0].volume == 6000.0 and model.lines[1].volume is None
