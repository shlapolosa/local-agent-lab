"""The meetings the app was added to, as the bot learned them when it was added.

Microsoft's recording notification names the organiser and the meeting, never its chat — and the chat
is where everything the app says goes. The bot learns both at once, from the install event and the
meeting details, so this joins them: meeting -> chat, and chat -> what the bot needs to speak there.

Entries EXPIRE (`TTL_S`) and are refreshed whenever the bot hears from the meeting again, so a meeting
nobody uses is forgotten rather than kept forever. Pausing is the organiser's word and survives the
app being re-added; only `set_paused` changes it."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace

from lab.core.collab import ContentHandle, HandleKind
from lab.platform import redis_client
from lab.substrate.mcp.graph import graph_map

__all__ = ["Meeting", "save", "by_chat", "by_meeting", "owner_of", "set_paused", "remember_card", "card_of",
           "record_files", "files_of", "TTL_S"]

TTL_S = 90 * 24 * 3600          # a quarter: longer than any series' gap, shorter than forever
_PREFIX = "meetingapp"


@dataclass(frozen=True)
class Meeting:
    chat_id: str                 # the meeting chat — where cards and minutes are posted
    organiser_oid: str           # the organiser's directory object id (Graph's key, the run's owner)
    organiser_mri: str           # the organiser's Teams id (29:…) — what a card's refresh list matches
    graph_meeting_id: str        # the online meeting id Graph names in its notifications
    service_url: str             # where the Bot Connector accepts this tenant's activities
    tenant_id: str
    paused: bool = False


def _r(client=None):
    return client if client is not None else redis_client.client()


def chat_key(chat_id: str) -> str:
    return f"{_PREFIX}:chat:{chat_id}"


def _meeting_key(organiser_oid: str, graph_meeting_id: str) -> str:
    return f"{_PREFIX}:meeting:{organiser_oid}:{graph_meeting_id}"


def _decode(raw) -> str | None:
    return raw.decode() if isinstance(raw, bytes) else raw


def save(meeting: Meeting, *, client=None) -> None:
    """Record (or refresh) a meeting. An existing PAUSE is kept: re-adding the app is not consent to
    resume a meeting the organiser paused."""
    r = _r(client)
    existing = by_chat(meeting.chat_id, client=r)
    if existing is not None and existing.paused:
        meeting = replace(meeting, paused=True)
    r.set(chat_key(meeting.chat_id), json.dumps(asdict(meeting)), ex=TTL_S)
    r.set(_meeting_key(meeting.organiser_oid, meeting.graph_meeting_id), meeting.chat_id, ex=TTL_S)


def by_chat(chat_id: str, *, client=None) -> Meeting | None:
    raw = _decode(_r(client).get(chat_key(chat_id)))
    return Meeting(**json.loads(raw)) if raw else None


def by_meeting(organiser_oid: str, graph_meeting_id: str, *, client=None) -> Meeting | None:
    r = _r(client)
    chat_id = _decode(r.get(_meeting_key(organiser_oid, graph_meeting_id)))
    return by_chat(chat_id, client=r) if chat_id else None


def owner_of(chat_id: str, recording: str, *, client=None) -> Meeting | None:
    """The registered meeting a run BELONGS to — or None.

    A run names a chat (the submitter's word) and a recording (whose scope is the meeting it came
    from). Only when both point at the SAME registered meeting may anything about the run go to that
    chat: otherwise a submitter could have one meeting's voices offered to another meeting's
    organiser, or its minutes posted in another meeting. One predicate, used wherever the bot shows,
    decides or posts."""
    meeting = by_chat(chat_id, client=client) if chat_id else None
    if meeting is None:
        return None
    try:
        handle = ContentHandle.parse(recording)
        organiser, meeting_id = graph_map.split_meeting_ref(handle.scope)
    except ValueError:
        return None
    if handle.kind is not HandleKind.RECORDING:
        return None
    return meeting if (organiser, meeting_id) == (meeting.organiser_oid, meeting.graph_meeting_id) else None


def set_paused(chat_id: str, paused: bool, *, client=None) -> Meeting | None:
    r = _r(client)
    meeting = by_chat(chat_id, client=r)
    if meeting is None:
        return None
    meeting = replace(meeting, paused=paused)
    r.set(chat_key(chat_id), json.dumps(asdict(meeting)), ex=TTL_S)
    return meeting


def remember_card(approval_id: str, chat_id: str, activity_id: str, *, client=None) -> None:
    """Which message carries an approval's speaker card, so answering it can close that card."""
    _r(client).set(f"{_PREFIX}:card:{approval_id}", json.dumps([chat_id, activity_id]), ex=TTL_S)


def card_of(approval_id: str, *, client=None) -> tuple[str, str] | None:
    raw = _decode(_r(client).get(f"{_PREFIX}:card:{approval_id}"))
    return tuple(json.loads(raw)) if raw else None


MAX_FILES = 60      # a few meetings' worth of lanes per chat — a recurring meeting reuses its chat


def record_files(chat_id: str, files: list[dict], *, client=None) -> None:
    """The documents a meeting's runs KEPT, as the tab lists them: `{name, ref, lane}`. Replaced BY
    NAME — a re-run corrects its own files, and the comparison (rewritten by every lane) stays one row."""
    r = _r(client)
    key = f"{_PREFIX}:files:{chat_id}"
    have = {f["name"]: f for f in files_of(chat_id, client=r)}
    for f in files:
        have[f["name"]] = {"name": f["name"], "ref": f["ref"], "lane": f.get("lane", "")}
    rows = list(have.values())[-MAX_FILES:]
    r.set(key, json.dumps(rows), ex=TTL_S)


def files_of(chat_id: str, *, client=None) -> list[dict]:
    raw = _decode(_r(client).get(f"{_PREFIX}:files:{chat_id}"))
    return json.loads(raw) if raw else []
