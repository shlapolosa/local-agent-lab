"""A repeating table of typed rows — the shape a real effort table needs.

Measured on the M42 intake: 39 submissions list one role, **22 list two and one lists three**. The
`MAPPING` kind is `label -> {field: value}`, one entry per label, so 37 % of real submissions
cannot be expressed: the second and third roles are dropped or crushed into one free-text blob.

That is not an ergonomics problem. Driver 1 is the only benefit driver with real data in all 62
submissions, and a driver left open means `recommend()` can never return `proceed` — so every case
in the portfolio reads "proceed with conditions" and the verdict carries no signal at all. A
portfolio you cannot rank is the failure this whole assessment exists to prevent.

`benefit.operational_efficiency` already takes a SEQUENCE of rows. The contract simply could not
carry one.
"""
import pytest

from lab.platform.contracts import Column, InputField, InputKind

EFFORT = InputField(
    "effort", InputKind.TABLE,
    "Who does this today and for how long.", required=False,
    columns=(Column("role", InputKind.CHOICE, required=True,
                    choices=("junior", "mid", "senior", "lead", "exec")),
             Column("headcount", InputKind.NUMBER, required=True),
             Column("current_minutes", InputKind.NUMBER, required=True),
             Column("expected_minutes", InputKind.NUMBER, required=False)))


def test_a_table_carries_many_rows():
    rows = EFFORT.coerce([
        {"role": "mid", "headcount": "2", "current_minutes": "180", "expected_minutes": "30"},
        {"role": "lead", "headcount": "1", "current_minutes": "120", "expected_minutes": "20"}])
    assert len(rows) == 2
    assert rows[0]["headcount"] == 2.0 and rows[1]["role"] == "lead"


def test_numbers_arrive_as_numbers_so_the_formula_does_not_parse_prose():
    rows = EFFORT.coerce([{"role": "mid", "headcount": "2", "current_minutes": "180"}])
    assert isinstance(rows[0]["headcount"], float)


def test_a_row_missing_a_required_column_is_refused_by_name():
    with pytest.raises(ValueError, match="current_minutes"):
        EFFORT.coerce([{"role": "mid", "headcount": "2"}])


def test_a_value_outside_a_column_s_closed_set_is_refused():
    with pytest.raises(ValueError, match="role"):
        EFFORT.coerce([{"role": "wizard", "headcount": "1", "current_minutes": "10"}])


def test_a_column_nobody_declared_is_refused_rather_than_carried():
    """A column the domain never reads is a value somebody believes was captured."""
    with pytest.raises(ValueError, match="sprint_length"):
        EFFORT.coerce([{"role": "mid", "headcount": "1", "current_minutes": "10",
                        "sprint_length": "2 weeks"}])


def test_an_optional_column_may_simply_be_absent():
    rows = EFFORT.coerce([{"role": "mid", "headcount": "1", "current_minutes": "10"}])
    assert "expected_minutes" not in rows[0] or rows[0]["expected_minutes"] is None


def test_an_empty_table_is_absence_not_an_empty_answer():
    assert EFFORT.coerce([]) is None
    assert EFFORT.coerce(None) is None


def test_a_table_is_bounded_like_every_other_input():
    """Bounded for the same reason MAPPING is: an input that can grow without limit is a way to
    smuggle arbitrary state through a governed door."""
    too_many = [{"role": "mid", "headcount": "1", "current_minutes": "10"}] * 200
    with pytest.raises(ValueError, match="rows"):
        EFFORT.coerce(too_many)


def test_a_table_field_must_declare_its_columns():
    with pytest.raises(ValueError, match="columns"):
        InputField("x", InputKind.TABLE, "no columns", required=False)


def test_columns_belong_only_to_a_table():
    with pytest.raises(ValueError, match="columns"):
        InputField("x", InputKind.REF, "not a table", columns=(Column("a", InputKind.NUMBER),))
