"""`pending_steps` must describe THIS process, and count what actually happened.

Audited 23 Sep 2026, two defects on one record:

* the screening `Derivation` was seeded from `STEPS` — which is `SCREENING_STEPS + DESIGN_STEPS` —
  so a PERFECT screening still reported eight design steps as pending, steps this process does not
  run and the design run does not inherit;
* the approval summary carried `len(PENDING_STEPS)`, the length of the module constant. It read 17
  on the observed run (nine of nine screening steps accounted for) and would read 17 on a run where
  every agent was unwired. The one number telling a reviewer how much of the screening did not
  happen was identical in the best and worst case, and could not change.
"""
from lab.workloads.usecase import steps as S
from lab.workloads.use_case_screening import workflow as screening


def test_the_screening_seeds_only_the_steps_it_runs():
    assert set(screening.PENDING_STEPS) == {s.number for s in S.SCREENING_STEPS}
    assert not set(screening.PENDING_STEPS) & {s.number for s in S.DESIGN_STEPS}


def test_every_seeded_step_is_named_by_its_own_title():
    assert screening.PENDING_STEPS == {s.number: s.title for s in S.SCREENING_STEPS}


def test_the_summary_counts_what_this_run_left_pending_not_the_table_size():
    """A count that cannot change is not a measurement."""
    perfect = screening.summary_counts({"pending_steps": {}, "defaulted_steps": {}})
    partial = screening.summary_counts({"pending_steps": {"9": "x", "10": "y"},
                                        "defaulted_steps": {"6": "z"}})
    assert perfect["pending_steps"] == 0
    assert partial["pending_steps"] == 2
    assert partial["defaulted_steps"] == ["6"]
