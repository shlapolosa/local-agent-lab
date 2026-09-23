"""The `submission` slot takes PROSE, and the file picker must say so.

`ProcessSpec` states it plainly — "ONE art:// reference to the submitted use case as prose — a
.md, .docx or .pdf saying what the problem is, who has it, and what changes". The picker offered
`csv` anyway, because `submission` shared one type list with `attachments`, where a spreadsheet of
evidence is perfectly reasonable.

Measured 23 Sep 2026, twice. A person uploaded `3-simple.csv` — an INTAKE FIELD file, meant for
the prepopulate editor — into the submission slot. The run read a table of blank driver rows as
the use-case narrative, found no use case in it (correctly), and spent ten minutes framing the
absence of input as the problem to be solved, all the way to a criticality approval. Nothing
failed; every step did its job on the wrong input.

The form already refuses what the contract would refuse for MISSING fields ("rather than a
600-second run discovering it"). This is the same rule applied to what a file IS.
"""
from lab.substrate.review import app as APP


def test_the_submission_picker_offers_prose_and_not_spreadsheets():
    types = APP.UPLOAD_TYPES[("use_case_screening", "submission")]
    assert "md" in types and "docx" in types and "pdf" in types, types
    for tabular in ("csv", "xlsx", "xls"):
        assert tabular not in types, (
            f"{tabular!r} is offered in the submission slot — an intake field file uploaded there "
            f"is read as the use-case narrative, and the run cannot tell the difference")


def test_attachments_still_take_a_spreadsheet_because_evidence_is_not_prose():
    """A vendor quote or a current-process export is exactly what `attachments` is for."""
    assert "csv" in APP.UPLOAD_TYPES[("use_case_screening", "attachments")]


def test_the_prose_list_is_a_SUBSET_of_what_the_document_reader_can_parse():
    """Whatever the picker offers, storage-mcp has to be able to read it as text."""
    assert set(APP.UPLOAD_TYPES[("use_case_screening", "submission")]) <= set(APP.REQUIREMENT_TYPES)
