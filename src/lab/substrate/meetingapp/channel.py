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
from lab.platform.contracts import (TRANSCRIPT_TO_MINUTES, ApprovalKind, WorkflowStatus, continuation_of,
                                    speaker_prompts)
from lab.substrate import approvals
from lab.substrate.meetingapp import bot, cards, registry
from lab.substrate.meetingapp.registry import Meeting

__all__ = ["CHANNEL", "GROUP", "ensure", "approvals_pass", "minutes_pass"]

CHANNEL = bot.CHANNEL            # the approval channel's consumer group, and the audit log's channel
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
    """The meeting and neutral card for an OPEN speaker question in a meeting the app is in."""
    if st.get("kind") != ApprovalKind.SPEAKER_MAPPING.value:
        return None
    payload = st.get("payload") or {}
    cont = continuation_of(payload)
    chat_id = str((cont.inputs if cont else {}).get("chat_id") or "")
    meeting = registry.by_chat(chat_id, client=client) if chat_id else None
    if meeting is None:
        return None
    return meeting, cards.awaiting(st["request_id"], meeting.organiser_mri,
                                   speakers=len(speaker_prompts(payload)),
                                   lane=str(cont.inputs.get("provider") or ""))


async def approvals_pass(post: Post, *, client=None) -> int:
    posted = 0
    for eid, fields in approvals.channel_events(CHANNEL, CONSUMER, client=client):
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


async def minutes_pass(post: Post, *, client=None) -> int:
    posted = 0
    for eid, fields in workflows.finished_events(GROUP, CONSUMER, client=client):
        rid = fields.get("request_id", "")
        try:
            if fields.get("process") == TRANSCRIPT_TO_MINUTES.name:
                st = workflows.status(rid, client=client)
                kept = [f for f in st.get("delivered") or [] if isinstance(f, dict) and not f.get("url")]
                meeting = registry.by_chat(str(st.get("chat_id") or ""), client=client) if st.get("chat_id") else None
                fresh = _r(client).set(_announced_key(rid), "1", nx=True, ex=registry.TTL_S)
                if st.get("status") == WorkflowStatus.DONE.value and kept and meeting is not None and fresh:
                    summary = st.get("summary") or {}
                    try:
                        await post(meeting, cards.minutes(
                            summary=str(summary.get("text") or ""), decisions=int(summary.get("decisions") or 0),
                            actions=int(summary.get("actions") or 0), files=[f.get("name", "") for f in kept],
                            lane=str(st.get("provider") or "")))
                    except Exception:
                        _r(client).delete(_announced_key(rid))    # say it on the retry
                        raise
                    posted += 1
            workflows.ack_finished(GROUP, eid, client=client)
        except Exception as e:                  # noqa: BLE001
            print(f"[meeting-app] minutes not posted for {rid}, will retry ({type(e).__name__}: {e})", flush=True)
    return posted


def _r(client):
    return client if client is not None else redis_client.client()
