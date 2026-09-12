"""`meeting_to_transcript` — a recording becomes a question for the meeting's organiser.

Four deterministic steps and NO agent, deliberately. An agent guessing speakers from
self-introductions would anchor the human on exactly the judgement being asked for, and its failure
mode is a confident wrong identity that the organiser clicks straight through — which is precisely
what this gate exists to prevent.

Everything runs offline: the gateway transport is faked, so no socket, no credential, no provider.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/meeting_to_transcript/
"""
import asyncio
import json

import pytest

from lab.platform.contracts import (MEETING_TO_TRANSCRIPT, ApprovalTools, CollabTools,
                                    SpeechTools, speaker_prompts)
from lab.workloads.meeting_to_transcript import workflow as W

HANDLE = "collab://recording/meeting-1/rec-1"
OWNER = "maria@contoso.com"

TRANSCRIBED = {
    "transcript_ref": "art://t1/meeting.segments.json",
    "duration": 2612.4, "model": "mixed", "languages": [], "code_switched": False, "warnings": [],
    "speakers": [
        {"label": "SPEAKER_00", "seconds": 900.5, "turns": 42,
         "samples": ["خلينا نعمل migration بعد الـ review", "we retire the legacy portal"]},
        {"label": "SPEAKER_01", "seconds": 300.2, "turns": 18, "samples": ["agreed"]},
        {"label": "SPEAKER_02", "seconds": 12.0, "turns": 3, "samples": ["نعم"]},
    ],
}
FETCHED = {"ref": "art://r1/Meeting Recording.mp4", "name": "Meeting Recording.mp4",
           "content_type": "video/mp4", "bytes": 4300237}
ASKED = {"request_id": "apr-abc123", "status": "pending", "asked": 3,
         "review_app": "http://review.invalid"}


class FakeGateway:
    """Records every gateway-MCP call and answers from a script keyed by tool suffix."""

    def __init__(self, **overrides):
        self.answers = {CollabTools.fetch: FETCHED, SpeechTools.transcribe: TRANSCRIBED,
                        ApprovalTools.ask: ASKED} | overrides
        self.calls = []

    async def __call__(self, headers, mcp_url, calls):
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            a = self.answers[suffix]
            if isinstance(a, Exception):
                raise a
            out.append(a)
        return out

    def args_for(self, suffix):
        return next(a for s, a in self.calls if s == suffix)


@pytest.fixture
def gw(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(W.gateway, "call_tools", fake)
    monkeypatch.setattr(W.gateway, "preflight", _ok)
    return fake


async def _ok(*a, **kw):
    return None


def _run(cfg=None, inputs=None):
    return asyncio.run(W.run_workflow(cfg or W.make_cfg(credential="k", languages=("ar", "en")),
                                      inputs or {"owner": OWNER, "recording": HANDLE}))


# ------------------------------------------------------------------ the shape of the run
def test_the_run_ends_by_asking_a_human_and_returns_the_approval(gw):
    out = _run()
    assert out["request_id"] == "apr-abc123" and out["status"] == "pending"
    assert out["recording_ref"] == FETCHED["ref"]
    assert out["transcript_ref"] == TRANSCRIBED["transcript_ref"]
    assert out["review_app"] == "http://review.invalid"
    assert [s["label"] for s in out["speakers"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


def test_the_recording_is_fetched_by_handle_never_by_url(gw):
    _run()
    assert gw.args_for(CollabTools.fetch)["handle"] == HANDLE


def test_every_language_the_meeting_uses_is_passed_as_a_hint(gw):
    """The single most important argument. One declared language is what breaks mid-sentence
    switching, so the run must pass BOTH."""
    _run()
    assert gw.args_for(SpeechTools.transcribe)["languages"] == ["ar", "en"]
    assert gw.args_for(SpeechTools.transcribe)["diarize"] is True


def test_the_transcript_is_passed_on_by_reference_never_inline(gw):
    """An hour of speech is not a workflow message and not a tool argument."""
    _run()
    ask = gw.args_for(ApprovalTools.ask)
    blob = json.dumps(ask, ensure_ascii=False)   # ensure_ascii would escape the Arabic away
    assert TRANSCRIBED["transcript_ref"] in blob
    assert "خلينا نعمل migration" in blob, "samples ARE carried — a human needs them to recognise a voice"
    assert len(blob) < 8000, "but the whole transcript is not"


# ------------------------------------------------------------------ the question a human gets
def test_the_question_asks_about_every_speaker_at_once(gw):
    """The user's decision: ONE decision covering all speakers, not one question per voice."""
    _run()
    ask = gw.args_for(ApprovalTools.ask)
    assert [i["label"] for i in ask["items"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    prompts = speaker_prompts({"question": {"items": ask["items"]}})
    assert prompts[0].seconds == 900.5 and prompts[0].turns == 42
    assert prompts[0].samples[0].startswith("خلينا")


def test_the_prompt_tells_a_person_they_may_use_a_free_tag(gw):
    """Not everyone in the room is in the directory, and a person who does not know they may say so
    will either guess or give up."""
    _run()
    prompt = gw.args_for(ApprovalTools.ask)["prompt"].lower()
    assert "tag" in prompt and ("identity" in prompt or "email" in prompt or "directory" in prompt)


def test_the_organiser_is_named_as_who_is_being_asked(gw):
    _run()
    ask = gw.args_for(ApprovalTools.ask)
    assert OWNER in json.dumps(ask), "the run must record whose question this is"


def test_the_recording_and_transcript_are_offered_to_the_reviewer(gw):
    """A reviewer who cannot tell two voices apart needs to be able to listen."""
    _run()
    artifacts = gw.args_for(ApprovalTools.ask)["artifacts"]
    assert FETCHED["ref"] in artifacts.values() and TRANSCRIBED["transcript_ref"] in artifacts.values()


# ------------------------------------------------------------------ the deterministic gate
def test_a_recording_that_was_not_diarized_fails_rather_than_asking_about_one_voice(gw, monkeypatch):
    """A single speaker for a room of people means separation did not happen. Asking the organiser
    to identify 'SPEAKER_00' for a whole meeting is worse than failing — they would answer it."""
    monkeypatch.setitem(gw.answers, SpeechTools.transcribe, TRANSCRIBED | {"speakers": []})
    with pytest.raises(RuntimeError, match="(?i)no speaker"):
        _run()


def test_a_transcript_with_no_reference_fails_at_the_step_that_produced_it(gw, monkeypatch):
    monkeypatch.setitem(gw.answers, SpeechTools.transcribe, {"speakers": TRANSCRIBED["speakers"]})
    with pytest.raises((KeyError, ValueError, RuntimeError)):
        _run()


def test_a_provider_warning_is_carried_to_the_human_not_swallowed(gw, monkeypatch):
    monkeypatch.setitem(gw.answers, SpeechTools.transcribe,
                        TRANSCRIBED | {"warnings": ["custom vocabulary was dropped"]})
    out = _run()
    assert out["summary"]["warnings"] == ["custom vocabulary was dropped"]


def test_the_summary_says_whether_a_language_switch_was_even_detectable(gw):
    """`code_switched: false` from a provider that reports no language means UNKNOWN, and a summary
    that showed it as 'no' would quietly answer the question this lab exists to ask."""
    out = _run()
    assert out["summary"]["languages_reported"] is False
    assert out["summary"]["code_switched"] is None


def test_when_languages_are_reported_the_summary_states_them(gw, monkeypatch):
    monkeypatch.setitem(gw.answers, SpeechTools.transcribe,
                        TRANSCRIBED | {"languages": ["ar", "en"], "code_switched": True})
    out = _run()
    assert out["summary"]["languages_reported"] is True and out["summary"]["code_switched"] is True


# ------------------------------------------------------------------ contract and governance
def test_the_process_declares_every_output_this_run_produces(gw):
    """Derived from a REAL run rather than a hand-kept list, so the two cannot drift: a field the run
    starts publishing but never declares is invisible to `_result` and to every REST client, and a
    field declared but never produced is a promise nothing keeps.

    `trace_id` is the one exception — the host writes it onto the request hash around the run rather
    than the workflow returning it, so it is asserted separately."""
    produced = set(_run()) | {"trace_id"}
    declared = set(MEETING_TO_TRANSCRIPT.outputs)
    assert declared <= produced, f"declared but never produced: {sorted(declared - produced)}"
    # the run also carries request_id/status for the consumer's own bookkeeping; everything a CLIENT
    # should be able to read must be declared
    client_visible = produced - {"request_id", "status"}
    assert client_visible <= declared, f"produced but undeclared: {sorted(client_visible - declared)}"


def test_preflight_refuses_before_any_work_when_a_tool_is_missing(monkeypatch):
    """A version mismatch must cost nothing — the tools are knowable before the first node runs."""
    async def missing(*a, **kw):
        raise RuntimeError("gateway does not expose ['speech_transcribe']")
    monkeypatch.setattr(W.gateway, "preflight", missing)
    called = []
    monkeypatch.setattr(W.gateway, "call_tools", lambda *a, **kw: called.append(1))
    with pytest.raises(RuntimeError, match="speech_transcribe"):
        _run()
    assert called == [], "nothing may run once the gateway is known to be wrong"


def test_required_tools_are_spelled_from_the_contract_not_as_literals():
    assert set(W.REQUIRED_TOOLS) == {CollabTools.fetch, SpeechTools.transcribe, ApprovalTools.ask}


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


# ------------------------------------------------------------------ the config contract
def test_the_credential_and_trace_context_travel_on_every_gateway_call():
    """One trace across process -> gateway -> MCP, and this workload's own identity on the call."""
    cfg = W.make_cfg(credential="k-123", traceparent="00-abc-def-01", languages=("ar",))
    assert cfg["headers"]["Authorization"] == "Bearer k-123"
    assert cfg["headers"]["traceparent"] == "00-abc-def-01"


def test_no_credential_means_no_authorization_header_rather_than_an_empty_one():
    """An empty bearer would be sent and rejected as malformed; absent is the honest state."""
    assert W.make_cfg().get("headers") == {}


def test_the_graph_is_recorded_on_the_run_so_the_board_can_draw_it(gw, monkeypatch):
    drawn = {}
    monkeypatch.setattr(W.runlog, "update", lambda rid, **kw: drawn.update({rid: kw}))
    monkeypatch.setattr(W.runlog, "span_node", lambda rid, node: __import__("contextlib").nullcontext())
    _run(cfg=W.make_cfg(credential="k", languages=("ar", "en"), run_id="run-1"))
    assert "mermaid" in drawn["run-1"] and "ask_mapping" in drawn["run-1"]["mermaid"]


def test_a_run_that_yields_nothing_fails_loudly(gw, monkeypatch):
    """Silence would look like success and leave nobody asked anything."""
    class Empty:
        def get_outputs(self): return []

    async def no_output(_inputs):
        return Empty()

    monkeypatch.setattr(W, "build_workflow", lambda cfg: type("W", (), {"run": staticmethod(no_output)})())
    with pytest.raises(RuntimeError, match="(?i)no approval"):
        _run()


def test_approving_the_mapping_releases_the_minutes_run(gw):
    """The loop closes here: the approval carries WHAT to start and WHERE to bind the answer, so a
    human answering is the only thing standing between a recording and its minutes."""
    from lab.platform.contracts import TRANSCRIPT_TO_MINUTES, continuation_of
    _run()
    ask = gw.args_for(ApprovalTools.ask)
    cont = continuation_of({"continuation": ask["continuation"]})
    assert cont.process == TRANSCRIPT_TO_MINUTES.name
    assert cont.answer_input == "speaker_map", "the human's answer binds to the minutes run's input"
    assert cont.inputs["transcript"] == TRANSCRIBED["transcript_ref"]
    assert cont.requester == OWNER


# ------------------------------------------------------------------ who the human can PICK
CHAT = "19:meeting_ZmFrZQ@thread.v2"
MEETINGS = {"items": [{"id": "m-other", "subject": "standup", "participants": ["x@contoso.com"]},
                      {"id": "meeting-1", "subject": "weekly sync", "chat_id": CHAT,
                       "participants": ["maria@contoso.com", "sam@contoso.com", ""]}]}
RECS = {"m-other": {"items": [{"handle": "collab://recording/m-other/rec-9"}]},
        "meeting-1": {"items": [{"handle": HANDLE}]}}


def _with_meetings(gw, meetings=MEETINGS, recs=RECS):
    gw.answers[CollabTools.meetings] = meetings

    async def call(headers, mcp_url, calls):
        out = []
        for suffix, args in calls:
            gw.calls.append((suffix, args))
            if suffix == CollabTools.recordings:
                out.append(recs.get(args.get("meeting_id"), {"items": []}))
                continue
            a = gw.answers[suffix]
            if isinstance(a, Exception):
                raise a
            out.append(a)
        return out
    return call


ITEM_HANDLE = "collab://item/b!drive/01FILE"        # what a folder-watching producer actually sends


def _with_item_match(gw, item_created="2026-09-07T08:13:20Z",
                     rec_created="2026-09-07T08:13:25.877286Z", other="2026-09-07T02:00:00Z"):
    """A provider answering as the real one does: a drive file, and meetings whose own recordings
    were created at their own instants."""
    gw.answers[CollabTools.meetings] = MEETINGS
    gw.answers[CollabTools.item] = {"id": "01FILE", "name": "rec.mp4", "created": item_created}
    recs = {"m-other": {"items": [{"handle": "collab://recording/m-other/r9", "created": other}]},
            "meeting-1": {"items": [{"handle": "collab://recording/meeting-1/r1", "created": rec_created}]}}

    async def call(headers, mcp_url, calls):
        out = []
        for suffix, args in calls:
            gw.calls.append((suffix, args))
            out.append(recs.get(args.get("meeting_id"), {"items": []})
                       if suffix == CollabTools.recordings else gw.answers[suffix])
        return out
    return call


def test_a_drive_file_is_matched_to_its_meeting_by_when_the_provider_made_each(gw, monkeypatch):
    """The case that had NEVER worked. A producer watching a folder sends `collab://item/...`; the
    provider's meeting recordings are `collab://recording/...`. The two can never be equal, so the
    handle match silently found nothing on every real run — an empty speaker picker and no chat to
    post the minutes back to.

    Matched on the two objects' own creation instants instead. Measured live: the callRecording said
    08:13:25.877Z and the drive file said 08:13:20Z, five seconds apart. Never on the file NAME — a
    provider's naming is a vendor detail this side of the port must not read."""
    monkeypatch.setattr(W.gateway, "call_tools", _with_item_match(gw))
    out = _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})
    assert out["candidates"] == [{"identity": "maria@contoso.com", "display": ""},
                                 {"identity": "sam@contoso.com", "display": ""}]


def test_the_chat_id_of_the_matched_meeting_reaches_the_minutes_run(gw, monkeypatch):
    """Which is the whole point of resolving it: without a chat id the minutes are written beside the
    recording and nobody is told."""
    monkeypatch.setattr(W.gateway, "call_tools", _with_item_match(gw))
    _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})
    assert gw.args_for(ApprovalTools.ask)["continuation"]["inputs"]["chat_id"] == CHAT


def test_a_meeting_is_matched_however_LONG_it_was(gw, monkeypatch):
    """THE defect, measured live on 12 Sep 2026: the drive file said 14:01:38Z and the provider's
    recording object said 14:02:54Z — 77 seconds apart, against a 60-second window, so the match was
    refused. The right meeting was nearest by a factor of 3,300 (the next candidate was three days
    away) and it was thrown out over 17 seconds.

    The gap is not noise, it is the MEETING'S LENGTH: OneDrive creates the file when recording
    STARTS and the provider creates its object when recording STOPS. A symmetric tolerance was
    therefore structurally wrong — it silently refused every meeting longer than a minute, which is
    every real one. The consequences were both halves of the same lookup: an empty speaker picker,
    and no `chat_id`, so the minutes were written beside the recording and nobody was told.
    """
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, item_created="2026-09-12T14:01:38Z",
                                         rec_created="2026-09-12T14:02:54.668Z"))
    assert _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})["candidates"]


def test_an_hour_long_meeting_is_matched_too(gw, monkeypatch):
    """The 77-second case is a 90-second test meeting. A real one runs an hour, and its gap is an
    hour — so a window chosen to fit the measurement would have failed the actual use case."""
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, item_created="2026-09-12T10:00:00Z",
                                         rec_created="2026-09-12T11:00:30Z"))
    assert _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})["candidates"]


def test_a_recording_that_stopped_BEFORE_this_file_started_is_not_its_meeting(gw, monkeypatch):
    """Direction is evidence, and it is what a symmetric window threw away. A recording object made
    before this file existed cannot be this file's: the file appears when recording begins. This is
    also what keeps back-to-back meetings apart — the earlier meeting's object is behind, not near."""
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, item_created="2026-09-12T11:00:00Z",
                                         rec_created="2026-09-12T10:30:00Z"))
    assert _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})["candidates"] == []


def test_a_small_clock_disagreement_between_the_two_providers_still_matches(gw, monkeypatch):
    """Two systems, two clocks. A few seconds the 'wrong' way is skew, not evidence of a different
    meeting, and refusing over it would reintroduce the defect in miniature."""
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, item_created="2026-09-12T14:00:05Z",
                                         rec_created="2026-09-12T14:00:00Z"))
    assert _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})["candidates"]


def test_a_recording_made_at_a_quite_different_time_is_not_claimed(gw, monkeypatch):
    """Nothing at all beats the wrong meeting: offering another meeting's participants would put
    strangers in front of the human as if the lab knew they were there."""
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, rec_created="2026-09-08T09:30:00Z"))
    assert _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})["candidates"] == []


def test_the_nearest_recording_wins_not_the_first_one_close_enough(gw, monkeypatch):
    """Both are inside the window; only one is right. Taking the first would make the answer depend
    on calendar order rather than on the evidence."""
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_item_match(gw, other="2026-09-07T08:13:50Z"))   # m-other: 30s off
    out = _run(inputs={"owner": OWNER, "recording": ITEM_HANDLE})             # meeting-1: 5s off
    assert out["candidates"] == [{"identity": "maria@contoso.com", "display": ""},
                                 {"identity": "sam@contoso.com", "display": ""}]


def test_the_meeting_that_owns_this_recording_supplies_the_people_to_pick_from(gw, monkeypatch):
    """Matched by HANDLE, never by parsing the recording's filename — a provider's naming is a vendor
    detail this side of the collaboration port must not know, and a wrong match would put the wrong
    people in front of the human, which is worse than offering nobody."""
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    out = _run()
    assert out["candidates"] == [{"identity": "maria@contoso.com", "display": ""},
                                 {"identity": "sam@contoso.com", "display": ""}], "blank entries dropped"
    assert gw.args_for(ApprovalTools.ask)["candidates"] == out["candidates"], "and they reach the human"


def test_the_meetings_are_asked_about_concurrently_but_answered_in_calendar_order(gw, monkeypatch):
    """The lookup asks up to ten meetings "do you own this recording", and the questions are
    independent — so they go out together instead of one round trip after another, which on a 22 s
    run is most of it.

    The ORDER of the answers is not negotiable, though: the provider's list is "most recent first",
    so the first MATCH in that order wins, never the first call to come back. Otherwise which meeting
    a recording belongs to would depend on which request happened to be quicker."""
    slow_first = {"m-other": {"items": [{"handle": HANDLE}]},          # both claim it; m-other is
                  "meeting-1": {"items": [{"handle": HANDLE}]}}        # first in the provider's order
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw, recs=slow_first))
    out = _run()
    assert out["candidates"] == [{"identity": "x@contoso.com", "display": ""}], "the earlier meeting"
    asked = [a["meeting_id"] for s, a in gw.calls if s == CollabTools.recordings]
    assert asked == ["m-other", "meeting-1"], "every candidate is asked, not just up to the match"


def test_a_recording_no_meeting_claims_offers_nobody_rather_than_guessing(gw, monkeypatch):
    monkeypatch.setattr(W.gateway, "call_tools",
                        _with_meetings(gw, recs={"meeting-1": {"items": [{"handle": "collab://x/y/z"}]}}))
    assert _run()["candidates"] == []


def test_the_run_still_succeeds_when_the_lookup_is_not_available(gw):
    """The tools are NOT in REQUIRED_TOOLS on purpose: a deployment that does not grant them should
    degrade to no picker, not be refused by preflight. `gw` has no answer for them, so the call
    raises — exactly what an ungranted tool does."""
    out = _run()
    assert out["candidates"] == [] and out["approval_id"] == ASKED["request_id"]
    assert out["speakers"], "and the question itself is unaffected"


def test_the_lookup_tools_are_not_required():
    assert CollabTools.meetings not in W.REQUIRED_TOOLS
    assert CollabTools.recordings not in W.REQUIRED_TOOLS
    assert CollabTools.fetch in W.REQUIRED_TOOLS, "fetching the recording IS required"


def test_the_owning_meeting_is_kept_not_just_its_participants(gw, monkeypatch):
    """It was already being resolved here and thrown away, which left the rest of the pipeline with
    no way to name the meeting — the minutes run ended up deriving one from the transcript's FILE
    NAME. One lookup now yields both the people to offer and the meeting to carry."""
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    out = _run()
    cont = gw.args_for(ApprovalTools.ask)["continuation"]
    assert cont["inputs"]["recording"] == HANDLE, "the handle rides to the minutes run"
    assert cont["inputs"]["transcript"] and cont["inputs"]["owner"] == OWNER


def test_the_recording_handle_is_what_carries_the_meeting():
    """Its SCOPE is the meeting id, so carrying the handle needs no new lookup and no new tool."""
    from lab.core.collab import ContentHandle
    assert ContentHandle.parse(HANDLE).scope == "meeting-1"


def test_a_run_with_no_resolvable_meeting_still_carries_the_recording(gw):
    """`gw` cannot answer collab_meetings, so nothing resolves — the continuation must still carry
    the handle, because the minutes run can name the meeting from it even when this lookup failed."""
    _run()
    inputs = gw.args_for(ApprovalTools.ask)["continuation"]["inputs"]
    assert inputs["recording"] == HANDLE
    assert not inputs["chat_id"], "and no conversation is invented for a meeting nobody could name"


# ------------------------------------------------------------------ the seam to the minutes run
def test_the_conversation_to_announce_in_crosses_the_approval(gw, monkeypatch):
    """The ONLY path by which the minutes run can learn where to announce itself. It is a
    continuation: it is started from a transcript reference and never sees the meeting, so a chat id
    it does not receive here cannot be recovered later at any price. This run resolved the meeting
    for the picker anyway, so carrying it costs nothing and needs no second lookup."""
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    _run()
    assert gw.args_for(ApprovalTools.ask)["continuation"]["inputs"]["chat_id"] == CHAT


def test_the_continuation_is_something_the_minutes_run_would_actually_accept(gw, monkeypatch):
    """The seam this pipeline broke on once: both halves passed their own tests while the inputs one
    produced were not the inputs the other could take. So validate what THIS run emits against the
    OTHER process's own contract, with the human's answer bound as the runner would bind it."""
    from lab.platform.contracts import TRANSCRIPT_TO_MINUTES, continuation_of
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    _run()
    cont = continuation_of({"continuation": gw.args_for(ApprovalTools.ask)["continuation"]})
    answered = dict(cont.inputs) | {cont.answer_input: {"SPEAKER_00": {"tag": "a vendor"}}}
    validated = TRANSCRIPT_TO_MINUTES.validate(answered)
    assert validated["chat_id"] == CHAT and validated["recording"] == HANDLE


# ------------------------------------------------------------------ the lane vs the label
def test_the_continuation_carries_the_LANE_not_the_transcripts_own_label(gw, monkeypatch):
    """Two namespaces that look like one, and only one provider tells them apart.

    A LANE is a registry key — `munsit`, `elevenlabs`, `assemblyai`, `soniox`, `soniox-en` — and it is
    what `ProcessSpec.validate` accepts. A transcript's `provider` is a DESCRIPTIVE label of the
    rendering it produced: `soniox-english`, `soniox-original`, `soniox-translation`. For three of the
    four providers the two strings are identical, so the code could substitute one for the other and
    nothing complained for months.

    Measured live 12 Sep 2026: the soniox lane's speaker card was approved and the continuation
    refused itself with `provider must be one of [...], not 'soniox-english'`. Three lanes delivered
    their minutes to the meeting chat and the fourth silently produced nothing — the approval was
    answered, and what it released was an error message nobody was watching.
    """
    gw.answers[SpeechTools.transcribe] = dict(gw.answers[SpeechTools.transcribe],
                                              provider="soniox-english")
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    _run(inputs={"owner": OWNER, "recording": HANDLE, "provider": "soniox-en"})
    asked = gw.args_for(ApprovalTools.ask)
    assert asked["continuation"]["inputs"]["provider"] == "soniox-en", \
        "the continuation must name a lane the process contract accepts"


def test_the_card_still_shows_the_rendering_the_human_is_looking_at(gw, monkeypatch):
    """The descriptive label is not noise — four cards for one meeting arrive together and the person
    answering has to tell them apart, and `soniox-english` says more than `soniox-en`. So the fix is
    to carry BOTH, not to replace one with the other."""
    gw.answers[SpeechTools.transcribe] = dict(gw.answers[SpeechTools.transcribe],
                                              provider="soniox-english")
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    _run(inputs={"owner": OWNER, "recording": HANDLE, "provider": "soniox-en"})
    assert "soniox-english" in gw.args_for(ApprovalTools.ask)["subject"]


def test_a_run_with_no_lane_asks_the_continuation_for_no_lane(gw, monkeypatch):
    """A deployment running ONE provider submits without naming a lane, and the continuation must not
    invent one from the transcript's label — `provider` is optional, and an absent lane is the honest
    answer rather than a guess that might not be a registry key at all."""
    gw.answers[SpeechTools.transcribe] = dict(gw.answers[SpeechTools.transcribe],
                                              provider="soniox-original")
    monkeypatch.setattr(W.gateway, "call_tools", _with_meetings(gw))
    _run(inputs={"owner": OWNER, "recording": HANDLE})
    assert gw.args_for(ApprovalTools.ask)["continuation"]["inputs"]["provider"] == ""
