"""Every step says in a few words what it does, in ONE place.

`step_5` is an address, not a description. A person watching a run should not have to hold the
numbering of a 25-step framework in their head to know which one is running — and the label that
answers it already existed as `PENDING_STEPS` in the screening workflow, for nine of the steps, in
a file the live view cannot see. So it moves onto `Step`, where both halves, the run log and the
live page read it from the same place.
"""
from lab.workloads.use_case_screening import workflow as screening
from lab.workloads.usecase import steps as S


def test_every_step_has_a_short_title():
    for step in list(S.STEPS) + [S.CAPABILITY_QUERY]:
        assert step.title, f"step {step.number} has no title"
        assert len(step.title.split()) <= 5, f"step {step.number}: {step.title!r} is a sentence"
        assert step.title == step.title.strip()


def test_a_title_reads_as_an_action_not_as_the_field_it_writes():
    """`coverage_map` is the record key and is already shown as `writes`. A title that repeated it
    would cost a column and say nothing new."""
    assert S.step_for("5").title == "match capabilities"
    assert S.step_for("5").title != S.step_for("5").key


def test_the_screening_labels_are_the_step_titles_and_not_a_second_copy():
    """`PENDING_STEPS` is what a deferred step is called in the record. Two hand-maintained lists
    of the same nine labels is one to forget when a step is renamed."""
    assert screening.PENDING_STEPS == {s.number: s.title for s in S.STEPS
                                       if s.number in screening.PENDING_STEPS}
