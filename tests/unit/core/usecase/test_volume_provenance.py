"""A volume is read from the group that CAPTURES volumes, not from whatever prose matched first.

Audited 23 Sep 2026 and reproduced: intake

    {"Quality":            {"latency": "Response within 5 seconds per user request"},
     "Volume assumptions": {"vol": "about 40k review runs a month"}}

returned `{'runs_per_month': 5.0, 'users': 5.0}` — a LATENCY SLA became the monthly run volume and
the real 40k assumption was never read. Every run-driven line was then priced at the bottom of its
band, recorded as if captured, and which number won depended on the ordering of the intake groups.

Scanning every group was deliberate ("a Finance rename must not silently disable cost") and the
cost of it was unbounded: a seat count from "3 users of the legacy tool" in a Notes field is the
same failure. The rename is still tolerated — a group is preferred by NAME and the rest are a
fallback — but a value read outside the volume group now says where it came from, because a figure
that positions every price line must be attributable.
"""
from lab.core.usecase import cost


INTAKE = {"Quality": {"latency": "Response within 5 seconds per user request"},
          "Volume assumptions": {"vol": "about 40k review runs a month"}}


def test_the_volume_group_wins_over_prose_elsewhere():
    assert cost.volume_from_intake(INTAKE).get("runs_per_month") == 40_000.0


def test_a_latency_sla_is_not_a_run_volume():
    """The specific reproduction: 5 seconds became 5 runs a month, three orders of magnitude out
    and silently at the bottom of every band."""
    assert cost.volume_from_intake(INTAKE).get("runs_per_month") != 5.0


def test_a_volume_group_that_is_SILENT_about_a_driver_does_not_hand_it_to_other_prose():
    """The sharper half of the same defect. The person captured volumes in one place; a figure
    they did not put there is not a volume they gave, and reading one from a Quality field is how
    the wrong number got in."""
    intake = {"Quality": {"latency": "Response within 5 seconds per user request"},
              "Volume assumptions": {"vol": "about 40k review runs a month"}}
    assert "users" not in cost.volume_from_intake(intake)


def test_a_renamed_volume_group_still_works():
    """The reason every group was scanned. A Finance rename must not silently disable cost."""
    renamed = {"Throughput expectations": {"vol": "about 40k review runs a month"}}
    assert cost.volume_from_intake(renamed).get("runs_per_month") == 40_000.0


def test_a_figure_read_outside_the_volume_group_says_so():
    """Attributable, because this figure positions every driven price line."""
    loose = {"Notes": {"n": "3 users of the legacy tool"}}
    got = cost.volume_from_intake(loose)
    assert got.get("users") == 3.0
    assert cost.volume_provenance(loose).get("users") == "Notes"


def test_a_figure_from_the_volume_group_is_attributed_to_it():
    assert cost.volume_provenance(INTAKE).get("runs_per_month") == "Volume assumptions"


def test_nothing_captured_is_nothing_claimed():
    assert cost.volume_from_intake({}) == {} and cost.volume_provenance({}) == {}


def test_a_question_that_merely_says_the_word_volume_is_not_a_volume_group():
    """Measured against the real M42 form: Q24 reads "Is this VOLUME consistent or does it peak?".
    A substring match on the group label picks it as the volume group, and because a volume group
    that exists suppresses the fallback, 0 of 62 real submissions then yielded any volume at all.

    Safer than the garbage it replaced (`users: 24` scraped out of "biggest value" prose) but still
    wrong. A group only counts as the volume group when it actually CARRIES a driver — the label
    proposes, the content decides."""
    peaky = {"Is this volume consistent or does it peak?": {"a": "Fairly consistent"},
             "Notes": {"n": "roughly 40k review runs a month"}}
    assert cost.volume_from_intake(peaky).get("runs_per_month") == 40_000.0


def test_a_volume_group_that_carries_a_driver_still_wins_outright():
    intake = {"Volume assumptions": {"vol": "about 40k review runs a month"},
              "Quality": {"latency": "Response within 5 seconds per user request"}}
    got = cost.volume_from_intake(intake)
    assert got.get("runs_per_month") == 40_000.0 and "users" not in got


# --------------------------------------- the shape the REAL producers emit, not the prose one

def test_the_typed_intake_form_shape_yields_a_volume():
    """The defect this closes, and every test here shared it. The review app's typed form, the CSV
    parser and the shipped `samples/intake-agent.csv` all emit `label -> {"value": "120"}`, with
    the driver words in the LABEL. `_by_group` joined only the values, so the number arrived with
    no word beside it and every structured submission yielded nothing at all.

    The prose shape these tests used — `{"Volume assumptions": {"value": "120 runs per month"}}` —
    is what the FALLBACK free grid emits. It was the only shape the code could read and the only
    shape the tests tried."""
    typed = {"Volume assumptions · Runs per month": {"value": "120"},
             "Volume assumptions · Users": {"value": "40"}}
    got = cost.volume_from_intake(typed)
    assert got.get("runs_per_month") == 120.0 and got.get("users") == 40.0


def test_the_nested_grid_shape_yields_a_volume_too():
    nested = {"Volume assumptions": {"runs per month": "120", "users": "40"}}
    got = cost.volume_from_intake(nested)
    assert got.get("runs_per_month") == 120.0 and got.get("users") == 40.0


def test_the_shipped_sample_csv_yields_a_volume():
    """The lab's own example submission. If it yields nothing, nothing does."""
    import csv
    import io
    from pathlib import Path
    sample = Path(__file__).resolve().parents[4] / \
        "src/lab/substrate/review/samples/intake-agent.csv"
    rows = list(csv.DictReader(io.StringIO(sample.read_text())))
    intake = {f'{r["Group"]} · {r["Field"]}': {"value": r["Value"]}
              for r in rows if r.get("Value", "").strip()}
    assert any(k.lower().startswith("volume") for k in intake), "the sample captures volumes"
    assert cost.volume_from_intake(intake), "and they must be readable"
