"""Helpers of the minutes workflow that carry the LANE — the per-provider pipeline a run belongs to."""
from unittest.mock import patch

from lab.core.meetings import Speakers
from lab.platform.contracts import CollabTools, SemanticTools
from lab.workloads import gateway
from lab.workloads.transcript_to_minutes import workflow as W


# ---------------------------------------------------------------- lanes must not overwrite lanes
def test_each_lane_delivers_files_named_after_its_own_provider():
    """The failure this prevents is SILENT and destroys data.

    `collab_put` replaces a file of the SAME NAME in the same folder — deliberately, so a re-run
    corrects its own output. Run four providers over one recording and every lane computes the same
    stem from the same recording, so all four write `<stem>.transcript.md`: the last lane to finish
    wins, the other three are gone, nothing errors, and the folder looks exactly as it should.

    So the lane is in the filename. A run with no lane keeps the original names, because a lab
    running one provider must not have its files renamed by a feature it does not use.
    """
    import asyncio

    calls = []

    async def fake_call(cfg, tool, args):
        calls.append((tool, args))
        if tool == CollabTools.item:
            return {"name": "2 test-20260907-Meeting Recording.mp4", "parent_handle": "collab://item/d/F"}
        if tool == CollabTools.put:
            return {"name": args["name"], "handle": "collab://item/d/x", "url": "https://x/y",
                    "bytes": 10}
        return {"ref": "art://a/b.txt"}

    def deliver(provider):
        calls.clear()
        state = {"segments": [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "hello"}],
                 "minutes": {"summary": "maria said hello"},
                 "map": Speakers.from_answer({"SPEAKER_00": {"identity": "maria@x.com"}}),
                 "minutes_ref": "art://m/m.json", "meeting": {}, "provider": provider}
        # `gateway.call`, not a per-workload `_call`: theseven workloads shared four
        # identical helpers and they now live in one place, so the seam moved with them.
        with patch.object(gateway, "call", fake_call):
            asyncio.run(W._deliver({}, state, "collab://recording/m/r"))
        return [a["name"] for t, a in calls if t == CollabTools.put]

    assert deliver("elevenlabs") == ["2 test-20260907-Meeting Recording.elevenlabs.transcript.txt",
                                     "2 test-20260907-Meeting Recording.elevenlabs.minutes.txt"]
    assert deliver("munsit") == ["2 test-20260907-Meeting Recording.munsit.transcript.txt",
                                 "2 test-20260907-Meeting Recording.munsit.minutes.txt"]
    # ...and four lanes therefore produce eight distinct names, not two
    assert not set(deliver("elevenlabs")) & set(deliver("munsit"))
    # a deployment with one provider keeps plain names
    assert deliver("") == ["2 test-20260907-Meeting Recording.transcript.txt",
                           "2 test-20260907-Meeting Recording.minutes.txt"]


# ------------------------------------------------- a label that never spoke needs no attribution
def test_a_silent_label_does_not_have_to_be_identified():
    """The gate must use the SAME rule the question used, or it demands an answer nobody was asked.

    Measured live 8 Sep 2026 on `wfr-4e17b417dd38`. A diarizer emitted two SPEAKER_01 segments with
    EMPTY text — one of them 0.02 seconds long. `Transcript.spoken` correctly kept that label out of
    the digest, so the card asked about SPEAKER_00 only and the organiser answered for SPEAKER_00.
    The minutes run then read the raw transcript, found SPEAKER_01 among its labels, and refused:
    "the transcript uses [\'SPEAKER_01\'], which nobody identified". A human answered every question
    they were asked and the pipeline stopped anyway.

    Fixing the digest without fixing the gate is what left two ends of one rule disagreeing. The
    gate now reads the labels that actually SPEAK; a silent one is neither required nor rejected.
    """
    assert W._speaking_labels([
        {"speaker": "SPEAKER_00", "text": "hello everybody"},
        {"speaker": "SPEAKER_00", "text": ""},
        {"speaker": "SPEAKER_01", "text": ""},
        {"speaker": "SPEAKER_01", "text": "   "},
    ]) == {"SPEAKER_00"}


def test_a_label_that_speaks_is_still_required():
    """The gate\'s purpose survives: a voice that said something must be identified, or the minutes
    would name an anonymous label as a person."""
    assert W._speaking_labels([
        {"speaker": "SPEAKER_00", "text": "hello"},
        {"speaker": "SPEAKER_01", "text": "Alhamdulillah."},
    ]) == {"SPEAKER_00", "SPEAKER_01"}


# ------------------------------------------- what is delivered is what a PERSON asked to be told
def test_the_delivered_files_name_the_people_a_human_tagged__not_the_labels():
    """The defect this closes, measured live 9 Sep 2026 on the 18:26 recording.

    A human answered all three speaker cards, and the file that landed in the meeting's own folder
    still read `SPEAKER_01 (socrateshlapolosa): …` while the summary read "speaker_0 opened the
    meeting". The labelled prose is the MODEL's input — the minutes schema demands labels and the
    gate validates against them — and it was being published verbatim to the reader. One artifact
    serving two audiences; the reader got the model's copy, and the tagging bought them nothing.
    """
    import asyncio
    import json

    put, stored = [], {}

    async def fake_call(cfg, tool, args):
        if tool == CollabTools.item:
            return {"name": "sync.mp4", "parent_handle": "collab://item/d/F", "created": "2026-09-29T07:20:44Z"}
        if tool == CollabTools.put:
            put.append(args)
            return {"name": args["name"], "handle": "h", "url": "u", "bytes": 1}
        if tool == SemanticTools.store_page:
            stored[args["name"]] = args["text"]          # stored AS ITSELF, never wrapped in JSON
            return {"ref": f"art://a/{args['name']}"}
        raise AssertionError(tool)

    state = {
        "segments": [{"speaker": "SPEAKER_00", "start": 3.0, "end": 6.0, "text": "Morning all."},
                     {"speaker": "SPEAKER_00", "start": 6.0, "end": 8.0, "text": "Shall we start?"}],
        "minutes": {"summary": "SPEAKER_00 opened the meeting.", "concepts": [], "decisions": [],
                    "actions": [{"id": "a1", "commitment": "send it", "owner": "SPEAKER_00",
                                 "concerns": []}], "keywords": []},
        "map": Speakers.from_answer({"SPEAKER_00": {"identity": "maria@x.com"}}),
        "minutes_ref": "art://m/labelled.json", "meeting": {}, "provider": "elevenlabs",
    }
    with patch.object(gateway, "call", fake_call):
        out = asyncio.run(W._deliver({}, state, "collab://item/d/rec"))

    transcript = stored["sync.elevenlabs.transcript.txt"]
    minutes = stored["sync.elevenlabs.minutes.txt"]
    # The UTF-8 mark first: SharePoint serves .txt with no charset and a browser then shows Arabic as
    # mojibake (measured 5 Oct 2026) — the mark is what tells every reader the bytes are UTF-8
    assert transcript.startswith("\ufeff") and minutes.startswith("\ufeff")
    # Teams' own layout: title, date, duration, then `Name   m:ss` over the words
    assert transcript.startswith("\ufeffsync\n29 September 2026, 07:20 UTC\n8s\nTranscription: elevenlabs\n\n")
    assert "maria   0:03\nMorning all. Shall we start?" in transcript
    assert "SPEAKER_" not in transcript and "SPEAKER_" not in minutes, "a label reached the reader"
    assert "maria opened the meeting." in minutes and "Owner: maria" in minutes
    # ...and the LABELLED minutes are still what the lab keeps: the gate validated them and the
    # semantic model is keyed on them, so delivery must not have rewritten them
    assert state["minutes"]["summary"] == "SPEAKER_00 opened the meeting."
    assert [a["ref"] for a in put] == ["art://a/sync.elevenlabs.transcript.txt",
                                       "art://a/sync.elevenlabs.minutes.txt"]
    # what the comparison needs to find the sibling lanes beside the same recording
    assert out["beside"]["drive"] == "d" and out["beside"]["lane"] == "elevenlabs"
