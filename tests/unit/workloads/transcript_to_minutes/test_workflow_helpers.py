"""Helpers of the minutes workflow that carry the LANE — the per-provider pipeline a run belongs to."""
from unittest.mock import patch

from lab.platform.contracts import CollabTools
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
        return {"spec_ref": "art://a/b.json"}

    def deliver(provider):
        calls.clear()
        state = {"prose": "hello", "minutes_ref": "art://m/m.json", "meeting": {},
                 "provider": provider}
        # `gateway.call`, not a per-workload `_call`: theseven workloads shared four
        # identical helpers and they now live in one place, so the seam moved with them.
        with patch.object(gateway, "call", fake_call):
            asyncio.run(W._deliver({}, state, "collab://recording/m/r"))
        return [a["name"] for t, a in calls if t == CollabTools.put]

    assert deliver("elevenlabs") == ["2 test-20260907-Meeting Recording.elevenlabs.transcript.md",
                                     "2 test-20260907-Meeting Recording.elevenlabs.minutes.json"]
    assert deliver("munsit") == ["2 test-20260907-Meeting Recording.munsit.transcript.md",
                                 "2 test-20260907-Meeting Recording.munsit.minutes.json"]
    # ...and four lanes therefore produce eight distinct names, not two
    assert not set(deliver("elevenlabs")) & set(deliver("munsit"))
    # a deployment with one provider is untouched
    assert deliver("") == ["2 test-20260907-Meeting Recording.transcript.md",
                           "2 test-20260907-Meeting Recording.minutes.json"]


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
