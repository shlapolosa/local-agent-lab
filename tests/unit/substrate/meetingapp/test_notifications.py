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
    assert s["key"] == notifications._key(RID), "Graph redelivers; a redelivery must not start a second run"
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


def test_one_entry_that_cannot_be_submitted_does_not_stop_the_next():
    r = FakeRedis()
    registry.save(M, client=r)
    calls = []

    def submit(process, inputs, requester, **kw):
        calls.append(inputs["recording"])
        if len(calls) == 1:
            raise ValueError("invalid input")
        return [{"request_id": "wfr-2"}]
    body = {"value": note(rid="first")["value"] + note(rid="second")["value"]}
    started = notifications.handle(body, client_state=SECRET, submit=submit, lanes=(), client=r)
    assert len(calls) == 2 and started == [{"request_id": "wfr-2"}]


def test_a_real_graph_recording_id_fits_the_front_doors_idempotency_key_limit():
    """Graph's recording ids run past 200 characters; the key was `recording:<id>:<lane>` and EVERY
    lane was refused (ValueError, MAX_KEY) — measured 6 Oct 2026, the first real app meeting ran nothing.
    The key is a digest: short, stable, one per recording."""
    from lab.platform import workflows
    long_id = "ktVizIfGAAAAifB4lQ" + "x" * 230
    r = FakeRedis()
    registry.save(M, client=r)
    started = notifications.handle(note(rid=long_id), client_state=SECRET, lanes=("munsit", "soniox-en"), client=r)
    assert [row["request_id"] for row in started if row.get("request_id")] and not any(row.get("error") for row in started)
    keys = list(r.scan_iter("workflow:idem:*"))
    assert keys and all(len(str(k)) <= workflows.MAX_KEY + 60 for k in keys)
    again = notifications.handle(note(rid=long_id), client_state=SECRET, lanes=("munsit", "soniox-en"), client=r)
    assert all(row["duplicate"] for row in again), "a redelivery is the same runs, not new ones"


def test_a_lane_that_was_refused_is_said_and_not_counted_as_a_run(capsys):
    r = FakeRedis()
    registry.save(M, client=r)

    def submit(process, inputs, requester, **kw):
        return [{"provider": "munsit", "request_id": "wfr-1", "duplicate": False},
                {"provider": "soniox", "request_id": "", "duplicate": False, "error": "ValueError: too long"}]
    notifications.handle(note(), client_state=SECRET, submit=submit, lanes=(), client=r)
    out = capsys.readouterr().out
    assert "1 run(s) started" in out and "soniox REFUSED" in out and "too long" in out


def test_the_run_carries_the_meetings_title_fitted_to_the_contract():
    from dataclasses import replace

    from lab.platform.contracts import MAX_TITLE_CHARS, MEETING_TO_TRANSCRIPT
    r = FakeRedis()
    registry.save(replace(M, title="Portal kickoff " * 20), client=r)
    _, submitted = run(note(), r)
    title = submitted[0]["inputs"]["title"]
    assert title.startswith("Portal kickoff") and len(title) <= MAX_TITLE_CHARS
    MEETING_TO_TRANSCRIPT.validate(submitted[0]["inputs"])


def test_a_meeting_with_no_title_submits_none():
    r = FakeRedis()
    registry.save(M, client=r)
    _, submitted = run(note(), r)
    assert "title" not in submitted[0]["inputs"]
