"""Fill the intake by uploading a CSV, rather than typing twenty-one boxes.

The form is generated from the published `intake-field-specs` artifact, and so is the template — a
template written by hand would drift from the fields the moment one was added, and drift silently,
because a CSV with a stale column looks exactly like a CSV with a typo.

An unknown field is REPORTED, never dropped. Someone filling a spreadsheet wants to know that
"Urgancy" went nowhere; discarding it quietly is how a submission arrives half-empty and nobody
can say why.
"""
import pytest

from lab.substrate.review import intake_csv

HEADERS = ["Field", "Group", "Label", "Type", "Required", "Order", "Used by"]
SPECS = [
    ["Urgency · Required-by date or urgency band", "Urgency", "Required-by date or urgency band",
     "date", "yes", "01", "Roadmap section"],
    ["Investment · Budget bucket or vendor quote", "Investment", "Budget bucket or vendor quote",
     "text", "no", "02", "Build cost"],
    ["Sensitivity flags · Personal data", "Sensitivity flags", "Personal data", "yesno", "yes",
     "03", "Driver 3"],
]


def test_the_template_has_one_row_per_published_field_in_order():
    """Generated from the artifact, so a field added by a PUBLISH appears in the next download with
    no change here."""
    text = intake_csv.template(SPECS, HEADERS)
    rows = [line.split(",")[0:2] for line in text.strip().splitlines()[1:]]
    assert [r[0] for r in rows] == ["Urgency", "Investment", "Sensitivity flags"]
    assert rows[0][1].startswith("Required-by")


def test_the_template_carries_the_type_and_whether_it_is_required():
    """A person filling it in should not have to guess whether a blank is allowed, or whether a cell
    wants a date or a sentence."""
    header, first = intake_csv.template(SPECS, HEADERS).splitlines()[:2]
    assert "Type" in header and "Required" in header
    assert "date" in first and "yes" in first


def test_a_filled_template_parses_to_the_mapping_the_contract_wants():
    """`{label: {"value": text}}` — the same shape the form produces and `InputField._mapping`
    accepts. A flat label -> value is refused by the contract."""
    text = ("Group,Field,Value\n"
            "Urgency,Required-by date or urgency band,Q4 2026\n"
            "Investment,Budget bucket or vendor quote,AED 250000\n")
    answer, problems = intake_csv.parse(text.encode(), SPECS, HEADERS)
    assert problems == []
    assert answer["Urgency · Required-by date or urgency band"] == {"value": "Q4 2026"}
    assert answer["Investment · Budget bucket or vendor quote"] == {"value": "AED 250000"}


def test_an_empty_value_is_left_out_rather_than_sent_as_a_blank():
    """A blank cell means "not answered", and the published behaviour for an unanswered field is a
    requires-input marker on the business case — not an empty string somebody has to interpret."""
    text = "Group,Field,Value\nUrgency,Required-by date or urgency band,\n"
    answer, problems = intake_csv.parse(text.encode(), SPECS, HEADERS)
    assert answer == {} and problems == []


def test_an_unknown_field_is_named_rather_than_discarded():
    """The whole reason this reports instead of filtering: a typo in a spreadsheet is invisible
    once the row is dropped, and the submission arrives short with no explanation."""
    text = "Group,Field,Value\nUrgency,Requiredby date,Q4\n"
    answer, problems = intake_csv.parse(text.encode(), SPECS, HEADERS)
    assert answer == {}
    assert any("Requiredby date" in p for p in problems)


def test_matching_is_forgiving_about_case_and_spacing_but_not_about_meaning():
    """A spreadsheet round-trip changes whitespace and capitalisation; it does not change which
    field somebody meant."""
    text = "Group,Field,Value\n  urgency ,  REQUIRED-BY DATE OR URGENCY BAND ,Q4 2026\n"
    answer, _ = intake_csv.parse(text.encode(), SPECS, HEADERS)
    assert answer["Urgency · Required-by date or urgency band"] == {"value": "Q4 2026"}


def test_a_field_named_without_its_group_still_resolves_when_it_is_unambiguous():
    """People delete columns. A field name unique across the whole set identifies itself."""
    text = "Field,Value\nPersonal data,no\n"
    answer, problems = intake_csv.parse(text.encode(), SPECS, HEADERS)
    assert answer["Sensitivity flags · Personal data"] == {"value": "no"}
    assert problems == []


def test_a_csv_with_no_recognisable_columns_says_so_instead_of_returning_nothing():
    """Returning `{}` would read as "the file was empty", and the person would re-upload it."""
    answer, problems = intake_csv.parse(b"a,b\n1,2\n", SPECS, HEADERS)
    assert answer == {} and problems and "Field" in problems[0]


def test_the_contract_bounds_are_respected():
    """`InputField._mapping` refuses more than 64 labels or 8 KB. Better to say which rows were
    dropped here than to have the run refuse the whole submission."""
    specs = [[f"G · F{i}", "G", f"F{i}", "text", "no", f"{i:02d}", ""] for i in range(70)]
    text = "Group,Field,Value\n" + "".join(f"G,F{i},value {i}\n" for i in range(70))
    answer, problems = intake_csv.parse(text.encode(), specs, HEADERS)
    assert len(answer) <= 64
    assert any("64" in p for p in problems)


@pytest.mark.parametrize("body", [b"", b"\n", b"Group,Field,Value\n"])
def test_an_empty_file_is_not_an_error_it_is_an_empty_answer(body):
    answer, problems = intake_csv.parse(body, SPECS, HEADERS)
    assert answer == {} and problems == []


# ---------------------------------------------------------------- the shipped example


def test_the_filled_example_answers_every_published_field():
    """"Use the intake agent as the use case" — the screening agent group assessed as a use case of
    itself. It ships in the image as an EXAMPLE, not a schema, so it is checked against the
    published specs rather than trusted: a field added by a publish should make this fail and be
    added to the example, and a row naming a field that no longer exists should fail here rather
    than arrive as a warning in front of a person trying to submit."""
    from pathlib import Path

    from lab.core.usecase import seed
    from lab.substrate.review import app

    spec = seed.artifact("intake_field_specs")["fields"]
    col = {h: i for i, h in enumerate(spec["headers"])}
    samples = dict(app.sample_csvs())
    # EVERY example must parse cleanly — an example carrying a field the corpus no longer
    # publishes is a second source of truth, and the person meets it as a warning.
    for name, body in samples.items():
        _, problems = intake_csv.parse(body, spec["rows"], spec["headers"])
        assert problems == [], f"{name}: {problems}"
    # and the FULL one answers every published field, which is what makes it the full journey.
    answer, _ = intake_csv.parse(samples["1-full-journey"], spec["rows"], spec["headers"])
    assert set(answer) == {str(r[col["Field"]]) for r in spec["rows"]}


def test_every_yesno_answer_in_the_example_is_one_the_widget_can_hold():
    """A selectbox refuses a value outside its options, so an example carrying "Yes" or "true"
    would half-apply and the person would see the failure as missing fields."""
    from pathlib import Path

    from lab.core.usecase import seed
    from lab.substrate.review import app

    spec = seed.artifact("intake_field_specs")["fields"]
    col = {h: i for i, h in enumerate(spec["headers"])}
    for name, body in app.sample_csvs():
        answer, _ = intake_csv.parse(body, spec["rows"], spec["headers"])
        for row in spec["rows"]:
            if str(row[col["Type"]]) != "yesno":
                continue
            got = answer.get(str(row[col["Field"]]))
            # Answered or not answered; never a third spelling the widget cannot hold.
            assert got is None or got["value"] in ("yes", "no"), (name, row[col["Field"]], got)
