"""The COLLABORATION domain's value objects — the ubiquitous language for files and meetings.

A collaboration provider holds a small, stable set of things, whoever the provider is: SITES (a
place a team's work lives) hold DRIVES (a document library), which hold DRIVE ITEMS (folders and
files); MEETINGS produce MEDIA RECORDS (a recording or a transcript — one shape, distinguished by
its `kind`, because everything the lab does with them is the same: name it, fetch it, store it);
and a WATCH is a subscription that asks the provider to notify us when something changes. A listing
comes back as a PAGE: some items and an opaque cursor.

Everything here is frozen and hashable, so a domain object can be a dict key, an accumulator entry
or a set member without anyone defending against mutation, and every object enforces its own
invariants at construction (no id, no object).

CONTENT HANDLES are the load-bearing idea. Content never travels inline (a recording is hundreds of
megabytes) and a provider's own download link is a short-lived URL with a credential in its query
string. So a listing mints a `collab://<kind>/<scope>/<id>` handle — two ids and the kind, nothing
else — which is safe to log, trace, hand to an agent and pass back later to fetch the bytes. It is
modelled on `lab.platform.contracts.ArtifactRef`: parseable, round-tripping, frozen. A handle that
contained a URL would defeat the whole arrangement, so construction refuses one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, Iterator, TypeVar

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "clamp_limit", "HandleKind", "ContentHandle", "Site", "Drive",
           "DriveItem", "Meeting", "MediaKind", "MediaRecord", "ChangeType", "Watch", "Page"]

# A listing's result is read by an agent, so the page size is capped in ONE place — the port — and
# every adapter and tool clamps through it rather than trusting a caller's number.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: int | None = None) -> int:
    """The page size a caller actually gets: the default when unset, never above `MAX_LIMIT`, never
    below one. `int(limit)` raises on nonsense, which is a caller error worth surfacing."""
    return DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))


def _require_id(what: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"a {what} needs a non-empty id")


# ----------------------------------------------------------------------------- content handles
_SCHEME = "collab://"
_NOT_AN_ID = re.compile(r"[/?#\s]")     # a path separator, a query, a fragment or any whitespace


class HandleKind(StrEnum):
    """What a handle points at — which decides how the bytes are fetched."""
    ITEM = "item"                 # a file in a drive:      scope = drive id,   id = item id
    RECORDING = "recording"       # a meeting recording:    scope = meeting id, id = record id
    TRANSCRIPT = "transcript"     # a meeting transcript:   scope = meeting id, id = record id


@dataclass(frozen=True)
class ContentHandle:
    """`collab://<kind>/<scope>/<id>` — an opaque, parseable reference to fetchable content.

    `scope` is whatever the content lives in (a drive for a file, a meeting for a recording or a
    transcript) and `id` is the content itself. `str(handle)` round-trips through `parse`.

    A handle carries IDS ONLY — never a URL, never a credential. Provider download links are
    pre-signed and short-lived; one in a handle would leak into a log, a trace and an agent's
    context and would be stale by the time it was used. Construction refuses anything that looks
    like one."""

    kind: HandleKind
    scope: str
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", HandleKind(self.kind))
        for field in ("scope", "id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"a content handle needs a non-empty {field}")
            if _NOT_AN_ID.search(value):
                raise ValueError(f"a content handle carries ids only, never a URL or a credential "
                                 f"({field}={value!r})")

    @classmethod
    def item(cls, drive_id: str, item_id: str) -> "ContentHandle":
        return cls(HandleKind.ITEM, drive_id, item_id)

    @classmethod
    def recording(cls, meeting_id: str, record_id: str) -> "ContentHandle":
        return cls(HandleKind.RECORDING, meeting_id, record_id)

    @classmethod
    def transcript(cls, meeting_id: str, record_id: str) -> "ContentHandle":
        return cls(HandleKind.TRANSCRIPT, meeting_id, record_id)

    @staticmethod
    def is_handle(src: Any) -> bool:
        """The cheap syntactic check (a path or an `art://` ref is not a handle)."""
        return isinstance(src, str) and src.startswith(_SCHEME)

    @classmethod
    def parse(cls, text: str) -> "ContentHandle":
        if not cls.is_handle(text):
            raise ValueError(f"not a content handle: {text!r}")
        parts = text[len(_SCHEME):].split("/")
        if len(parts) != 3:
            raise ValueError(f"malformed content handle (want {_SCHEME}<kind>/<scope>/<id>): {text!r}")
        kind, scope, ident = parts
        if kind not in set(HandleKind):
            raise ValueError(f"unknown content handle kind {kind!r} (one of {[k.value for k in HandleKind]})")
        return cls(HandleKind(kind), scope, ident)      # __post_init__ enforces the ids themselves

    def __str__(self) -> str:
        return f"{_SCHEME}{self.kind.value}/{self.scope}/{self.id}"


# ----------------------------------------------------------------------------- files
@dataclass(frozen=True)
class Site:
    """A place a team's work lives — the unit a provider grants access to, and the unit the lab is
    granted per-site access to where the provider supports it."""

    id: str
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_id("site", self.id)


@dataclass(frozen=True)
class Drive:
    """A document library inside a site (`site_id` is empty for a drive reached on its own)."""

    id: str
    name: str
    site_id: str = ""

    def __post_init__(self) -> None:
        _require_id("drive", self.id)


@dataclass(frozen=True)
class DriveItem:
    """A folder or a file in a drive. `path` is the folder it sits in, relative to the drive root
    ("" is the root); `modified` is an ISO-8601 UTC timestamp as the provider reports it."""

    id: str
    name: str
    drive_id: str
    folder: bool = False
    size: int = 0
    modified: str = ""
    path: str = ""

    def __post_init__(self) -> None:
        _require_id("drive item", self.id)

    @property
    def handle(self) -> ContentHandle:
        """The handle its bytes are fetched by. A folder has none — it holds no content."""
        if self.folder:
            raise ValueError(f"a folder has no content to fetch: {self.name!r}")
        return ContentHandle.item(self.drive_id, self.id)


# ----------------------------------------------------------------------------- meetings
@dataclass(frozen=True)
class Meeting:
    """One online meeting. `participants` are the provider's identifiers for who attended — the
    starting point for attributing what was said, never the answer on its own (one device in a room
    is one participant)."""

    id: str
    subject: str = ""
    organizer: str = ""
    start: str = ""
    end: str = ""
    participants: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id("meeting", self.id)
        object.__setattr__(self, "participants", tuple(self.participants))


class MediaKind(StrEnum):
    """What a meeting produced. Every value is also a `HandleKind`, so a record can always name its
    own content."""
    RECORDING = "recording"
    TRANSCRIPT = "transcript"


@dataclass(frozen=True)
class MediaRecord:
    """A recording OR a transcript of a meeting — ONE shape, distinguished by `kind`, because the
    lab treats both identically: list it, name it by handle, fetch it into the store. `media_type`
    is the provider's MIME type when it declares one, `size` its byte count when it knows it."""

    id: str
    kind: MediaKind
    meeting_id: str
    created: str = ""
    media_type: str = ""
    size: int = 0

    def __post_init__(self) -> None:
        _require_id("media record", self.id)
        object.__setattr__(self, "kind", MediaKind(self.kind))

    @property
    def handle(self) -> ContentHandle:
        return ContentHandle(HandleKind(self.kind.value), self.meeting_id, self.id)


# ----------------------------------------------------------------------------- change notifications
class ChangeType(StrEnum):
    """The changes a watch can ask to hear about."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass(frozen=True)
class Watch:
    """A change-notification subscription: the provider POSTs to `notification_url` when one of
    `events` happens to `resource`, until `expires` (ISO-8601 UTC).

    It is a durable object on the PROVIDER's side that outlives the run that created it, and it is
    egress to a caller-supplied URL — which is why creating one is a write verb, granted separately."""

    id: str
    resource: str
    notification_url: str
    events: tuple[ChangeType, ...]
    expires: str = ""

    def __post_init__(self) -> None:
        _require_id("watch", self.id)
        if not (self.notification_url or "").strip():
            raise ValueError("a watch needs a notification url to notify")
        events = tuple(ChangeType(e) for e in self.events)
        if not events:
            raise ValueError("a watch needs at least one change to listen for")
        object.__setattr__(self, "events", events)


# ----------------------------------------------------------------------------- paging
T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a listing: the items, and an OPAQUE cursor to ask for the next page with (`None`
    on the last page — a provider's continuation token is never parsed, only echoed back)."""

    items: tuple[T, ...] = ()
    cursor: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "cursor", (self.cursor or "").strip() or None)

    @property
    def more(self) -> bool:
        """Whether asking again with `cursor` would return anything."""
        return self.cursor is not None

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
