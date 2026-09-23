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
