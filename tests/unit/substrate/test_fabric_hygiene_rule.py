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


def test_a_lab_record_whose_PRODUCER_IS_UNKNOWN_is_kept_for_a_person_to_decide():
    """The rule must never withdraw what it cannot explain, which is what its own docstring already
    promises — "deliberately NARROW … a rule that withdrew a business case would be worse than the defect
    it fixes". `spec is None` meant the opposite: an unresolvable producer was read as workings.

    Measured 12 Oct 2026 against the live catalogue: 66 records were `source=lab` with an EMPTY
    `produced_by` — every synthesised decision-record draft the fabric has ever made, because the draft's
    `catalog_upsert` omitted the field the source record's upsert passes. The rule called all 66 working
    files. Nothing had withdrawn them only because `fabric_hygiene` reaches records through their OPEN
    DRAFT-REVIEW CARD and these have none; the first person to give it catalogue-wide reach — which
    `semantic_catalog_list` now makes a one-line change — would have withdrawn the fabric's own products."""
    assert H.is_working_file({"pointer": {"source": "lab", "ref": "art://s/x.json"}, "produced_by": ""}) is False
    assert H.is_working_file({"pointer": {"source": "lab", "ref": "art://s/x.json"}}) is False
    assert H.is_working_file(lab("art://s/x.json", process="a_process_that_does_not_exist")) is False


def test_a_SYNTHESISED_DRAFT_is_the_product_not_a_working_file():
    """`artifact_intake` declares no `products`, and "declares no products" is read as "everything it
    leaves behind is workings" — true for `meeting_to_transcript`, whose outputs really are transcripts,
    and false here. The synthesised decision record IS the artifact the fabric made (FR-4 Synthesize); it
    is what the draft-review card asks a person about."""
    assert H.is_working_file(lab("art://s/01ABC.d1.decision-record.json", process="artifact_intake")) is False


def test_a_per_lane_segments_file_is_still_a_working_file():
    """The population the hygiene pass is actually for, and the one the loosened rule must not lose: 22
    pending records measured 12 Oct 2026, `produced_by=transcript_to_minutes`, one per speech provider for
    the same recording. Only `minutes.json` is that process's product."""
    assert H.is_working_file(lab("art://s/rec.munsit.segments.json")) is True
    assert H.is_working_file(lab("art://s/rec.minutes.json")) is False


def test_a_working_file_with_NO_open_card_is_found_too():
    """The reach gap, measured 12 Oct 2026. This script matches an open draft-review CARD to a record and
    judges only what it matched, so a record that entered the lifecycle without a card — or whose card was
    already decided — stays pending for ever, invisible to the one pass that exists to catch it. Live: 22
    per-lane `.segments.json` records, `produced_by=transcript_to_minutes`, one per speech provider for the
    same recording, none of them with a card.

    Reported separately from the carded ones because the ACT is different and smaller: there is no decision
    to decline, so no actor is needed and nothing a person did is being overridden. The record is simply
    withdrawn from a lifecycle it should never have entered."""
    carded = lab("art://s/a.segments.json")
    orphan = lab("art://s/b.segments.json")
    product = lab("art://s/c.minutes.json")
    draft = lab("art://s/d.decision-record.json", process="artifact_intake")
    rows = [{**carded, "iri": "urn:a"}, {**orphan, "iri": "urn:b"},
            {**product, "iri": "urn:c"}, {**draft, "iri": "urn:d"}]
    found = H.unreachable_workings(rows, carded={"urn:a"})
    assert [r["iri"] for r in found] == ["urn:b"], "only the uncarded working file"


def test_the_uncarded_pass_never_reaches_a_record_a_person_is_deciding():
    """A record WITH an open card belongs to the carded path, which declines the card as well as
    withdrawing the record. Withdrawing it from under an open card would leave a person holding a question
    about something already gone."""
    r = {**lab("art://s/a.segments.json"), "iri": "urn:a"}
    assert H.unreachable_workings([r], carded={"urn:a"}) == []
    assert [x["iri"] for x in H.unreachable_workings([r], carded=set())] == ["urn:a"]
