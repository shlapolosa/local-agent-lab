"""The meeting notifier: what turns "the minutes exist" into "the meeting knows about them".

The minutes run writes its outputs back into the folder the recording sits in, which makes them
findable — but only by someone who goes looking. The place people actually return to after a meeting
is its own conversation, so that is where a link belongs.

WHY THE LAB DOES NOT POST IT ITSELF. Microsoft Graph refuses to create a chat message with
application permissions — that path exists only for migration — and this lab authenticates as an
application by design (the provider-identity rule: the caller's credential authorises the call to the
MCP, the SERVER's own registration authorises the call to the provider). On-behalf-of is blocked on
identity propagation. So no amount of consent lets `collab_mcp` post as itself, and the only things
that can are a registered bot or something already holding a delegated Teams connection.

So this pushes to a webhook and something with a person's connection posts. That is not a workaround
invented here: it is exactly what `channels/teams.py` already does, and CLAUDE.md sanctions it —
substrate egress, to a fixed configured URL, carrying counts, ids and links and no model content.
The alternative shape, having the low-code flow poll until the minutes finish, was rejected because a
flow sitting in a Do-until for the length of an unknown run is a worse thing to operate than a push.

Deliberately bounded, and each bound is a decision:
  * only `transcript_to_minutes`, and only when it finished DONE — a failed run has nothing to say;
  * only when the run resolved a `chat_id`. An ad-hoc recording has no discoverable meeting, so
    there is no conversation to post to, and inventing a destination is worse than staying quiet;
  * only ids, names and links. No minutes text, no transcript, no speaker identities — the outputs
    live behind the tenant's own permissions and this says where, not what;
  * it never writes to a run, never decides an approval and never retries a delivery.

Run: .venv/bin/python -m lab.substrate.meeting_notifier
"""
from __future__ import annotations

import json
import signal
import sys
import time

from lab.platform import config, workflows
from lab.platform.webhook import post_json
from lab.platform.contracts import TRANSCRIPT_TO_MINUTES, WorkflowStatus

GROUP = "meeting-notifier"
CONSUMER = "1"
BLOCK_MS = 3000            # under the Redis client's socket timeout, like every other consumer here
BACKOFF_S = 5              # after a Redis blip: long enough not to spin, short enough to recover
ANNOUNCED_TTL_S = 86400    # long enough to outlive any retry of one run, short enough not to accumulate

_stop = False


def announcement(state: dict) -> dict | None:
    """What to POST for one finished run, or None when there is nothing to say.

    Pure, so the decision of WHETHER to announce is testable without a Redis or a webhook — which
    matters because "stay quiet" is the common case, not the exception.
    """
    if state.get("status") != WorkflowStatus.DONE.value:
        return None
    chat_id = str(state.get("chat_id") or "").strip()
    delivered = state.get("delivered") or []
    if not chat_id or not delivered:
        return None
    summary = state.get("summary") or {}
    # No `subject`. The meeting's title is free text a person typed, and the minutes run never has
    # it — a continuation is started from a transcript reference, not from a meeting. A field that
    # is always empty invites a message that reads "the minutes for ** are ready", and the
    # destination is the meeting's OWN conversation, where the title is already on screen.
    return {"chat_id": chat_id,
            "request_id": state.get("request_id", ""),
            "files": [{"name": f.get("name", ""), "url": f.get("url", ""),
                       "handle": f.get("handle", "")} for f in delivered],
            # counts, never content: what was decided is in the tenant, behind its own permissions
            "decisions": summary.get("decisions", 0), "actions": summary.get("actions", 0),
            "speakers": summary.get("speakers", 0)}


def handle(entry_id: str, fields: dict, *, webhook: str, client) -> dict | None:
    """One finished run. Returns what was announced, or None.

    ACKS when the work is DONE — announced, or there was never anything to announce. A FAILED SEND is
    deliberately left UNACKED, the way the Teams channel leaves one: the entry stays in this group's
    pending list and `finished_events` reclaims it after a minute, so a webhook outage delays a
    meeting's message rather than losing it. Acking a failure would be the one thing Streams were
    chosen over pub/sub to avoid. Reading `>` means a pending entry blocks nothing behind it.

    An exception never escapes: one meeting that cannot be announced must not stop the rest.
    """
    rid = fields.get("request_id", "")
    try:
        if fields.get("process") != TRANSCRIPT_TO_MINUTES.name:
            return _done(entry_id, client)
        said = announcement(workflows.status(rid, client=client))
        if not said or _already_announced(client, rid):
            # nothing to say, or a reclaimed entry whose ack was lost after a send that DID land —
            # at-least-once delivery with a best-effort guard against saying it twice
            return _done(entry_id, client)
        if webhook:
            post_json(webhook, said)
        else:
            print(f"[notifier] would post: {json.dumps(said)[:200]}", flush=True)
        _mark_announced(client, rid)
        _done(entry_id, client)
        return said
    except Exception as e:                          # noqa: BLE001 — one meeting must not stop the rest
        print(f"[notifier] {rid}: {type(e).__name__}: {e}", flush=True)
        # ...and leave a trace where a person looking at the run will find it, not only on stdout
        _note_failure(client, rid, e)
        return None


def _done(entry_id: str, client) -> None:
    workflows.ack_finished(GROUP, entry_id, client=client)
    return None


def _announced_key(request_id: str) -> str:
    return f"notify:sent:{request_id}"


def _already_announced(client, request_id: str) -> bool:
    return bool(request_id) and bool(client.get(_announced_key(request_id)))


def _mark_announced(client, request_id: str) -> None:
    """Recorded AFTER the send, never before: claiming first would make a failed send look like one
    already delivered, and the retry would skip it."""
    if request_id:
        client.set(_announced_key(request_id), "1", ex=ANNOUNCED_TTL_S)


def _note_failure(client, request_id: str, error: Exception) -> None:
    try:
        workflows.annotate(request_id, client=client,
                           notify_error=f"{type(error).__name__}: {error}"[:300])
    except Exception:                               # noqa: BLE001 — a note is never worth the loop
        pass


def run_once(*, webhook: str = "", client=None, block_ms: int = 0) -> list[dict]:
    r = client or _client()
    events = workflows.finished_events(GROUP, CONSUMER, block_ms=block_ms, count=50, client=r)
    return [s for s in (handle(eid, f, webhook=webhook, client=r) for eid, f in events) if s]


def _client():
    from lab.platform import redis_client
    return redis_client.client()


def main() -> None:
    def _request_stop(*_a):
        global _stop
        _stop = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)
    webhook = config.MEETING_WEBHOOK_URL
    r = _client()
    workflows.ensure_finished_group(GROUP, r)
    print(f"meeting notifier ready  group={GROUP} "
          f"{'webhook configured' if webhook else 'NO webhook (MEETING_WEBHOOK_URL unset) — it will log instead'}",
          flush=True)
    while not _stop:
        # Guarded for the same reason the continuation runner is: a Redis read can time out on a
        # busy machine, and this is the only thing that tells a meeting its minutes exist. A blip
        # costs a log line and a back-off, never the process.
        try:
            run_once(webhook=webhook, client=r, block_ms=BLOCK_MS)
        except Exception as e:                      # noqa: BLE001 — log, back off, keep serving
            print(f"notifier loop error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            time.sleep(BACKOFF_S)
    print("meeting notifier stopped", flush=True)


if __name__ == "__main__":
    main()
