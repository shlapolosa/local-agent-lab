"""Offline doubles for the Microsoft Graph adapter — no tenant, no network, no `msal`.

FakeTransport   the `graph_rest` transport seam: rules matched on (method, url substring) returning
                canned (status, headers, body) responses, every call recorded. An unmatched request
                answers Graph's own 404 shape, so a test that forgets a route fails like the real
                thing rather than with an AttributeError.
FakeSleep       a sleep that records what it was asked to wait instead of waiting — throttling and
                back-off are asserted, never endured.
FakeTokens      the `graph_auth.TokenSource` interface: a fixed token and a fixed roles claim.
FakeGraph       the DOMAIN port (`lab.core.collab.CollabRepository`) with knobs — `capabilities=`
                turns an area off, `raises=` makes every call fail — for anything upstream of the
                adapter (a tool, a workflow) that needs a collaboration provider but not Graph.
"""
from __future__ import annotations

import io
import json

from lab.core.collab import (CAPABILITIES, ChangeType, CollabUnavailable, ContentStream, Drive,
                             DriveItem, HandleKind, MediaKind, MediaRecord, Meeting, Page, Site,
                             Watch, clamp_limit)
from lab.substrate.mcp.graph.graph_rest import Response

__all__ = ["FakeTransport", "FakeSleep", "FakeTokens", "FakeGraph", "NOT_FOUND"]

NOT_FOUND = {"error": {"code": "itemNotFound", "message": "The resource could not be found."}}


def _body(body) -> tuple[bytes, str]:
    if body is None:
        return b"", ""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body), "application/octet-stream"
    if isinstance(body, str):
        return body.encode(), "text/plain"
    return json.dumps(body).encode(), "application/json"


class _Rule:
    def __init__(self, contains, method, status, body, headers, times):
        self.contains, self.method, self.status = contains, method.upper(), status
        self.raw, self.content_type = _body(body)
        self.headers = {"content-type": self.content_type, **{k.lower(): v for k, v in (headers or {}).items()}}
        self.times = times

    def matches(self, method, url):
        return (self.times is None or self.times > 0) and self.contains in url and \
            (not self.method or self.method == method.upper())


class FakeTransport:
    """`transport(method, url, headers, body, timeout) -> Response`, driven by queued rules.

    Rules are tried in order and consumed after `times` matches (`times=None` = unlimited), so a
    test can say "this call 429s once, then succeeds" by queueing two rules for the same URL."""

    def __init__(self):
        self.rules: list[_Rule] = []
        self.calls: list[dict] = []
        self.bodies: list[io.BytesIO] = []      # every body handed out, so a test can assert it was closed

    def expect(self, contains="", status=200, body=None, headers=None, method="", times=1):
        self.rules.append(_Rule(contains, method, status, body, headers, times))
        return self

    def __call__(self, method, url, headers, body=None, timeout=30.0) -> Response:
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        for rule in self.rules:
            if rule.matches(method, url):
                if rule.times is not None:
                    rule.times -= 1
                return self._response(rule.status, dict(rule.headers), rule.raw)
        return self._response(404, {"content-type": "application/json"}, _body(NOT_FOUND)[0])

    def _response(self, status, headers, raw) -> Response:
        body = io.BytesIO(raw)
        self.bodies.append(body)
        return Response(status, headers, body)

    @property
    def urls(self) -> list[str]:
        return [c["url"] for c in self.calls]


class FakeSleep:
    """A recording sleep — `calls` is what the client asked to wait for, in order."""

    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeTokens:
    """A `graph_auth.TokenSource`: whatever token and roles a test wants, or a failure."""

    def __init__(self, token="fake-token", roles=(), raises=None):
        self._token, self._roles, self._raises = token, tuple(roles), raises

    def token(self):
        if self._raises:
            raise self._raises
        return self._token

    def roles(self):
        if self._raises:
            raise self._raises
        return self._roles


class FakeGraph:
    """A `CollabRepository` for everything ABOVE the adapter. Knobs, not scenarios:

        FakeGraph(capabilities={"recordings": False})   recordings refuse; everything else works
        FakeGraph(raises=CollabUnavailable(...))        every verb fails the same way
    """

    def __init__(self, sites=(), drives=(), items=(), meetings=(), recordings=(), transcripts=(),
                 watches=(), content=b"content", content_type="", capabilities=None, raises=None):
        self._sites = tuple(sites) or (Site("site-1", "Lab"),)
        self._drives = tuple(drives) or (Drive("drive-1", "Documents", "site-1"),)
        self._items = tuple(items) or (DriveItem("item-1", "notes.docx", "drive-1", size=12),)
        self._meetings = tuple(meetings) or (Meeting("meeting-1", "Design review"),)
        self._recordings = tuple(recordings) or (MediaRecord("rec-1", MediaKind.RECORDING, "meeting-1"),)
        self._transcripts = tuple(transcripts) or (MediaRecord("tr-1", MediaKind.TRANSCRIPT, "meeting-1"),)
        self._watches = tuple(watches)
        # `content_type` defaults to EMPTY on purpose: a double must not invent a declaration the
        # provider never made, or a caller's fallback path is never exercised.
        self.content, self.content_type, self.raises = content, content_type, raises
        self.off = {k for k, on in (capabilities or {}).items() if not on}
        self.calls: list[tuple] = []

    # -- the knobs ------------------------------------------------------------------
    def _check(self, capability, *args):
        self.calls.append((capability, *args))
        if self.raises:
            raise self.raises
        if capability in self.off:
            raise CollabUnavailable(capability, f"{capability} is switched off in this fake",
                                    "construct FakeGraph without turning it off")

    def _page(self, capability, items, limit, cursor, *args):
        """Real paging, so a caller written against this fake exercises the cursor it will have to
        handle against a provider: the cursor is an offset, echoed back opaquely, `None` at the end.
        `limit` goes through the DOMAIN's clamp, exactly as an adapter's does."""
        self._check(capability, *args)
        items, size = tuple(items), clamp_limit(limit)
        start = int(cursor) if cursor else 0
        window = items[start:start + size]
        return Page(window, str(start + size) if start + size < len(items) else None)

    # -- the port -------------------------------------------------------------------
    def capabilities(self, deep=False):
        self.calls.append(("capabilities", deep))
        return {c: (CollabUnavailable(c, "switched off in this fake") if c in self.off else None)
                for c in CAPABILITIES}

    def sites(self, query="", limit=None, cursor=None):
        return self._page("sites", self._sites, limit, cursor, query)

    def drives(self, site_id, limit=None, cursor=None):
        return self._page("drives", self._drives, limit, cursor, site_id)

    def user_drive(self, user_id):
        # The same caller error the real adapter makes, so a caller cannot pass this fake and fail Graph.
        if not str(user_id or "").strip():
            raise ValueError("a user drive needs the person whose drive it is")
        self._check("drives", user_id)
        return next((d for d in self._drives if d.owner == user_id),
                    Drive(f"drive-of-{len(self._drives)}", "Personal", owner=user_id))

    def items(self, drive_id, path="", limit=None, cursor=None):
        return self._page("items", self._items, limit, cursor, drive_id, path)

    def item(self, handle):
        # The same refusals the real adapter makes, so a caller cannot pass this fake and fail Graph.
        if handle.kind is not HandleKind.ITEM:
            raise ValueError(f"only a file handle has drive metadata, not {handle.kind.value}")
        self._check("items", str(handle))
        found = next((i for i in self._items if i.id == handle.id), None)
        if found is None:
            raise CollabUnavailable("items", f"no item {handle.id}", "check the id")
        return found

    def open(self, handle):
        self._check("content", str(handle))
        return ContentStream(iter([self.content]), self.content_type, len(self.content))

    def meetings(self, since="", until="", organizer="", limit=None, cursor=None):
        window = [m for m in self._meetings
                  if (not since or not m.start or m.start >= since)
                  and (not until or not m.start or m.start <= until)]
        return self._page("meetings", window, limit, cursor, since, until, organizer)

    def recordings(self, meeting_id, limit=None, cursor=None):
        return self._page("recordings", self._recordings, limit, cursor, meeting_id)

    def transcripts(self, meeting_id, limit=None, cursor=None):
        return self._page("transcripts", self._transcripts, limit, cursor, meeting_id)

    def watches(self, limit=None, cursor=None):
        return self._page("watches", self._watches, limit, cursor)

    def watch(self, resource, notification_url, events, expires=""):
        self._check("watches", resource, notification_url)
        made = Watch(f"sub-{len(self._watches) + 1}", resource, notification_url,
                     tuple(ChangeType(e) for e in events), expires)
        self._watches += (made,)
        return made

    def renew(self, watch_id, expires):
        self._check("watches", watch_id, expires)
        found = next(w for w in self._watches if w.id == watch_id)
        renewed = Watch(found.id, found.resource, found.notification_url, found.events, expires)
        self._watches = tuple(renewed if w.id == watch_id else w for w in self._watches)
        return renewed

    def unwatch(self, watch_id):
        self._check("watches", watch_id)
        self._watches = tuple(w for w in self._watches if w.id != watch_id)
