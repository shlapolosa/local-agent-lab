"""lab.substrate.meetingapp.channel — the two things the bot says unprompted in a meeting chat.

1. A speaker question is waiting: the NEUTRAL card, posted in the meeting it belongs to (found by the
   chat id the question's continuation carries), remembered so answering can close it.
2. The minutes are done: the summary and counts, for a meeting whose outputs the lab KEPT (the app's
   meetings — a folder-delivered run is announced by the webhook notifier instead).
Both ACK only what is handled; a post that fails stays pending and is reclaimed, like every channel.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_channel.py"""
import asyncio
import json

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import TRANSCRIPT_TO_MINUTES, ApprovalKind, WorkflowStatus
from lab.substrate import approvals
from lab.substrate.meetingapp import channel, registry
from lab.substrate.meetingapp.registry import Meeting

CHAT = "19:meeting_x@thread.v2"
M = Meeting(chat_id=CHAT, organiser_oid="org", organiser_mri="29:org", graph_meeting_id="MSo",
            service_url="https://smba/", tenant_id="t")
RECORDING = "collab://recording/org~MSo/rec-1"
QUESTION = {"question": {"items": [{"label": "SPEAKER_00", "samples": ["secret words"], "seconds": 9, "turns": 1}]},
            "continuation": {"process": "transcript_to_minutes",
                             "inputs": {"chat_id": CHAT, "provider": "soniox-en", "transcript": "art://t/x.json",
                                        "recording": RECORDING}}}


class Poster:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def __call__(self, meeting, card):
        if self.fail:
            raise RuntimeError("bot connector down")
        self.sent.append((meeting.chat_id, card))
        return f"act-{len(self.sent)}"


def ask(r, payload=QUESTION, kind=ApprovalKind.SPEAKER_MAPPING.value):
    return approvals.request(kind, "who is speaking?", payload, "meeting_to_transcript", client=r)


def test_an_open_speaker_question_is_posted_neutral_in_its_meeting_and_remembered():
    r, post = FakeRedis(), Poster()
    registry.save(M, client=r)
    rid = ask(r)
    asyncio.run(channel.approvals_pass(post, client=r))
    (chat, card), = post.sent
    assert chat == CHAT and card["refresh"]["userIds"] == ["29:org"]
    assert "secret words" not in json.dumps(card), "the chat sees no utterance; only the organiser's view does"
    assert registry.card_of(rid, client=r) == (CHAT, "act-1")
    asyncio.run(channel.approvals_pass(post, client=r))
    assert len(post.sent) == 1, "acked: posted once"


def test_a_question_for_a_chat_the_app_is_not_in_is_acked_and_not_posted():
    r, post = FakeRedis(), Poster()
    ask(r)                                             # nothing registered
    ask(r, kind=ApprovalKind.EA_IMPORT.value, payload={})
    asyncio.run(channel.approvals_pass(post, client=r))
    asyncio.run(channel.approvals_pass(post, client=r))
    assert post.sent == []


def test_a_failed_post_is_left_pending_to_be_tried_again():
    r = FakeRedis()
    registry.save(M, client=r)
    ask(r)
    asyncio.run(channel.approvals_pass(Poster(fail=True), client=r))
    r.age_pending(approvals.REQ, channel.CHANNEL, 3600)
    post = Poster()
    asyncio.run(channel.approvals_pass(post, client=r))
    assert len(post.sent) == 1


def finish(r, **outputs):
    channel.ensure(client=r)                    # what the service does at startup
    rid, _ = workflows.submit(TRANSCRIPT_TO_MINUTES.name, {"transcript": "art://t/x.json", "recording": RECORDING,
                                                          "chat_id": CHAT,
                                                          "speaker_map": {"SPEAKER_00": {"tag": "M"}}},
                              "continuation-runner", client=r)
    workflows.mark(rid, WorkflowStatus.DONE.value, client=r, **outputs)
    return rid


KEPT = [{"name": "Meeting.soniox-en.minutes.txt", "ref": "art://s/m.txt", "url": ""}]
SUMMARY = {"decisions": 1, "actions": 2, "speakers": 1, "text": "They agreed to start with the portal."}


def test_finished_minutes_of_an_app_meeting_are_posted_once_in_its_chat():
    r, post = FakeRedis(), Poster()
    registry.save(M, client=r)
    finish(r, chat_id=CHAT, delivered=json.dumps(KEPT), summary=json.dumps(SUMMARY), provider="soniox-en")
    asyncio.run(channel.minutes_pass(post, client=r))
    (chat, card), = post.sent
    assert chat == CHAT and "They agreed to start with the portal." in json.dumps(card)
    asyncio.run(channel.minutes_pass(post, client=r))
    assert len(post.sent) == 1


def test_minutes_delivered_to_a_folder_are_left_to_the_webhook_notifier():
    r, post = FakeRedis(), Poster()
    registry.save(M, client=r)
    folder = [{"name": "x.minutes.txt", "ref": "art://s/m.txt", "url": "https://tenant/x.minutes.txt"}]
    finish(r, chat_id=CHAT, delivered=json.dumps(folder), summary=json.dumps(SUMMARY))
    asyncio.run(channel.minutes_pass(post, client=r))
    assert post.sent == []


def test_a_question_about_another_meetings_recording_is_not_posted_in_this_chat():
    """A submitter names the chat; the recording names the meeting. Only when they agree is anything
    posted — otherwise one meeting's voices would be offered to another meeting's organiser."""
    r, post = FakeRedis(), Poster()
    registry.save(M, client=r)
    elsewhere = QUESTION | {"continuation": {"process": "transcript_to_minutes", "inputs": {
        "chat_id": CHAT, "recording": "collab://recording/other~MSo/rec-9"}}}
    ask(r, payload=elsewhere)
    asyncio.run(channel.approvals_pass(post, client=r))
    assert post.sent == []


def test_minutes_of_another_meetings_recording_are_not_posted_in_this_chat():
    r, post = FakeRedis(), Poster()
    registry.save(M, client=r)
    channel.ensure(client=r)
    rid, _ = workflows.submit(TRANSCRIPT_TO_MINUTES.name, {
        "transcript": "art://t/x.json", "chat_id": CHAT, "recording": "collab://recording/other~MSo/rec-9",
        "speaker_map": {"SPEAKER_00": {"tag": "M"}}}, "continuation-runner", client=r)
    workflows.mark(rid, WorkflowStatus.DONE.value, client=r, chat_id=CHAT, delivered=KEPT, summary=SUMMARY)
    asyncio.run(channel.minutes_pass(post, client=r))
    assert post.sent == []
