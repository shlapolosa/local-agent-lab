"""A recording is ready in a meeting the app was added to — so that meeting's run starts.

ONE Graph subscription (`appCatalogs/teamsApps/{id}/installedToOnlineMeetings/getAllRecordings`,
resource-specific consent) covers every meeting the app is in; each notification names the organiser,
the meeting and the recording. Turning one into a submission is mostly a matter of saying NO: a wrong
client secret, a transcript notification (the run fetches the tenant transcript itself), a paused
meeting, and a meeting the bot never saw added — whose chat is therefore unknown — all start nothing.

Submission goes through `workflows.submit_lanes` with `lanes_for`, exactly as the front door does, so a
meeting fans out into the configured provider lanes; the idempotency key is the recording, because
Graph redelivers and a redelivery must not start a second transcription."""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Callable

from lab.core.collab import ContentHandle
from lab.platform import config, workflows
from lab.platform.contracts import MEETING_TO_TRANSCRIPT, fit_title
from lab.substrate.meetingapp import registry
from lab.substrate.mcp.graph import graph_map

__all__ = ["handle", "parse", "REQUESTER"]

REQUESTER = "meeting-app"
# users('<organiser>')/onlineMeetings('<meeting>')/recordings('<recording>') — Graph's own form.
_RESOURCE = re.compile(r"users\('([^']+)'\)/onlineMeetings\('([^']+)'\)/(recordings|transcripts)\('([^']+)'\)")


def parse(value: dict) -> tuple[str, str, str, str] | None:
    """(kind, organiser, meeting, id) from one notification, or None if it is not one we know."""
    m = _RESOURCE.search(str(value.get("resource") or ""))
    return (m.group(3), m.group(1), m.group(2), m.group(4)) if m else None


def handle(body: dict, *, client_state: str, submit: Callable = workflows.submit_lanes,
           lanes=None, client=None) -> list[dict]:
    """Every run started by one notification POST (Graph may batch several). Never raises for a
    single bad entry: Graph retries a whole batch on an error, and one malformed entry must not
    replay the good ones."""
    lanes = config.SPEECH_LANES if lanes is None else lanes
    started = []
    for value in (body or {}).get("value") or []:
        if not client_state or not hmac.compare_digest(str(value.get("clientState") or ""), client_state):
            continue
        parsed = parse(value)
        if parsed is None or parsed[0] != "recordings":
            continue
        _, organiser, meeting_id, recording_id = parsed
        try:
            started += _start(organiser, meeting_id, recording_id, submit, lanes, client)
        except Exception as e:                  # noqa: BLE001 — one entry must not cost the rest of the batch
            print(f"[meeting-app] recording {recording_id} NOT started ({type(e).__name__}: {e})", flush=True)
    return started


def _start(organiser: str, meeting_id: str, recording_id: str, submit: Callable, lanes, client) -> list[dict]:
    meeting = registry.by_meeting(organiser, meeting_id, client=client)
    if meeting is None or meeting.paused:
        print(f"[meeting-app] recording {recording_id} not started "
              f"({'paused' if meeting else 'meeting not registered'})", flush=True)
        return []
    inputs = {"owner": organiser, "chat_id": meeting.chat_id,
              "recording": str(ContentHandle.recording(graph_map.meeting_ref(organiser, meeting_id), recording_id))}
    # The title is fitted, never refused: a meeting's long or odd subject costs its documents their
    # tidy name, not the meeting its minutes.
    if title := fit_title(meeting.title):
        inputs["title"] = title
    rows = submit(MEETING_TO_TRANSCRIPT.name, inputs, REQUESTER,
                  lanes=workflows.lanes_for(MEETING_TO_TRANSCRIPT, inputs, lanes),
                  idempotency_key=_key(recording_id), client=client)
    # A lane that could not be submitted comes back as a ROW with an error, not an exception — so count
    # what started and SAY what was refused. Counting rows once reported "3 run(s)" for three refusals
    # (measured 6 Oct 2026), and the first real app meeting silently ran nothing.
    ran = [row for row in rows if row.get("request_id") and not row.get("error")]
    print(f"[meeting-app] recording {recording_id[:8]}: {len(ran)} run(s) started", flush=True)
    for row in rows:
        if row.get("error"):
            print(f"[meeting-app] recording {recording_id[:8]}: lane {row.get('provider') or '-'} REFUSED "
                  f"({row['error']})", flush=True)
    return rows


def _key(recording_id: str) -> str:
    """The submission's idempotency key: one per recording, and SHORT. Graph's recording ids run past
    200 characters, over the front door's key limit, so the id itself made every lane's key invalid."""
    return "recording:" + hashlib.sha256(recording_id.encode()).hexdigest()[:32]
