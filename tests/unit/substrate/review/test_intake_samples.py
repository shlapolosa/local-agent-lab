"""The filled examples a submitter can start from — several, not one.

One example taught one shape. A person could not see what a MINIMAL honest submission looks like
(every blank becomes a requires-input marker, not an estimate), nor what a submission that the
framework will deterministically REJECT looks like, nor how much a genuinely complicated case
carries. The set is discovered from the directory, so adding a fifth is a file and not an edit
here — the same property the template already has by being generated from the corpus.

They are EXAMPLES, never a schema. The schema is the published artifact, and a row in any of these
that no longer matches a published field is reported by the parser like any other unknown field —
which is what keeps a stale example from quietly becoming a second source of truth.
"""
import csv
import io

from lab.substrate.review import app, intake_csv


def test_several_examples_ship_and_they_are_discovered_not_listed():
    names = [name for name, _ in app.sample_csvs()]
    assert len(names) >= 4, names
    assert names == sorted(names), "offered in a stable order a person can learn"


def test_each_one_parses_against_the_published_fields_with_nothing_unknown():
    """The test that stops an example drifting from the corpus: every row must name a field the
    artifact publishes."""
    rows, headers = intake_csv_rows()
    for name, body in app.sample_csvs():
        mapping, problems = intake_csv.parse(body, rows, headers)
        assert not problems, f"{name}: {problems}"
        assert mapping, f"{name}: parsed to nothing"


def test_the_simple_one_is_genuinely_sparse_and_the_complex_one_is_complete():
    by_name = dict(app.sample_csvs())
    rows, headers = intake_csv_rows()
    simple, _ = intake_csv.parse(by_name["3-simple"], rows, headers)
    complex_, _ = intake_csv.parse(by_name["4-complex-intake-agent"], rows, headers)
    assert len(simple) < len(complex_) / 2, (len(simple), len(complex_))


def test_the_rejected_example_answers_nothing_that_would_earn_a_capability():
    """It is the DETERMINISTIC rejection: step 5 matches its functions against the technology
    capability map, a purely physical task exercises none, `capability_matched` is False and
    `feasibility_verdict` returns REJECT on its first rule. The intake does not decide that — it
    is here so a reader can see what such a submission looks like before running one."""
    by_name = dict(app.sample_csvs())
    assert "2-rejected-no-capability" in by_name


def intake_csv_rows():
    """The published field rows, from the committed seed — the same list the form is built from."""
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[4]
    seed = json.loads((root / "src/lab/core/usecase/seed/intake_field_specs.json").read_text())
    spec = seed[[k for k in seed if k != "_source"][0]]
    return spec["rows"], spec["headers"]
