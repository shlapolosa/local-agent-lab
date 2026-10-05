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

import re
from typing import Callable

from lab.core.collab import ContentHandle
from lab.platform import config, workflows
from lab.platform.contracts import MEETING_TO_TRANSCRIPT
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
        if not client_state or value.get("clientState") != client_state:
            continue
        parsed = parse(value)
        if parsed is None or parsed[0] != "recordings":
            continue
        _, organiser, meeting_id, recording_id = parsed
        meeting = registry.by_meeting(organiser, meeting_id, client=client)
        if meeting is None or meeting.paused:
            print(f"[meeting-app] recording not started ({'paused' if meeting else 'meeting not registered'})",
                  flush=True)
            continue
        inputs = {"owner": organiser, "chat_id": meeting.chat_id,
                  "recording": str(ContentHandle.recording(graph_map.meeting_ref(organiser, meeting_id),
                                                          recording_id))}
        rows = submit(MEETING_TO_TRANSCRIPT.name, inputs, REQUESTER,
                      lanes=workflows.lanes_for(MEETING_TO_TRANSCRIPT, inputs, lanes),
                      idempotency_key=f"recording:{recording_id}", client=client)
        started += rows
        print(f"[meeting-app] recording -> {len(rows)} run(s)", flush=True)
    return started
