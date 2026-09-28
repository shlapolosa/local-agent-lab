"""Step 23's build line, priced at the PUBLISHED delivery day rate (CAFÉ workbook, 28 Sep 2026: "price
the build at the delivery day rate; Year-1 = build + 12 x monthly run").

The rate is one factor; the effort is the other, and the workbook's source for it — historical
delivery actuals — is not yet supplied. So the multiplication is deterministic and the rate governed,
while the FTE-days come from the cost engineer only WITH a stated basis, and the line is an
`estimate`. A captured quote or budget always beats it: a figure somebody will be held to outranks
one reconstructed from a rate.
"""
import pytest

from lab.core.usecase import cost

RATES = [{"assumption": "External delivery FTE day rate", "value": "AED 3,670 per FTE-day",
          "basis": "Infrastructure business case, p.111"}]


def test_fte_days_with_a_basis_are_priced_at_the_published_rate():
    got = cost.build_from_rate({"build_fte_days": 40, "build_basis": "4 building blocks x 10 days"},
                               RATES)
    assert got["amount"] == 146_800.0
    assert got["provenance"] == "estimate"
    assert "AED 3,670" in got["basis"] and "4 building blocks" in got["basis"]
    assert got["currency"] == "AED", "the rate's currency travels with the line it priced"


def test_a_captured_figure_beats_an_estimate_from_the_rate():
    inputs = {"build_amount": 90_000, "build_provenance": "vendor quote", "build_fte_days": 40,
              "build_basis": "whatever"}
    got = cost.build_from_rate(inputs, RATES)
    assert (got["amount"], got["provenance"]) == (90_000.0, "vendor quote")


@pytest.mark.parametrize("inputs", [{"build_fte_days": 40},                    # no basis
                                    {"build_fte_days": 0, "build_basis": "x"},
                                    {}])
def test_no_basis_or_no_effort_is_NO_build_cost_rather_than_a_guess(inputs):
    assert cost.build_from_rate(inputs, RATES) == {"amount": 0.0, "provenance": "", "basis": "",
                                                   "currency": ""}


def test_no_published_rate_is_no_estimate():
    assert cost.build_from_rate({"build_fte_days": 40, "build_basis": "x"}, [])["amount"] == 0.0


def test_a_rate_that_cannot_be_read_as_a_number_is_refused_rather_than_read_as_zero():
    with pytest.raises(cost.CostError, match="day rate"):
        cost.build_from_rate({"build_fte_days": 40, "build_basis": "x"},
                             [{"assumption": "External delivery FTE day rate", "value": "TBC"}])


def test_step_23_refuses_fte_days_with_no_basis():
    """The prompt's rule means nothing unless the gate holds it: an effort figure nobody can check
    becomes, at the published rate, a build cost nobody can check."""
    from lab.workloads.usecase.steps import step_for
    problems = step_for("23").complete({"build_provenance": "", "notes": [], "build_fte_days": 40},
                                        {})
    assert any("basis" in p for p in problems), problems
    assert not step_for("23").complete({"build_provenance": "", "notes": [], "build_fte_days": 40,
                                        "build_basis": "4 building blocks x 10 days"}, {})


def test_two_day_rates_are_refused_rather_than_one_picked_by_row_order():
    """Review F2, 28 Sep 2026: the first row whose assumption said "day rate" won, and lookup rows
    come back in content-hash order — with an internal rate listed first, 4 days priced at the
    wrong rate. Two candidates is an ambiguity a person resolves, not a coin toss."""
    rates = RATES + [{"assumption": "Internal delivery FTE day rate", "value": "AED 1,000 per FTE-day"}]
    with pytest.raises(cost.CostError, match="more than one"):
        cost.build_from_rate({"build_fte_days": 4, "build_basis": "x"}, rates)


@pytest.mark.parametrize("value", ["AED 3,670 / FTE-day", "3,670 AED per FTE-day", ", per FTE-day"])
def test_a_rate_in_another_shape_is_a_CostError_never_a_raw_crash(value):
    with pytest.raises(cost.CostError):
        cost.build_from_rate({"build_fte_days": 4, "build_basis": "x"},
                             [{"assumption": "External delivery FTE day rate", "value": value}])
