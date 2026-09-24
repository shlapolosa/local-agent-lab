"""An intake label nothing published is REPORTED, not silently carried.

`_mapping` checks that a label is a non-empty string and nothing more — it does not know the
published labels exist. So an agent that paraphrases a question ("medium urgency" where the
published field reads "Urgency · Required-by date or urgency band") produces an intake that is
accepted, stored, carried into the business case and read by NOTHING, with no surface saying so.

The CSV path already does this right: `intake_csv.parse` names every field it could not match.
The API path had no equivalent, so the same mistake was loud in one door and silent in the other.

Reported rather than refused, deliberately. A label the corpus does not publish may be a
paraphrase, or it may be a field published since this image was built — and refusing the whole
submission for either would lose the thirty answers that were fine. It becomes a gap flag the
business case carries to the approver, which is what every other unresolved thing here does.
"""
from lab.workloads.usecase import intake as intake_mod


PUBLISHED = ["Effort table · Role", "Quality baseline · error rate", "Urgency · Required-by date"]


def test_a_label_the_corpus_publishes_is_not_reported():
    unknown = intake_mod.unmatched({"Quality baseline · error rate": {"value": "0.1"}}, PUBLISHED)
    assert unknown == []


def test_a_paraphrased_label_is_named():
    unknown = intake_mod.unmatched({"medium urgency": {"value": "yes"}}, PUBLISHED)
    assert unknown == ["medium urgency"]


def test_matching_ignores_case_and_surrounding_space_because_those_are_not_mistakes():
    assert intake_mod.unmatched({"  effort table · role ": {"value": "mid"}}, PUBLISHED) == []


def test_nothing_published_reports_nothing_rather_than_everything():
    """A corpus that could not be read is a check that cannot run. Reporting every label as
    unmatched would bury the real ones and blame the submitter for an unreachable artifact."""
    assert intake_mod.unmatched({"anything": {"value": "x"}}, []) == []


def test_an_empty_intake_reports_nothing():
    assert intake_mod.unmatched({}, PUBLISHED) == []


def test_the_report_is_a_gap_flag_naming_the_labels_and_who_can_fix_them():
    flags = intake_mod.gap_flags(["medium urgency", "budget"], PUBLISHED)
    assert len(flags) == 1
    what = flags[0]["what"]
    assert "medium urgency" in what and "budget" in what
    assert flags[0]["owning_body"], "a gap flag names who owns closing it"


def test_no_unmatched_labels_raises_no_flag():
    assert intake_mod.gap_flags([], PUBLISHED) == []


# ------------------------------------------------------------- wired into the screening run

def test_the_screening_run_pins_the_published_questions_because_it_reads_them():
    """A pin carries exactly what its run reads and nothing else — so a run that checks the
    answered labels against the published ones has to pin that artifact."""
    from lab.workloads.use_case_screening import workflow as screening
    assert screening.INTAKE_ARTIFACT in screening.REFERENCE_ARTIFACTS


def test_an_unreadable_corpus_reports_nothing_rather_than_everything():
    """The check cannot run, which is not the same as every label being wrong. Reporting all of
    them would bury the real ones and blame a submitter for an artifact they cannot reach."""
    import asyncio

    from lab.workloads.use_case_screening import workflow as screening

    async def boom(*a, **k):
        raise RuntimeError("reference-mcp unreachable")

    original = screening.reference.records
    screening.reference.records = boom
    try:
        got = asyncio.run(screening.intake_problems({}, "pin-1", {"anything": {"value": "x"}}))
    finally:
        screening.reference.records = original
    assert got == []


def test_an_empty_intake_asks_the_corpus_nothing():
    """Nothing answered is nothing to check — and a read costs a consumption row."""
    import asyncio

    from lab.workloads.use_case_screening import workflow as screening

    called = []
    original = screening.reference.records

    async def watch(*a, **k):
        called.append(a)
        return []

    screening.reference.records = watch
    try:
        assert asyncio.run(screening.intake_problems({}, "pin-1", {})) == []
    finally:
        screening.reference.records = original
    assert called == []
