"""Microsoft Graph JSON <-> the collaboration domain. PURE: no I/O, no client, no configuration.

This is the module where correctness lives, which is why it is separated from the transport and
tested alone against captured Graph payloads. Three pieces of Graph knowledge are encoded here and
nowhere else:

* **Handle-safe ids.** A `collab://` handle refuses `/`, `?`, `#` and whitespace, and a Teams
  `onlineMeeting` id is base64 that may contain any of them. So every id the adapter HANDS OUT goes
  through `encode_id` (a marked, reversible escape that leaves an already-safe id untouched, so a
  driveItem id stays readable in a log) and every id it TAKES BACK goes through `decode_id` before
  it reaches a URL. One rule, applied everywhere.
* **A meeting is read per user.** Graph has no "meetings in a window" endpoint: the listable window
  is the organiser's CALENDAR VIEW, and recordings/transcripts live under
  `/users/{user}/onlineMeetings/{meeting}`. So the domain's `Meeting.id` is a MEETING REFERENCE —
  the user and the meeting token together — and a calendar event's token is its JOIN URL, because
  `joinWebUrl` is the only field `/users/{u}/onlineMeetings` can be filtered by. The caller sees one
  opaque id; the adapter can always resolve it.
* **Subscription lifetimes are per resource.** Graph caps `expirationDateTime` differently for each
  resource family (driveItem 42,300 minutes; Teams resources 4,320; Outlook 10,080; directory
  41,760; presence 60) and silently raises anything under 45 minutes. `expiry_for` clamps rather
  than letting a subscription be refused for asking too much.
"""
from __future__ import annotations

import base64
import binascii
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Callable

from lab.core.collab import ChangeType, Drive, DriveItem, MediaKind, MediaRecord, Meeting, Site, Watch

__all__ = ["ENCODED_PREFIX", "encode_id", "decode_id", "meeting_ref", "split_meeting_ref", "site",
           "drive", "drive_item", "meeting", "media_record", "watch", "subscription_body",
           "expiry_for", "max_expiry_minutes", "stamp", "EXPIRY_FLOOR_MINUTES",
           "EXPIRY_MARGIN_MINUTES", "MEDIA_TYPES"]

ENCODED_PREFIX = "b64."
REF_SEPARATOR = "~"
# Anything a `collab://` handle refuses, plus the separator this module composes references with.
_UNSAFE = re.compile(r"[/?#\s~|]")
EXPIRY_FLOOR_MINUTES = 45          # Graph raises anything shorter to this; do it ourselves, visibly
# Ask for slightly LESS than the documented maximum: Graph validates the expiry against ITS clock,
# not this host's, so a maximum-length subscription is refused by any positive skew.
EXPIRY_MARGIN_MINUTES = 10
MEDIA_TYPES = {MediaKind.RECORDING: "video/mp4", MediaKind.TRANSCRIPT: "text/vtt"}

# Ordered because resources overlap: `/users/{id}/drive/root` is a driveItem, `/users/{id}/events` is
# a mailbox, `/users` alone is the directory, and callRecord is NOT the same as callRecording. First
# match wins. Source: https://learn.microsoft.com/graph/api/resources/subscription — "Subscription
# lifetime" table, read 4 Sep 2026 (driveItem/list 42,300; Teams resources incl. callRecording and
# callTranscript 4,320; callRecord 4,230; Outlook 10,080; directory 41,760; presence 60).
_EXPIRY_RULES: tuple[tuple[tuple[str, ...], int], ...] = (
    (("/presence",), 60),
    (("/drive", "/drives"), 42_300),
    (("/lists",), 42_300),
    (("callrecord",), 4_230),          # the call RECORD (CDR); a call RECORDING is 4,320, below
    (("/teams", "/channels", "/chats", "/chat/", "onlinemeetings", "/communications"), 4_320),
    (("/events", "/messages", "/mailfolders", "/contacts"), 10_080),
)
_DIRECTORY_MINUTES, _DEFAULT_MINUTES = 41_760, 4_320


# ----------------------------------------------------------------------------- ids
def encode_id(raw: str) -> str:
    """A provider id made safe for a `collab://` handle — unchanged when it already is, so the common
    case stays readable, and marked when it is not, so decoding is unambiguous."""
    text = str(raw or "")
    if not _UNSAFE.search(text) and not text.startswith(ENCODED_PREFIX):
        return text
    return ENCODED_PREFIX + base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def decode_id(safe: str) -> str:
    """The inverse of `encode_id`. An id reaches here from a handle a CALLER passed back, so a
    malformed one is ordinary input, not an exotic case: it becomes a `ValueError` (the caller
    error it is) rather than a `binascii` or codec traceback escaping the adapter."""
    text = str(safe or "")
    if not text.startswith(ENCODED_PREFIX):
        return text
    body = text[len(ENCODED_PREFIX):]
    try:
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"malformed provider id: {safe!r}") from e


def meeting_ref(user_id: str, meeting_id: str) -> str:
    """`<user>~<meeting>`, both encoded — one opaque token the caller passes back, from which the
    adapter recovers whose meeting it is (Graph reads meetings per user, never tenant-wide)."""
    return f"{encode_id(user_id)}{REF_SEPARATOR}{encode_id(meeting_id)}"


def split_meeting_ref(ref: str) -> tuple[str, str]:
    """`(user_id, meeting_token)`. The token is an onlineMeeting id or a join URL; the repository
    resolves it. An empty user is legal — it means "whoever the deployment reads meetings for"."""
    parts = str(ref or "").split(REF_SEPARATOR)
    if len(parts) != 2:
        raise ValueError(f"malformed meeting reference (want <user>{REF_SEPARATOR}<meeting>): {ref!r}")
    return decode_id(parts[0]), decode_id(parts[1])


# ----------------------------------------------------------------------------- files
def site(js: dict) -> Site:
    return Site(js["id"], js.get("displayName") or js.get("name") or js["id"], js.get("description", ""))


def drive(js: dict, site_id: str = "", owner: str = "") -> Drive:
    """A drive as the domain holds it. `owner` is passed in when the drive was reached THROUGH a
    person (`/users/{id}/drive`), so it names them the way the caller asked for them; otherwise it
    comes from the payload's own `owner.user`. Either way it is an IDENTIFIER the caller can pass
    back to `user_drive()` — never a display name, which would resolve to nobody."""
    return Drive(js["id"], js.get("name") or js["id"], site_id, owner or _principal(js.get("owner")))


def _principal(owner: dict | None) -> str:
    """A drive owner as something ADDRESSABLE: `/users/{id}` accepts a principal name or a directory
    id and nothing else. Graph's `owner.user` often carries only a `displayName`, which would look
    like an answer and then fail every call made with it — so that case reports NO owner."""
    user = (owner or {}).get("user") or {}
    return str(user.get("userPrincipalName") or user.get("email") or user.get("id") or "")


def drive_item(js: dict, drive_id: str = "") -> DriveItem:
    parent = js.get("parentReference") or {}
    # `drive_id` may arrive already encoded (it came from a listing this adapter handed out) while
    # `parentReference.driveId` is always raw — normalise so encoding stays idempotent either way.
    return DriveItem(id=encode_id(js["id"]), name=js.get("name") or js["id"],
                     drive_id=encode_id(decode_id(parent.get("driveId") or drive_id)),
                     folder="folder" in js, size=int(js.get("size") or 0),
                     modified=js.get("lastModifiedDateTime", ""), path=_folder_path(parent))


def _folder_path(parent: dict) -> str:
    """`parentReference.path` is `/drives/{id}/root:/A/B` (or `/drive/root:` at the top) and is
    percent-encoded; the domain wants `A/B` relative to the drive root."""
    raw = str(parent.get("path") or "")
    _, marker, tail = raw.partition("root:")
    return urllib.parse.unquote((tail if marker else raw).strip("/"))


# ----------------------------------------------------------------------------- meetings
def meeting(js: dict, user_id: str = "") -> Meeting:
    """One `Meeting` from either shape Graph offers: an `onlineMeeting`, or a calendar `event` (the
    only listable time window), whose join URL becomes the resolvable token."""
    online = js.get("onlineMeeting") or {}
    token = online.get("joinUrl") or js["id"]
    people = js.get("participants") or {}
    organizer = _person(people.get("organizer") or js.get("organizer") or {})
    attendees = people.get("attendees") if "participants" in js else js.get("attendees")
    return Meeting(id=meeting_ref(user_id, token), subject=js.get("subject", ""), organizer=organizer,
                   start=_when(js, "startDateTime", "start"), end=_when(js, "endDateTime", "end"),
                   participants=_dedupe([organizer, *(_person(a) for a in (attendees or []))]))


def _person(js: dict) -> str:
    """The most human identifier Graph offers for one participant, whichever shape it used."""
    js = js or {}
    user = (js.get("identity") or {}).get("user") or {}
    mail = js.get("emailAddress") or {}
    return (js.get("upn") or mail.get("address") or user.get("displayName") or user.get("id")
            or mail.get("name") or "")


def _dedupe(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _when(js: dict, online_key: str, event_key: str) -> str:
    """`onlineMeeting` reports a UTC instant; an `event` reports `{dateTime, timeZone}` with no
    offset in the string. Only stamp the Z when Graph actually said UTC."""
    if js.get(online_key):
        return str(js[online_key])
    block = js.get(event_key) or {}
    value = str(block.get("dateTime") or "")
    if value and str(block.get("timeZone", "")).upper() == "UTC" and not value.endswith("Z"):
        value += "Z"
    return value


def media_record(js: dict, kind: MediaKind, meeting: str) -> MediaRecord:
    """A `callRecording` or a `callTranscript` — one domain shape, told apart by `kind`. `meeting` is
    the meeting REFERENCE the record was listed under, so the handle can find its way back."""
    kind = MediaKind(kind)
    return MediaRecord(id=encode_id(js["id"]), kind=kind, meeting_id=meeting,
                       created=js.get("createdDateTime", ""),
                       media_type=js.get("contentType") or MEDIA_TYPES[kind],
                       size=int(js.get("size") or 0))


# ----------------------------------------------------------------------------- subscriptions
def watch(js: dict) -> Watch:
    """A Graph `subscription` as the domain's `Watch`. A change type the domain does not model is
    DROPPED rather than guessed at; a subscription that then has none left is malformed and the
    domain object refuses it."""
    known = set(ChangeType)
    events = tuple(ChangeType(c) for c in
                   (t.strip() for t in str(js.get("changeType") or "").split(",")) if c in known)
    return Watch(id=js["id"], resource=js.get("resource", ""),
                 notification_url=js.get("notificationUrl", ""), events=events,
                 expires=js.get("expirationDateTime", ""))


def subscription_body(resource: str, notification_url: str, events: tuple[ChangeType, ...],
                      expires: str) -> dict:
    """The POST body Graph expects for a subscription.

    No `clientState`: that field exists so a RECEIVER can authenticate an incoming notification, and
    the receiver is deliberately not part of this change (a caller-supplied `notification_url` means
    someone else owns the receiving end today). It comes back with the receiver that needs it, rather
    than sitting here as an option nobody takes."""
    return {"resource": resource, "notificationUrl": notification_url,
            "changeType": ",".join(ChangeType(e).value for e in events),
            "expirationDateTime": expires}


def max_expiry_minutes(resource: str) -> int:
    """How long Graph will let a subscription on this resource live."""
    text = str(resource or "").lower()
    for needles, minutes in _EXPIRY_RULES:
        if any(n in text for n in needles):
            return minutes
    return _DIRECTORY_MINUTES if text.strip("/") in ("users", "groups") else _DEFAULT_MINUTES


def expiry_for(resource: str, requested: str = "",
               now: Callable[[], datetime] | None = None) -> str:
    """The expiry to ask Graph for: what the caller wanted, clamped to the resource's maximum (less
    `EXPIRY_MARGIN_MINUTES`, because the maximum is checked against GRAPH's clock) and raised to
    Graph's 45-minute floor. An unstated or unreadable request means "as long as allowed" — a
    subscription refused for asking too much helps nobody."""
    base = (now or (lambda: datetime.now(timezone.utc)))()
    ceiling = base + timedelta(minutes=max_expiry_minutes(resource) - EXPIRY_MARGIN_MINUTES)
    wanted = _parse(requested) or ceiling
    return stamp(max(min(wanted, ceiling), base + timedelta(minutes=EXPIRY_FLOOR_MINUTES)))


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stamp(when: datetime) -> str:
    """The UTC form Graph accepts and returns."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
