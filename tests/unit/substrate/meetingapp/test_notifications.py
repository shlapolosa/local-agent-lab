"""lab.substrate.meetingapp.notifications — a recording is ready, so the meeting's run starts.

One Graph subscription covers every meeting the app was added to; each notification names the
organiser, the meeting and the recording. This turns one into a submission — or into nothing, which
is the common case worth pinning: a wrong secret, a transcript notification, a paused meeting, or a
meeting the bot never saw added must all start nothing.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_notifications.py"""
from fixtures.fakes import FakeRedis
from lab.core.collab import ContentHandle, HandleKind
from lab.substrate.meetingapp import notifications, registry
from lab.substrate.meetingapp.registry import Meeting
from lab.substrate.mcp.graph import graph_map

SECRET = "s3cret"
ORG, MID, RID = "5f48f64f-21d4-411a-afe7-72026aea94ed", "MSo1ZjQ4", "ktVizIfG"
M = Meeting(chat_id="19:meeting_x@thread.v2", organiser_oid=ORG, organiser_mri="29:org",
            graph_meeting_id=MID, service_url="https://smba/", tenant_id="t")


def note(kind="recordings", state=SECRET, rid=RID):
    return {"value": [{"subscriptionId": "s", "changeType": "created", "clientState": state,
                       "resource": f"users('{ORG}')/onlineMeetings('{MID}')/{kind}('{rid}')"}]}


def run(body, r, lanes=()):
    submitted = []

    def submit(process, inputs, requester, *, lanes=(), idempotency_key=None, **kw):
        submitted.append({"process": process, "inputs": inputs, "requester": requester, "lanes": lanes,
                          "key": idempotency_key})
        return [{"provider": "", "request_id": "wfr-1", "duplicate": False}]
    started = notifications.handle(body, client_state=SECRET, submit=submit, lanes=lanes, client=r)
    return started, submitted


def test_a_recording_in_a_registered_meeting_starts_one_run_with_its_chat():
    r = FakeRedis()
    registry.save(M, client=r)
    started, submitted = run(note(), r, lanes=("munsit", "soniox-en"))
    assert len(started) == 1 and len(submitted) == 1
    s = submitted[0]
    assert s["process"] == "meeting_to_transcript" and s["requester"] == "meeting-app"
    handle = ContentHandle.parse(s["inputs"]["recording"])
    assert handle.kind is HandleKind.RECORDING and handle.id == RID
    assert graph_map.split_meeting_ref(handle.scope) == (ORG, MID)
    assert s["inputs"]["owner"] == ORG and s["inputs"]["chat_id"] == M.chat_id
    assert s["key"] == f"recording:{RID}", "Graph redelivers; a redelivery must not start a second run"
    assert s["lanes"] == ("munsit", "soniox-en"), "lanes fan out exactly as through the front door"


def test_a_notification_with_the_wrong_secret_starts_nothing():
    r = FakeRedis()
    registry.save(M, client=r)
    assert run(note(state="guess"), r) == ([], [])


def test_a_transcript_notification_starts_nothing_because_the_run_fetches_it_itself():
    r = FakeRedis()
    registry.save(M, client=r)
    assert run(note(kind="transcripts"), r) == ([], [])


def test_a_paused_meeting_starts_nothing():
    r = FakeRedis()
    registry.save(M, client=r)
    registry.set_paused(M.chat_id, True, client=r)
    assert run(note(), r) == ([], [])


def test_a_meeting_the_bot_never_saw_added_starts_nothing_rather_than_a_run_with_no_chat():
    assert run(note(), FakeRedis()) == ([], [])


def test_a_malformed_resource_is_skipped_not_raised():
    r = FakeRedis()
    registry.save(M, client=r)
    body = {"value": [{"clientState": SECRET, "resource": "users/x/somethingElse"}, *note()["value"]]}
    started, _ = run(body, r)
    assert len(started) == 1
