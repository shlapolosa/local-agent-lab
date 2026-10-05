"""meeting_to_transcript started by the opt-in MEETING APP rather than a folder watcher.

The app is told about a recording by Microsoft with the meeting it belongs to, so it submits a
`collab://recording/<meeting>/<id>` handle — the meeting is IN the handle — plus the meeting chat's id,
which it knows because it lives in that chat. Nothing has to be searched for: no calendar view, no
matching a file's timestamp against a meeting's. These tests pin that the workload trusts what it was
given and asks only for what it was not.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/meeting_to_transcript/test_meeting_app.py"""
import asyncio

from lab.platform.contracts import MEETING_TO_TRANSCRIPT, ApprovalTools, CollabTools, InputKind, continuation_of
from lab.workloads.meeting_to_transcript import workflow as W

from .test_workflow import OWNER, _run, gw  # noqa: F401 - gw is a fixture

MEETING_REF = "org-oid~MSoxMTE"
RECORDING = f"collab://recording/{MEETING_REF}/rec-1"
CHAT = "19:meeting_abc@thread.v2"


def owning(gw, state):  # noqa: F811
    return asyncio.run(W._owning_meeting({"headers": {}, "mcp_url": "x"}, state))


def test_a_recording_handle_names_its_meeting_so_no_calendar_is_searched(gw):  # noqa: F811
    gw.answers[CollabTools.recordings] = {"items": [{"handle": RECORDING, "created": "2026-10-05T07:43:00Z"}]}
    got = owning(gw, {"owner": OWNER, "recording": RECORDING, "chat_id": CHAT})
    assert got == {"id": MEETING_REF, "chat_id": CHAT, "participants": [], "recorded_at": "2026-10-05T07:43:00Z"}
    assert CollabTools.meetings not in [s for s, _ in gw.calls]


def test_when_the_recording_time_cannot_be_read_the_meeting_is_still_known(gw):  # noqa: F811
    """The time only picks WHICH occurrence's tenant transcript to compare with; losing it must not
    lose the meeting, its chat, or the run."""
    gw.answers[CollabTools.recordings] = RuntimeError("throttled")
    got = owning(gw, {"owner": OWNER, "recording": RECORDING, "chat_id": CHAT})
    assert got["id"] == MEETING_REF and got["chat_id"] == CHAT and got["recorded_at"] == ""


def test_the_chat_the_caller_names_is_where_the_minutes_are_announced(gw):  # noqa: F811
    gw.answers[CollabTools.recordings] = {"items": []}
    gw.answers[CollabTools.transcripts] = {"items": []}
    _run(inputs={"owner": OWNER, "recording": RECORDING, "chat_id": CHAT})
    cont = continuation_of({"continuation": gw.args_for(ApprovalTools.ask)["continuation"]})
    assert cont.inputs["chat_id"] == CHAT


def test_the_process_accepts_the_meeting_chat_as_an_optional_conversation_input():
    field = next(f for f in MEETING_TO_TRANSCRIPT.inputs if f.name == "chat_id")
    assert field.kind is InputKind.CONVERSATION and not field.required
    assert MEETING_TO_TRANSCRIPT.validate({"owner": OWNER, "recording": RECORDING, "chat_id": CHAT})["chat_id"] == CHAT
