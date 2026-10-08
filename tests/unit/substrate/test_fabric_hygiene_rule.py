"""The hygiene RULE: which catalogued records are working files that should never have entered the lifecycle.

`scripts/fabric_hygiene.py` is an operator script and scripts are coverage-exempt, but `is_working_file` is a
pure rule that WITHDRAWS records and DECLINES a person's card. A rule with that blast radius is tested, and
testing it costs nothing because it is a pure function over one dict.

BRS principle 8: "Only managed artifacts enter the lifecycle. Transcripts, threads and working files stay
where they are as pointers. What gets owned, reviewed and published are the products made from them."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import fabric_hygiene as H  # noqa: E402


def lab(ref, process="transcript_to_minutes", **kw):
    return {"pointer": {"source": "lab", "ref": ref}, "produced_by": process, **kw}


def collab(name, handle="collab://item/drive-1/x", **kw):
    return {"pointer": {"source": "collab", "handle": handle}, "title": name, "produced_by": "", **kw}


def test_a_lab_record_is_a_working_file_unless_it_is_a_declared_product():
    """The rule as it stood: a producer's declared product stays, everything else it left behind is a working
    file — a recording, a per-lane segment dump, a submission record."""
    assert H.is_working_file(lab("art://s/x.minutes.json")) is False
    assert H.is_working_file(lab("art://s/x.segments.json")) is True
    assert H.is_working_file(lab("art://s/rec.mp4", process="meeting_to_transcript")) is True


def test_a_collab_transcript_or_comparison_is_a_working_file_and_minutes_are_not():
    """Measured 7 Oct 2026: the rule returned False for ANY non-`lab` pointer, so 26 meeting `.txt` files
    swept in from the organiser's Recordings folder were admitted as managed artifacts and raised a
    draft-review card each. A transcript is the working material a meeting produces; the MINUTES are the
    product made from it, and principle 8 distinguishes exactly those two.

    Decided by the user 7 Oct 2026: keep minutes, withdraw transcripts and comparisons.
    """
    assert H.is_working_file(collab("Test 8-20261006-Meeting Recording.soniox.transcript.txt")) is True
    assert H.is_working_file(collab("Test 8-20261006-Meeting Recording.comparison.txt")) is True
    assert H.is_working_file(collab("Test 8-20261006-Meeting Recording.soniox.minutes.txt")) is False


def test_the_collab_rule_is_decided_on_the_NAME_and_nothing_else():
    """A collab record carries no `produced_by` — it was swept from a folder, not emitted by a run — so the
    file name is the only evidence there is. Case and path must not change the answer."""
    assert H.is_working_file(collab("MEETING.SONIOX.TRANSCRIPT.TXT")) is True
    assert H.is_working_file(collab("notes.transcript.txt", handle="collab://item/d/abc")) is True


def test_an_ordinary_collab_document_is_never_a_working_file():
    """The pilot library is full of architecture documents, business cases and CSVs. The widened rule must
    reach meeting workings and nothing else — a rule that withdrew a business case would be worse than the
    defect it fixes."""
    for name in ("Malaffi integration design.docx", "UC-1043-business-case.docx", "01_sanity_3.csv",
                 "README.md", "capability-map.xlsx", "meeting notes.docx"):
        assert H.is_working_file(collab(name)) is False, name


def test_a_source_the_rule_does_not_know_is_left_alone():
    """Silence is the safe answer for a source nobody has considered: it stays in the lifecycle and a person
    decides, rather than being withdrawn by a rule that was never written with it in mind."""
    assert H.is_working_file({"pointer": {"source": "ado", "workItem": "123"}, "produced_by": ""}) is False
