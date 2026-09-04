"""`GraphCollabRepository` — the Microsoft Graph adapter for `lab.core.collab.CollabRepository`.

It composes the four modules beside it (`graph_auth` for the credential, `graph_rest` for the wire,
`graph_map` for the shapes, `graph_probe` for the meaning) and adds only what is genuinely a Graph
decision: which URL a verb is, which id must be resolved first, and which refusals this DEPLOYMENT
makes on its own account rather than relaying from the tenant.

Three of those decisions are worth stating, because they are not obvious from the port:

* **Meetings are read per user.** Graph has no "meetings in a window" endpoint. The listable window
  is a user's CALENDAR VIEW, and recordings and transcripts hang off
  `/users/{user}/onlineMeetings/{meeting}`. So a `Meeting.id` is a meeting REFERENCE (`graph_map`),
  the calendar's join URL is resolved to a real meeting id on first use and remembered, and a
  deployment names whose calendar it reads with `GRAPH_MEETING_USER` — an absent one is a
  configuration refusal that says so, not a 400 from Graph.
* **A subscription is egress the lab authorises, not the tenant.** `watch()` refuses any destination
  whose ORIGIN (scheme + host, compared as parsed URLs, never as a string prefix — `https://flow.example`
  must not admit `https://flow.example.evil.com`) is not in `GRAPH_NOTIFICATION_ALLOWLIST`, and an
  EMPTY allowlist refuses everything, because a caller-supplied notification URL is an exfiltration
  lever and this is a write verb granted separately from reading. The expiry is clamped to Graph's
  per-resource maximum before asking. The same reasoning bounds WHOSE meetings may be read:
  `GRAPH_MEETING_USER`/`GRAPH_MEETING_USERS` is a bound, not merely a default, so an `organizer`
  argument cannot reach every mailbox the app-only token can see.
* **The tenant-wide meeting feeds stay behind a switch.** Verified against live documentation
  (Sep 2026): the Teams Graph APIs stopped being metered on 25 Aug 2025, so the per-meeting path
  this adapter uses needs no billing configuration at all. `GRAPH_ALLOW_METERED` therefore gates
  what is still worth gating — `/communications/onlineMeetings/getAllRecordings|getAllTranscripts`
  and subscriptions on them: beta-only, tenant-wide, and unbounded in blast radius.

Every failure leaves through `_call`, which turns a transport-level `GraphError` into the domain's
typed refusal via `graph_probe` — so no caller of this class ever sees a status code.

One thing to know about the cursor: it is Graph's own `@odata.nextLink`, which for a meeting listing
embeds the user's UPN (`/users/chair@lab.example/calendarView?…`). It is opaque to the domain but not
opaque to a reader, and it travels to an agent — the gateway's PII guardrail scans it like any other
text. That is a deliberate trade for a cursor Graph will accept back verbatim, not an oversight.
"""
from __future__ import annotations

import urllib.parse
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

from lab.core.collab import (CAPABILITIES, ChangeType, CollabNotConfigured, CollabThrottled,
                             CollabUnavailable, ContentHandle, ContentStream, Drive, DriveItem,
                             HandleKind, MediaKind, MediaRecord, Meeting, Page, Site, Watch)
from lab.platform import config
from lab.substrate.artifacts import CHUNK          # the one home for "how much is moved at a time"
from lab.substrate.mcp.graph import graph_auth, graph_map, graph_probe
from lab.substrate.mcp.graph.graph_rest import Content, GraphClient, GraphError

__all__ = ["GraphCollabRepository", "build", "DEFAULT_WINDOW_DAYS"]

DEFAULT_WINDOW_DAYS = 30           # how far back an unstated meeting window reaches
RESOLVED_CACHE = 512               # join URL -> meeting id, bounded: this object outlives every call
_LOOKAHEAD_DAYS = 1                # …and how far forward, so a meeting today is included
_PROBE_MEETING = "probe"           # a meeting id that cannot exist: the deep probe wants the ANSWER
# A probe that gets 400/404 reached the resource: Graph understood the request and did not refuse it
# on authorisation grounds, which is the only thing a probe is asking.
_PROBE_REACHED = (400, 404)
_EVENT_FIELDS = "id,subject,start,end,organizer,attendees,isOnlineMeeting,onlineMeeting"


def _origin(url: str) -> tuple[str, str]:
    """A URL's scheme and host, lower-cased — what an allow-list must compare. Prefix matching on the
    raw string would admit `https://flow.example.evil.com/` for an entry of `https://flow.example`,
    which is exactly the lookalike-host attack the allow-list exists to stop."""
    parts = urllib.parse.urlsplit(str(url or ""))
    return parts.scheme.lower(), parts.netloc.lower()


def _seg(value: str) -> str:
    """One id as a URL path segment: decoded back to what Graph issued, then quoted whole (a site id
    carries commas, a drive id an exclamation mark, a meeting id base64 padding)."""
    return urllib.parse.quote(graph_map.decode_id(value), safe="")


class GraphCollabRepository:
    """The port, over Microsoft Graph. Everything it needs is injected: the client (which owns the
    credential), the token source (for the roles claim the shallow probe reads), this deployment's
    policy, and a clock."""

    def __init__(self, client: GraphClient, tokens, *, meeting_user: str = "",
                 meeting_users: tuple[str, ...] = (), allow_metered: bool = False,
                 notification_allowlist: tuple[str, ...] = (), max_fetch_bytes: int = 0,
                 now: Callable[[], datetime] | None = None) -> None:
        self.client, self.tokens = client, tokens
        self.meeting_user = meeting_user
        # Whose meetings may be read at all. The default user is IN the set, so a deployment that
        # names only GRAPH_MEETING_USER is bounded to that one mailbox rather than to every mailbox
        # the app-only token can reach.
        self.meeting_users = tuple(meeting_users) or ((meeting_user,) if meeting_user else ())
        self.allow_metered = allow_metered
        self.notification_allowlist = tuple(notification_allowlist)
        self.max_fetch_bytes = max_fetch_bytes
        self._now = now or (lambda: datetime.now(timezone.utc))
        # Bounded on purpose: the container binds this repository as a SINGLETON in a long-lived
        # server, so an unbounded dict keyed on every join URL ever seen grows for the life of the
        # process. The values are immutable ids, so evicting the oldest costs at most one lookup.
        self._resolved: OrderedDict[tuple[str, str], str] = OrderedDict()

    # ------------------------------------------------------------------ capabilities
    def capabilities(self, deep: bool = False) -> dict[str, CollabUnavailable | None]:
        try:
            table = graph_probe.capabilities_from_roles(self.tokens.roles())
        except CollabUnavailable as e:                # no credential at all: one story, every row
            return {c: CollabUnavailable(c, e.reason, e.remedy) for c in CAPABILITIES}
        if deep:
            for capability, already in list(table.items()):
                if already is None:                  # only probe what the roles claim allows
                    table[capability] = self._probe(capability)
        return table

    def _probe(self, capability: str) -> CollabUnavailable | None:
        """One cheap live call per area — it catches what a roles claim cannot: a missing Teams
        application access policy, a tenant switch, a per-site grant that reaches nothing."""
        try:
            path, params = self._probe_call(capability)
            self.client.get(path, params)
            return None
        except GraphError as e:
            if e.status in _PROBE_REACHED:
                return None
            refused = graph_probe.refusal(e.status, e.code, e.detail, capability, e.retry_after)
            if isinstance(refused, CollabThrottled):
                # A deep probe is eight calls in a burst, so being throttled is likely — and the
                # table is typed `CollabUnavailable | None`, which is what renders a remedy.
                return CollabUnavailable(capability, refused.sentence,
                                         "the deep probe was throttled; re-run it shortly")
            return refused
        except CollabUnavailable as e:                # the lab's own side (no configured user)
            return e

    def _probe_call(self, capability: str) -> tuple[str, dict | None]:
        if capability in graph_probe.POLICY_CAPABILITIES:
            user = _seg(self._user(""))
            if capability == "meetings":
                since, until = self._window("", "")
                return f"/users/{user}/calendarView", {"startDateTime": since, "endDateTime": until, "$top": 1}
            return f"/users/{user}/onlineMeetings/{_PROBE_MEETING}/{capability}", None
        return {"sites": ("/sites/root", None),
                "drives": ("/sites/root/drives", {"$top": 1}),
                "items": ("/sites/root/drive/root/children", {"$top": 1}),
                "content": ("/sites/root/drive/root", None),
                "watches": ("/subscriptions", {"$top": 1})}[capability]

    # ------------------------------------------------------------------ files
    def sites(self, query: str = "", limit: int | None = None, cursor: str | None = None) -> Page[Site]:
        # Graph has no plain list of sites: `search` is the listing, and `*` is "everything visible".
        items, nxt = self._call("sites", self.client.paged, "/sites", {"search": query or "*"}, cursor, limit)
        return Page(tuple(graph_map.site(i) for i in items), nxt)

    def drives(self, site_id: str, limit: int | None = None, cursor: str | None = None) -> Page[Drive]:
        items, nxt = self._call("drives", self.client.paged, f"/sites/{_seg(site_id)}/drives",
                                None, cursor, limit)
        return Page(tuple(graph_map.drive(i, site_id) for i in items), nxt)

    def user_drive(self, user_id: str) -> Drive:
        """One person's own drive. Deliberately NOT bounded the way meetings are: `GRAPH_MEETING_USERS`
        bounds whose CALENDAR may be read, and a drive is a files capability whose ceiling is the
        Files grant itself (narrow it in Entra with `Files.SelectedOperations.Selected` if a tenant
        needs less). The person may be a directory id or a principal name — both are one path
        segment once quoted."""
        if not str(user_id or "").strip():
            raise ValueError("a user drive needs the person whose drive it is — pass a directory id "
                             "or a principal name, not an empty string")
        js = self._call("drives", self.client.get, f"/users/{_seg(user_id)}/drive")
        return graph_map.drive(js, owner=user_id)

    def items(self, drive_id: str, path: str = "", limit: int | None = None,
              cursor: str | None = None) -> Page[DriveItem]:
        root = f"/drives/{_seg(drive_id)}/root"
        folder = f"{root}:/{urllib.parse.quote(path.strip('/'), safe='/')}:" if path.strip("/") else root
        items, nxt = self._call("items", self.client.paged, f"{folder}/children", None, cursor, limit)
        return Page(tuple(graph_map.drive_item(i, drive_id) for i in items), nxt)

    def item(self, handle: ContentHandle) -> DriveItem:
        if handle.kind is not HandleKind.ITEM:
            raise ValueError(f"only a file handle has drive metadata, not {handle.kind.value}: {handle}")
        js = self._call("items", self.client.get, f"/drives/{_seg(handle.scope)}/items/{_seg(handle.id)}")
        return graph_map.drive_item(js, handle.scope)

    # ------------------------------------------------------------------ content
    def content(self, handle: ContentHandle) -> Content:
        """The bytes as a FILE-LIKE plus its type and size — what `Store.put_stream` wants, so a
        recording travels from Graph into the store without ever being materialised.

        The size ceiling is applied HERE rather than in the transport, because only this class knows
        which capability was attempted and therefore which one to report as unavailable."""
        capability = self._capability(handle)
        path, params = self._content_call(handle)
        content = self._call(capability, self.client.stream, path, params)
        if self.max_fetch_bytes and content.size > self.max_fetch_bytes:
            content.fileobj.close()
            raise CollabUnavailable(
                capability,
                f"the object is {content.size} bytes, over this deployment's "
                f"{self.max_fetch_bytes}-byte ceiling",
                "raise GRAPH_MAX_FETCH_BYTES if the store can hold it, or fetch a smaller artifact")
        return content

    def open(self, handle: ContentHandle) -> ContentStream:
        """The port's verb: the same stream, chunked — and CLOSED however the caller leaves it, so
        abandoning a half-read recording does not leak the socket on a long-lived server. Graph's
        own `Content-Type` and `Content-Length` travel with it, so the caller stores what the
        provider actually said instead of guessing from the handle."""
        content = self.content(handle)
        return ContentStream(self._chunks(content.fileobj), content.content_type, content.size)

    @staticmethod
    def _chunks(body) -> Iterator[bytes]:
        try:
            while True:
                chunk = body.read(CHUNK)
                if not chunk:
                    return
                yield chunk
        finally:
            body.close()

    @staticmethod
    def _capability(handle: ContentHandle) -> str:
        return "content" if handle.kind is HandleKind.ITEM else handle.kind.value + "s"

    def _content_call(self, handle: ContentHandle) -> tuple[str, dict | None]:
        if handle.kind is HandleKind.ITEM:
            return f"/drives/{_seg(handle.scope)}/items/{_seg(handle.id)}/content", None
        kind = MediaKind(handle.kind.value)
        path = f"{self._meeting_path(handle.scope)}/{kind.value}s/{_seg(handle.id)}/content"
        # A transcript is delivered in whatever format is asked for; WebVTT is the one a reader wants.
        return path, ({"$format": graph_map.MEDIA_TYPES[kind]} if kind is MediaKind.TRANSCRIPT else None)

    # ------------------------------------------------------------------ meetings
    def meetings(self, since: str = "", until: str = "", organizer: str = "",
                 limit: int | None = None, cursor: str | None = None) -> Page[Meeting]:
        """The calendar view of one user, mapped to meetings. Only events that ARE online meetings
        are returned — an ordinary room booking has no recording to fetch — so a page can be shorter
        than `limit` while still reporting a cursor."""
        user = self._user(organizer)
        start, end = self._window(since, until)
        params = {"startDateTime": start, "endDateTime": end, "$select": _EVENT_FIELDS}
        items, nxt = self._call("meetings", self.client.paged,
                                f"/users/{_seg(user)}/calendarView", params, cursor, limit)
        online = [i for i in items if i.get("isOnlineMeeting")]
        return Page(tuple(graph_map.meeting(i, user) for i in online), nxt)

    def recordings(self, meeting_id: str, limit: int | None = None, cursor: str | None = None) -> Page[MediaRecord]:
        return self._media(meeting_id, MediaKind.RECORDING, limit, cursor)

    def transcripts(self, meeting_id: str, limit: int | None = None, cursor: str | None = None) -> Page[MediaRecord]:
        return self._media(meeting_id, MediaKind.TRANSCRIPT, limit, cursor)

    def _media(self, meeting_id: str, kind: MediaKind, limit, cursor) -> Page[MediaRecord]:
        capability = f"{kind.value}s"
        path = f"{self._meeting_path(meeting_id)}/{capability}"
        items, nxt = self._call(capability, self.client.paged, path, None, cursor, limit)
        return Page(tuple(graph_map.media_record(i, kind, meeting_id) for i in items), nxt)

    def _meeting_path(self, ref: str) -> str:
        user, token = graph_map.split_meeting_ref(ref)
        user = self._user(user)
        return f"/users/{_seg(user)}/onlineMeetings/{_seg(self._resolve(user, token))}"

    def _resolve(self, user: str, token: str) -> str:
        """A calendar event knows only the JOIN URL; `/users/{u}/onlineMeetings` can be filtered by
        exactly that. Resolved once per (user, url) and remembered, so listing then fetching several
        recordings costs one lookup, not one per file."""
        if not token.startswith("http"):
            return token
        key = (user, token)
        if key in self._resolved:
            self._resolved.move_to_end(key)
        else:
            # An OData string literal escapes a quote by doubling it. Both halves of a meeting
            # reference come back from the caller, so an unescaped one would let a caller widen the
            # filter to somebody else's meeting.
            js = self._call("meetings", self.client.get, f"/users/{_seg(user)}/onlineMeetings",
                            {"$filter": "joinWebUrl eq '{}'".format(token.replace("'", "''"))})
            found = js.get("value") or []
            if not found:
                raise CollabUnavailable("meetings", f"no online meeting matches {token}",
                                        "check the meeting still exists and that the application "
                                        "access policy covers its organiser")
            self._resolved[key] = found[0]["id"]
            while len(self._resolved) > RESOLVED_CACHE:
                self._resolved.popitem(last=False)
        return self._resolved[key]

    def _user(self, given: str) -> str:
        """Whose meetings to read — and whether this deployment permits reading them at all. The
        app-only token can reach every mailbox the Teams application access policy covers, so the
        configured user(s) are a BOUND on `organizer`, not merely its default."""
        user = given or self.meeting_user
        if not user:
            raise CollabNotConfigured(
                "GRAPH_MEETING_USER",
                "set GRAPH_MEETING_USER (or pass an organizer): Microsoft Graph reads meetings per "
                "user, so a meeting call must name whose meetings to read")
        if user not in self.meeting_users:
            raise CollabUnavailable(
                "meetings", f"{user} is not a mailbox this deployment reads meetings from",
                "add it to GRAPH_MEETING_USERS (GRAPH_MEETING_USER is the single-mailbox form)")
        return user

    def _window(self, since: str, until: str) -> tuple[str, str]:
        now = self._now()
        return (since or graph_map.stamp(now - timedelta(days=DEFAULT_WINDOW_DAYS)),
                until or graph_map.stamp(now + timedelta(days=_LOOKAHEAD_DAYS)))

    # ------------------------------------------------------------------ watches (the write side)
    def watches(self, limit: int | None = None, cursor: str | None = None) -> Page[Watch]:
        items, nxt = self._call("watches", self.client.paged, "/subscriptions", None, cursor, limit)
        return Page(tuple(graph_map.watch(i) for i in items), nxt)

    def watch(self, resource: str, notification_url: str, events: tuple[ChangeType, ...],
              expires: str = "") -> Watch:
        self._check_destination(notification_url)
        self._check_metered("watches", resource)
        body = graph_map.subscription_body(resource, notification_url, events,
                                           graph_map.expiry_for(resource, expires, self._now))
        return graph_map.watch(self._call("watches", self.client.post, "/subscriptions", body))

    def renew(self, watch_id: str, expires: str) -> Watch:
        # No allow-list or metered re-check: a renewal changes only the expiry, and the destination
        # and resource were authorised when the subscription was created and cannot be edited here.
        # Read it first: the maximum lifetime depends on WHAT is watched, and only the subscription
        # itself knows that.
        path = f"/subscriptions/{_seg(watch_id)}"
        current = self._call("watches", self.client.get, path)
        clamped = graph_map.expiry_for(current.get("resource", ""), expires, self._now)
        return graph_map.watch(self._call("watches", self.client.patch, path,
                                          {"expirationDateTime": clamped}))

    def unwatch(self, watch_id: str) -> None:
        """Idempotent: a subscription that is already gone is the outcome that was asked for."""
        self._call("watches", self.client.delete, f"/subscriptions/{_seg(watch_id)}", tolerate=(404,))

    def _check_destination(self, url: str) -> None:
        if not str(url).lower().startswith("https://"):
            raise CollabUnavailable("watches", f"{url} is not an https destination",
                                    "Microsoft Graph delivers change notifications over https only")
        if not self.notification_allowlist:
            raise CollabUnavailable(
                "watches", "this deployment allow-lists no change-notification destination",
                "set GRAPH_NOTIFICATION_ALLOWLIST to the receivers that may be notified — empty "
                "REFUSES every subscription rather than allowing any")
        if _origin(url) not in {_origin(a) for a in self.notification_allowlist}:
            raise CollabUnavailable(
                "watches", f"{url} is not an allow-listed change-notification destination",
                "add it to GRAPH_NOTIFICATION_ALLOWLIST, or notify a receiver that is already listed")

    def _check_metered(self, capability: str, path: str) -> None:
        if graph_probe.is_metered(path) and not self.allow_metered:
            raise graph_probe.metered_refusal(capability, path)

    # ------------------------------------------------------------------ the one failure path
    def _call(self, capability: str, fn: Callable, *args, tolerate: tuple[int, ...] = (), **kwargs):
        """Every Graph call goes through here, so every refusal becomes a sentence naming the
        capability, the reason and the remedy — and a status code never escapes the adapter."""
        try:
            return fn(*args, **kwargs)
        except GraphError as e:
            if e.status in tolerate:
                return None
            # A GraphError can carry a SUCCESS status — a proxy answering 200 with HTML is still a
            # failure — so never trust `refusal()` to be non-None here.
            raise (graph_probe.refusal(e.status, e.code, e.detail, capability, e.retry_after)
                   or CollabUnavailable(capability, e.detail,
                                        "check what sits between the lab and Microsoft Graph")) from e


def build(*, tenant_id: str | None = None, client_id: str | None = None, client_secret: str | None = None,
          auth_mode: str | None = None, static_token: str | None = None, base_url: str | None = None,
          meeting_user: str | None = None, meeting_users: tuple[str, ...] | None = None,
          allow_metered: bool | None = None,
          notification_allowlist: tuple[str, ...] | None = None, max_fetch_bytes: int | None = None,
          client_factory: Callable | None = None, now: Callable[[], datetime] | None = None,
          **client_kwargs) -> GraphCollabRepository:
    """The ONE place this adapter is assembled — what a composition root names. Every value defaults
    to `lab.platform.config` (the single env reader) and can be overridden for a test or a second
    tenant; nothing below this function reads configuration."""
    def pick(given, default):
        return default if given is None else given

    tokens = graph_auth.token_source(
        pick(auth_mode, config.GRAPH_AUTH_MODE),
        tenant_id=pick(tenant_id, config.ENTRA_TENANT_ID),
        client_id=pick(client_id, config.GRAPH_CLIENT_ID),
        client_secret=pick(client_secret, config.GRAPH_CLIENT_SECRET),
        static_token=pick(static_token, config.GRAPH_ACCESS_TOKEN),
        client_factory=client_factory)
    client = GraphClient(tokens, base_url=pick(base_url, config.GRAPH_BASE_URL), **client_kwargs)
    return GraphCollabRepository(
        client, tokens, meeting_user=pick(meeting_user, config.GRAPH_MEETING_USER) or "",
        meeting_users=tuple(pick(meeting_users, config.GRAPH_MEETING_USERS)),
        allow_metered=bool(pick(allow_metered, config.GRAPH_ALLOW_METERED)),
        notification_allowlist=tuple(pick(notification_allowlist, config.GRAPH_NOTIFICATION_ALLOWLIST)),
        max_fetch_bytes=int(pick(max_fetch_bytes, config.GRAPH_MAX_FETCH_BYTES)),
        now=now)
