"""Step 23 — the cost model. Seven sub-steps, three of them pure arithmetic.

The estimate is computed against a REFERENCE price sheet rather than a live pricing query, so that
two submissions costed a week apart stay comparable. Everything here therefore hangs off a pinned
sheet version, and the rules that matter most are the two refusals: an unmatched resource is a gap
flag and never a proxy price (FR-32), and an estimate is never presented as a quote (FR-34).
"""
import pytest

from lab.core.usecase.cost import (
    CostError,
    Provenance,
    ThreePoint,
    band_position,
    build_cost,
    cost_model,
    parse_estimate,
    price_lines,
    year_one_total,
)


# ---------------------------------------------------------------- reading the sheet

def test_the_published_sheet_loads_with_every_line_priced_or_marked():
    lines = price_lines()
    assert len(lines) >= 10
    assert all(line.service for line in lines)


@pytest.mark.parametrize("text,low,high", [
    ("~175", 175, 175),
    ("~100–400", 100, 400),
    ("~9,200", 9200, 9200),
    ("~500–2,000", 500, 2000),
    ("~700+", 700, 700),
])
def test_an_estimate_parses_into_a_range(text, low, high):
    point = parse_estimate(text)
    assert (point.low, point.high) == (low, high)


def test_an_included_line_costs_nothing_but_is_still_a_line():
    """"Included" in the M365 licensing sense is a real answer, not a missing one — the resource is
    switched on and the cost model must show it."""
    point = parse_estimate("Included")
    assert point.expected == 0
    assert point.known is True


def test_an_unparsable_estimate_is_not_silently_zero():
    with pytest.raises(CostError):
        parse_estimate("call us")


# ---------------------------------------------------------------- 23.2 mapping, and the gap flag

def test_a_resource_matches_its_price_sheet_line():
    model = cost_model(["API Management (Developer)"], build=None)
    assert model.lines[0].service.startswith("API Management")
    assert model.gap_flags == ()


def test_a_resource_with_no_line_raises_a_gap_flag_and_never_a_proxy_price():
    """FR-32, and the reason it is worth a rule: a proxy price looks exactly like a real one in the
    total, and nothing downstream could tell them apart."""
    model = cost_model(["Quantum Annealing Service"], build=None)
    assert "Quantum Annealing Service" in model.gap_flags
    assert model.lines == ()
    assert model.monthly.expected == 0


def test_a_gap_flag_does_not_stop_the_rest_of_the_model_being_costed():
    model = cost_model(["API Management (Developer)", "Nonexistent Service"], build=None)
    assert model.gap_flags
    assert model.monthly.expected > 0


# ---------------------------------------------------------------- 23.3 banding

@pytest.mark.parametrize("envelope,expected", [("low", 100), ("expected", 250), ("high", 400)])
def test_a_banded_line_is_positioned_by_the_quality_attribute_envelope(envelope, expected):
    assert band_position(ThreePoint(100, 250, 400), envelope) == expected


def test_an_unbanded_line_has_no_range_to_position():
    point = parse_estimate("~175")
    assert point.low == point.expected == point.high == 175


def test_the_three_point_range_is_carried_through_rather_than_collapsed():
    """FR-31 says so explicitly. Collapsing to a single figure loses the only honest statement the
    estimate can make about its own uncertainty."""
    model = cost_model(["Container Apps"], build=None)
    assert model.monthly.low < model.monthly.high


# ---------------------------------------------------------------- 23.5 build cost provenance

def test_a_vendor_quote_is_recorded_as_a_quote():
    cost = build_cost(250_000, Provenance.QUOTE)
    assert cost.provenance is Provenance.QUOTE


def test_an_estimate_is_never_presented_as_a_quote():
    """FR-34. The three provenances are not interchangeable: an approver reads 'quote' as a number
    somebody is willing to be held to."""
    cost = build_cost(250_000, Provenance.ESTIMATE)
    assert cost.provenance is Provenance.ESTIMATE
    assert "estimate" in cost.basis.lower()


def test_a_build_cost_with_no_provenance_is_refused():
    with pytest.raises(CostError):
        build_cost(250_000, None)          # type: ignore[arg-type]


def test_no_build_cost_at_all_requires_input_rather_than_assuming_zero():
    model = cost_model(["API Management (Developer)"], build=None)
    assert model.requires_input
    assert model.year_one.expected == model.monthly.expected * 12


# ---------------------------------------------------------------- 23.6 the arithmetic

def test_year_one_is_build_plus_twelve_months_of_run():
    assert year_one_total(ThreePoint(100, 200, 300), 12_000).expected == 12_000 + 200 * 12


def test_year_one_preserves_the_three_point_range():
    total = year_one_total(ThreePoint(100, 200, 300), 12_000)
    assert total.low == 12_000 + 1_200
    assert total.high == 12_000 + 3_600


# ---------------------------------------------------------------- 23.7 assembly

def test_the_model_stamps_the_sheet_version_every_line_came_from():
    """CR-23/CR-24: a cost produced against a superseded price sheet is wrong in a way that is
    invisible without the version stamp."""
    model = cost_model(["API Management (Developer)"], build=None)
    assert model.sheet_version


def test_the_model_stamps_the_design_version_it_was_derived_from():
    model = cost_model(["API Management (Developer)"], build=None, design_version="d-42")
    assert model.design_version == "d-42"


def test_the_model_carries_the_illustrative_caveat_of_the_seeded_sheet():
    """The spec says the seeded figures are illustrative of the structure. A run costed against
    them has to say so rather than read as a priced estimate."""
    assert "illustrative" in cost_model(["Key Vault"], build=None).caveat.lower()


def test_every_costed_line_cites_the_line_it_came_from():
    model = cost_model(["Container Apps", "Key Vault"], build=None)
    assert all(line.service and line.unit for line in model.lines)
