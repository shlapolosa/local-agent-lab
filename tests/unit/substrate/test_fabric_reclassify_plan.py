"""The re-classification driver's one pure decision: which catalogued records can be re-read.

The script itself is an operator CLI and coverage-exempt, but `plan` decides what a sweep over the whole
estate touches, and a wrong answer there is either a record silently skipped or a submission that cannot run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import fabric_reclassify as R  # noqa: E402


def row(iri="urn:fabric:artifact:A", **p):
    return {"iri": iri, "title": "Notes", "pointer": p or {"source": "collab", "handle": "collab://item/d/i"}}


def test_a_record_is_re_readable_when_its_pointer_can_be_submitted_again():
    out = R.plan([row(), row("urn:fabric:artifact:B", source="lab", ref="art://s/x.json")])
    assert [w["iri"] for w in out] == ["urn:fabric:artifact:A", "urn:fabric:artifact:B"]
    assert out[0]["pointer"]["handle"] == "collab://item/d/i"


def test_a_pointer_that_names_nothing_is_SKIPPED_not_submitted():
    """Intake reads the artifact THROUGH its pointer, so a row without a source or an id is not a thing that
    can be re-read. Submitting it would spend a run to fail, and — worse on a ninety-record sweep — the
    failure would look like a classifier problem rather than a catalogue one."""
    assert R.plan([{"iri": "urn:x", "pointer": {}}]) == []
    assert R.plan([{"iri": "urn:x", "pointer": {"source": "collab"}}]) == []
    assert R.plan([{"iri": "urn:x", "pointer": {"handle": "collab://item/d/i"}}]) == []


def test_the_producer_and_context_travel_with_the_record():
    """`produced_by` makes the document type a FACT rather than a suggestion, and the context is what keeps
    the record associated. Dropping either would turn a re-read into a downgrade."""
    out = R.plan([{"iri": "urn:x", "title": "m", "pointer": {"source": "lab", "ref": "art://s/m.json"},
                   "produced_by": "transcript_to_minutes", "context": "meeting:m1"}])
    assert out[0]["produced_by"] == "transcript_to_minutes" and out[0]["context"] == "meeting:m1"


def test_the_pace_is_slow_enough_to_share_the_upstream():
    """Ollama Cloud's session limit is one bucket for the whole ACCOUNT, so a burst of ninety
    classifications would starve a live meeting, an eval or a screening. Nothing waits on this sweep."""
    assert R.PACE_S >= 1.0
