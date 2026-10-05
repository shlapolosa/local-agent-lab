"""transcript_to_minutes for a meeting that opted in through the MEETING APP.

Such a meeting is known by a `collab://recording/<meeting>/<id>` handle and has no folder the lab may
write into — the meeting app holds no file permission, deliberately. So the transcript, the minutes
and the comparison are KEPT in the lab by reference, and the meeting app posts them in the meeting's
own chat. Nothing is written to anyone's OneDrive. Synthetic text throughout (this repository is public).
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/transcript_to_minutes/test_meeting_app.py"""
import asyncio
from unittest.mock import patch

from lab.core.meetings.model import Speakers
from lab.platform.contracts import CollabTools, SemanticTools, StorageTools
from lab.workloads import gateway
from lab.workloads.transcript_to_minutes import workflow as W

RECORDING = "collab://recording/org~MSoxMTE/rec-1"
VTT = "WEBVTT\n\n00:00:03.000 --> 00:00:08.000\n<v Maria Perez>Shall we start with the portal</v>\n"


def harness():
    calls, stored = [], {}

    async def fake_call(cfg, tool, args):
        calls.append((tool, args))
        if tool == SemanticTools.store_page:
            stored[args["name"]] = args["text"]
            return {"ref": f"art://s/{args['name']}"}
        if tool == StorageTools.read_document:
            return VTT
        raise AssertionError(f"an app meeting must not call {tool}")
    return calls, stored, fake_call


def state(**kw):
    return {"segments": [{"speaker": "SPEAKER_00", "start": 3.0, "end": 8.0, "text": "Shall we start with the portal"}],
            "minutes": {"summary": "they agreed to start with the portal"},
            "map": Speakers.from_answer({"SPEAKER_00": {"tag": "Maria"}}),
            "meeting": {"id": "org~MSoxMTE", "recording": RECORDING, "chat_id": "19:meeting_x@thread.v2"},
            "provider": "soniox-en"} | kw


def test_an_app_meetings_outputs_are_kept_in_the_lab_not_written_to_a_folder():
    calls, stored, fake = harness()
    with patch.object(gateway, "call", fake):
        out = asyncio.run(W._deliver({}, state(), RECORDING))
    assert {t for t, _ in calls} == {SemanticTools.store_page}, "no folder lookup, no upload"
    assert [d["name"] for d in out["delivered"]] == ["Meeting.soniox-en.transcript.txt",
                                                     "Meeting.soniox-en.minutes.txt"]
    assert all(d["ref"].startswith("art://") and not d["url"] for d in out["delivered"])
    assert out["chat_id"] == "19:meeting_x@thread.v2", "the meeting app announces them in that chat"
    assert all(text.startswith(W.BOM) for text in stored.values()), "Arabic must not arrive as mojibake"


def test_an_app_meeting_is_compared_with_the_tenant_transcript_and_the_table_is_kept_too():
    calls, stored, fake = harness()
    with patch.object(gateway, "call", fake):
        delivered = asyncio.run(W._deliver({}, state(), RECORDING))
        got = asyncio.run(W._compare({}, state(reference="art://v/teams.vtt") | delivered))
    assert got["lanes"] == ["soniox-en"] and got["file"]["name"] == "Meeting.comparison.txt"
    assert got["file"]["ref"] == "art://s/Meeting.comparison.txt"
    assert CollabTools.list not in [t for t, _ in calls], "no folder to find sibling lanes in"
