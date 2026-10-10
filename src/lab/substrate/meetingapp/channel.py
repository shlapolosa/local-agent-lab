"""The two things the bot says UNPROMPTED in a meeting chat.

1. **A speaker question is waiting.** The approval channel `teams-app` (its own consumer group, so it
   sees every request beside the review app and the other channels) — the NEUTRAL card, posted in the
   meeting the question belongs to, found by the chat id its continuation carries. Remembered, so the
   organiser's answer can close that very card for everyone.
2. **The minutes are done.** The finished-runs stream — summary and counts, for a meeting whose
   outputs the lab KEPT. A run that delivered into a folder has addresses a person can open, and the
   webhook notifier announces those; posting them here too would announce the same minutes twice.

Each pass ACKS only what it handled. A post that fails stays pending and is reclaimed by the shared
readers (`channel_events`, `finished_events`), exactly as every other channel does — a Bot Connector
outage delays a card, it never loses one. The reads are non-blocking; the service calls a pass on a
short interval inside its own event loop, because `streams.serve` owns signals and the bot's web server
already does."""
from __future__ import annotations

from typing import Awaitable, Callable

from lab.platform import redis_client, workflows
from lab.platform.contracts import (TRANSCRIPT_TO_MINUTES, ApprovalAudience, WorkflowStatus,
                                    continuation_of, speaker_prompts)
from lab.core.meetings import render
from lab.substrate import approvals, artifacts, meeting_notifier
from lab.substrate.meetingapp import bot, cards, registry
from lab.substrate.meetingapp.registry import Meeting

__all__ = ["CHANNEL", "GROUP", "ensure", "approvals_pass", "minutes_pass"]

CHANNEL = bot.CHANNEL            # the approval channel's consumer group, and the audit log's channel
AUDIENCE = ApprovalAudience.OWNER      # it announces questions about somebody's RECORDING
GROUP = "meeting-app"            # the finished-runs consumer group
CONSUMER = "1"
Post = Callable[[Meeting, dict], Awaitable[str]]


def ensure(*, client=None) -> None:
    """Create both consumer groups at STARTUP. The finished-runs group starts at "now" — a fresh
    listener must not announce every run in history — so it has to exist before the runs it should
    see finish; creating it lazily at the first read would miss whatever finished in between."""
    workflows.ensure_finished_group(GROUP, client)
    approvals.ensure_groups(client)


def _question_target(st: dict, client) -> tuple[Meeting, dict] | None:
    """The meeting and neutral card for an OPEN speaker question that belongs to a meeting the app is in
    — by the SAME test the bot applies before showing or deciding anything (`bot.question_meeting`)."""
    meeting = bot.question_meeting(st, client=client)
    if meeting is None:
        return None
    payload = st.get("payload") or {}
    cont = continuation_of(payload)
    return meeting, cards.awaiting(st["request_id"], meeting.organiser_mri,
                                   speakers=len(speaker_prompts(payload)),
                                   lane=str((cont.inputs if cont else {}).get("provider") or ""))


async def approvals_pass(post: Post, *, client=None) -> int:
    posted = 0
    # An OWNER channel, declared rather than implied. Its own test (`question_meeting`) is tighter
    # and already drops everything that is not a speaker question for a meeting it is in — so this
    # changes nothing today and costs one HGETALL less per vocabulary card. It is declared because
    # "every notifier states its audience" is only an invariant if it has no quiet exception: a
    # future steward kind carrying a chat-owning payload would otherwise post into a meeting.
    for eid, fields in approvals.channel_events(CHANNEL, CONSUMER, audience=AUDIENCE, client=client):
        try:
            target = _question_target(approvals.status(fields.get("request_id", ""), client=client), client)
            if target is not None:
                meeting, card = target
                activity_id = await post(meeting, card)
                registry.remember_card(fields["request_id"], meeting.chat_id, activity_id, client=client)
                posted += 1
            approvals.ack(CHANNEL, eid, client=client)
        except Exception as e:                  # noqa: BLE001 — one meeting must not stop the rest
            print(f"[meeting-app] question not posted, will retry ({type(e).__name__}: {e})", flush=True)
    return posted


def _announced_key(request_id: str) -> str:
    return f"meetingapp:announced:{request_id}"


async def minutes_pass(post: Post, *, store=None, client=None) -> int:
    posted = 0
    for eid, fields in workflows.finished_events(GROUP, CONSUMER, client=client):
        rid = fields.get("request_id", "")
        try:
            if fields.get("process") == TRANSCRIPT_TO_MINUTES.name:
                st = workflows.status(rid, client=client)
                _, kept = meeting_notifier.partition(st.get("delivered"))
                inputs = st.get("inputs") or {}
                meeting = registry.owner_of(str(st.get("chat_id") or ""), str(inputs.get("recording") or ""),
                                            client=client)
                if st.get("status") == WorkflowStatus.DONE.value and kept and meeting is not None:
                    # what the meeting tab lists — recorded before the post, so a failed post loses no file
                    recording = str(inputs.get("recording") or "")
                    registry.record_files(meeting.chat_id, [{"name": f.get("name", ""), "ref": f.get("ref", ""),
                                                              "lane": str(st.get("provider") or "")}
                                                             for f in kept if f.get("ref")],
                                          recording=recording, client=client)
                    _rebuild_comparison(meeting, recording, str(inputs.get("reference") or ""),
                                        store=store, client=client)
                # the marker is claimed only for a run THIS sink announces, and released if the post fails
                if (st.get("status") == WorkflowStatus.DONE.value and kept and meeting is not None
                        and _r(client).set(_announced_key(rid), "1", nx=True, ex=registry.TTL_S)):
                    summary = st.get("summary") or {}
                    try:
                        await post(meeting, cards.minutes(
                            summary=str(summary.get("text") or ""), decisions=int(summary.get("decisions") or 0),
                            actions=int(summary.get("actions") or 0), files=[f.get("name", "") for f in kept],
                            lane=str(st.get("provider") or "")))
                    except Exception:
                        _r(client).delete(_announced_key(rid))                 # say it on the retry
                        raise
                    posted += 1
            workflows.ack_finished(GROUP, eid, client=client)
        except Exception as e:                  # noqa: BLE001
            print(f"[meeting-app] minutes not posted for {rid}, will retry ({type(e).__name__}: {e})", flush=True)
    return posted


TRANSCRIPT_SUFFIX = ".transcript.txt"
BOM = "\ufeff"


def _rebuild_comparison(meeting: registry.Meeting, recording: str, reference: str, *, store=None,
                        client=None) -> None:
    """ONE comparison per recording, across EVERY lane kept for it. A kept lane can only compare itself
    (it has no folder to find its siblings in) and each lane rewrites the same file, so the tab held the
    last lane's row alone; the meeting app knows every lane it recorded, so it rebuilds the table here.
    BEST EFFORT: the minutes are posted and the files listed whether or not a comparison can be made."""
    if not reference:
        return
    try:
        store = store if store is not None else artifacts.store()
        chat_id, title = meeting.chat_id, meeting.title or "Meeting"
        rec = registry.recording_key(recording)
        lanes = {f["lane"]: store.get(f["ref"]).decode("utf-8-sig")
                 for f in registry.files_of(chat_id, client=client)
                 if f.get("rec") == rec and f["name"].endswith(TRANSCRIPT_SUFFIX) and f.get("lane")}
        table = render.compare_lanes(store.get(reference).decode("utf-8-sig"), lanes, title=title)
        if table is None or not lanes:
            return
        name = f"{render.file_stem(title)}.comparison.txt"
        ref = store.put(name, (BOM + table).encode(), "text/plain; charset=utf-8")
        registry.record_files(chat_id, [{"name": name, "ref": ref, "lane": ""}],
                              recording=recording, client=client)
    except Exception as e:                      # noqa: BLE001 — a comparison never costs the minutes
        print(f"[meeting-app] comparison not rebuilt ({type(e).__name__}: {e})", flush=True)


def _r(client):
    return client if client is not None else redis_client.client()
