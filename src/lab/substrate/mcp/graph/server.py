"""graph-mcp — the COLLABORATION port (files and meetings) as governed tools (port 9500, /mcp).

Why a server, and why here: reaching where an organisation actually collaborates needs a long-lived
credential with tenant-wide reach. A workload must never hold one (invariant: agents never hold tool
credentials — the gateway injects them), so the credential lives HERE, in the substrate, and every
call an agent or workload makes goes gateway -> this server: granted per team, allow-listed per tool,
metered, PII-scanned and traced like any other call.

VENDOR-NEUTRAL BY CONSTRUCTION. The gateway alias is `collab_mcp` and every tool is `collab_*`
(`lab.platform.contracts.CollabTools`); the provider is named only by the SERVICE (`graph-mcp`,
`GRAPH_*` credentials) and by the ADAPTER the container resolves. This file talks to
`lab.core.collab.CollabRepository` — the domain port — and never to a provider SDK, so a second
collaboration platform is one entry in `lab.substrate.container.COLLAB_PROVIDERS` plus its adapter,
with no change here and no change in any caller. That is the `ea_mcp` / `adoit-mcp` precedent.

APP-ONLY IDENTITY, AND WHAT THAT COSTS. The gateway authenticates to every MCP server with one
shared secret, so this server never learns who the caller was and on-behalf-of is impossible without
changing that hop. It therefore uses its OWN credential: the caller's credential authorises the call
to this server, this server's identity authorises the call to the provider. The consequence is worth
stating rather than glossing — the app's permissions are the CEILING for every caller, per-caller
narrowing is done at the gateway with per-team `mcp_tool_permissions`, and the provider's own audit
shows the application, not the person.

TWO GRANTS, NOT ONE (`CollabTools.READ` / `.WRITE`). Reading is safe. The three subscription tools
are not: a subscription is EGRESS to a caller-supplied URL and a durable object on the provider's
side that outlives the run that made it, so they are granted separately and must never reach a
workload's own agents. The adapter refuses a destination that is not allow-listed; an empty
allow-list refuses everything.

CONTENT NEVER COMES BACK INLINE. A listing mints an opaque `collab://<kind>/<scope>/<id>` handle;
`collab_fetch` is the one verb that moves bytes, and it STREAMS them into the UPLOAD store and
returns an `art://` reference the workload then reads through storage-mcp. A meeting recording is
gigabytes; an agent's context is not, and neither is this process's memory.

NO SPAN CARRIES A PERSON. Tool arguments and results cross the gateway, where the PII guardrail
scans them; span attributes do NOT — they go straight to the OTLP endpoint, which in this lab is a
public, unauthenticated Jaeger. This is the first server whose arguments are real people (a
principal name, a search phrase, a meeting reference that embeds its organiser), so the rule here is
that a span attribute carries PROVIDER IDS, COUNTS and SHAPES only — never a principal and never
caller free text. Where knowing an argument was supplied still helps, the attribute is a boolean
(`collab.organizer.given`). Do not "helpfully" add the value back;
`tests/unit/substrate/mcp/graph/test_server.py` fails if one appears.

EVERY REFUSAL IS A SENTENCE. A provider answers "no" for administratively different reasons — the
permission was never consented, a separate policy was never applied, a tenant switch is off, the lab
itself is unconfigured — and the whole operating experience of such an integration is whether a
caller is told which. So every tool leaves through `governed`, which renders the domain's typed
refusal (`lab.core.collab.CollabError.sentence`: what is unavailable, why, and the administrative
step that fixes it). A status never reaches a caller WITHOUT the sentence that explains it — the
sentence often quotes the status, because a human chasing a 403 needs it; what never happens is a
bare code with no remedy. `collab_capabilities` is the same story told up front, for a tenant whose
grants are still being arranged.

  collab_capabilities(deep)                     what this tenant/credential actually allows, and why not
  collab_sites(query, limit, cursor)            the places a team's work lives
  collab_drives(site_id, limit, cursor)         one place's document libraries
  collab_user_drive(user_id)                    one PERSON's own drive — content no team ever filed
  collab_list(drive_id, path, limit, cursor)    one level of a drive
  collab_item(handle)                           one file's metadata
  collab_meetings(since, until, organizer, …)   meetings in a time window
  collab_recordings(meeting_id, …)              a meeting's recordings, by handle
  collab_transcripts(meeting_id, …)             a meeting's transcripts, by handle
  collab_fetch(handle, name)                    handle -> art:// ref, STREAMED into the upload store
  collab_watches / collab_watch /               change-notification subscriptions (the WRITE grant)
  collab_watch_renew / collab_unwatch
"""
from __future__ import annotations

import functools

from fastmcp.exceptions import ToolError

from lab.core.collab import (CAPABILITIES, ChangeType, CollabError, CollabUnavailable,
                             ContentHandle, HandleKind, MAX_LIMIT)
from lab.platform import config
from lab.platform.contracts import CollabTools, StorageTools
from lab.platform.filetypes import content_type_for
from lab.substrate.artifacts import IteratorReader
from lab.substrate.mcpserver import LabServer, span

SERVICE = "graph-mcp"

server = LabServer(SERVICE, config.GRAPH_MCP_PORT)   # server.collab() = the provider; server.uploads() = the upload store

# What a fetched object is CALLED, and what it is typed as WHEN THE PROVIDER DECLARES NOTHING. A
# file takes its name from its own metadata and every stream carries the provider's own media type;
# a recording or a transcript has no name at all, so the handle's KIND supplies one. Keyed on the
# DOMAIN's enum, so this is a presentation default and a last-resort fallback — never a guess used
# in place of something the provider actually said.
FETCH_DEFAULTS: dict[HandleKind, tuple[str, str]] = {
    HandleKind.RECORDING: ("mp4", "video/mp4"),
    HandleKind.TRANSCRIPT: ("vtt", "text/vtt"),
}
# What a caller does with the reference this server hands back — named from the contract, so a
# renamed storage tool cannot leave this instruction pointing at nothing.
READ_WITH = (f"read it through {StorageTools.SERVER}: {StorageTools.info} for its metadata, then "
             f"{StorageTools.get} (images), {StorageTools.read_document} (documents) or "
             f"{StorageTools.read_vsdx} (diagrams)")


def governed(fn):
    """`@server.tool()` (which adds the per-call span) plus the ONE failure path: a typed refusal
    leaves as its SENTENCE — what is unavailable, why, and the administrative step that fixes it —
    so no caller ever relays a provider status code to a human. Everything else (a malformed handle,
    an unknown change type) is already a `ValueError` naming what the caller got wrong."""
    @functools.wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except CollabError as refused:
            span().set_attribute("collab.refused", refused.capability or "")
            raise ToolError(refused.sentence) from refused
    return server.tool()(call)


# ----------------------------------------------------------------------------- rendering
def _page(page, render, **attributes) -> dict:
    """One listing as an agent reads it: the items, and the OPAQUE cursor to ask again with (`null`
    on the last page — never parsed, only echoed back)."""
    span().set_attributes({"collab.count": len(page), "collab.more": page.more, **attributes})
    return {"items": [render(i) for i in page], "cursor": page.cursor, "more": page.more}


def _site(s) -> dict:
    return {"id": s.id, "name": s.name, "description": s.description}


def _drive(d) -> dict:
    return {"id": d.id, "name": d.name, "site_id": d.site_id, "owner": d.owner}


def _item(i) -> dict:
    return {"id": i.id, "name": i.name, "drive_id": i.drive_id, "folder": i.folder, "size": i.size,
            "modified": i.modified, "path": i.path,
            "handle": None if i.folder else str(i.handle)}     # a folder holds no content to fetch


def _meeting(m) -> dict:
    return {"id": m.id, "subject": m.subject, "organizer": m.organizer, "start": m.start,
            "end": m.end, "participants": list(m.participants)}


def _record(r) -> dict:
    return {"id": r.id, "kind": r.kind.value, "meeting_id": r.meeting_id, "created": r.created,
            "media_type": r.media_type, "size": r.size, "handle": str(r.handle)}


def _watch(w) -> dict:
    return {"id": w.id, "resource": w.resource, "notification_url": w.notification_url,
            "events": [e.value for e in w.events], "expires": w.expires}


# ----------------------------------------------------------------------------- caller input
def _handle(text: str) -> ContentHandle:
    handle = ContentHandle.parse(text)
    # the KIND, not the handle: a media handle's scope is a meeting reference that embeds the
    # organiser's principal name in the clear (see the span rule in the module docstring)
    span().set_attribute("collab.handle.kind", handle.kind.value)
    return handle


def _filename(name: str) -> str:
    """A NAME, never a path: an `art://<id>/<name>` reference is parsed on the slash, so a name
    carrying one would mint a reference nothing can read back. Applied to the name actually USED,
    not only to a caller's override — a provider's own file name is caller input once removed."""
    text = str(name or "").strip()
    if not text:
        return text                    # an absent override; the caller of `_named` supplies one
    if "/" in text or "\\" in text or text in (".", "..") or text.startswith(".."):
        raise ValueError(f"a file name is a name, not a path: {name!r}")
    return text


def _default_media_type(handle: ContentHandle, filename: str) -> str:
    """The type to store an object under when the provider declared none — from the file's own
    extension where that is known, else from the kind of handle (a recording is video, a transcript
    is text). Never used in place of a type the provider actually reported."""
    if handle.kind in FETCH_DEFAULTS:
        return FETCH_DEFAULTS[handle.kind][1]
    return content_type_for(filename)


def _events(events) -> tuple[ChangeType, ...]:
    known = [c.value for c in ChangeType]
    try:
        return tuple(ChangeType(str(e).strip().lower()) for e in (events or [ChangeType.CREATED]))
    except ValueError:
        raise ValueError(f"unknown change type in {list(events)!r} — one of {known}") from None


def _named(handle: ContentHandle, given: str) -> str:
    """What to CALL a fetched object. The caller's name wins; a FILE otherwise keeps the name it has
    at the provider (one cheap lookup, skipped when the caller already said); a recording or a
    transcript carries no name at all, so the handle's KIND supplies a neutral one. The result is
    validated like any name, because a provider's own name is caller input once removed and an
    `art://<id>/<name>` reference is parsed on the slash."""
    if given:
        return given
    if handle.kind is HandleKind.ITEM:
        # `or` the fallback: a provider that reports no name must not mint `art://<id>/` — a
        # reference with an empty name cannot be parsed back.
        return _filename(server.collab().item(handle).name) or f"{handle.kind.value}-{handle.id}"
    return _filename(f"{handle.kind.value}-{handle.id}.{FETCH_DEFAULTS[handle.kind][0]}")


# ----------------------------------------------------------------------------- capabilities
@governed
def collab_capabilities(deep: bool = False) -> dict:
    """What this collaboration provider will ACTUALLY serve for the lab right now, area by area
    (sites, drives, items, content, meetings, recordings, transcripts, watches), and for anything it
    will not: why, and the administrative step that would fix it. Run this FIRST when a collab_ tool
    refuses, and before assuming a tenant can serve meeting recordings — they usually need a
    separate policy as well as a permission. `deep=true` additionally makes one cheap live call per
    area, which catches a permission that was granted but a policy that was never applied; the
    default reads only what the credential itself declares and calls nothing."""
    table = server.collab().capabilities(deep)
    unavailable = {name: refused.to_dict() for name, refused in table.items() if refused is not None}
    # A capability the provider did not report on at all is UNAVAILABLE, not available: for a
    # capability table the safe default is the pessimistic one, and silence is not a yes.
    unavailable |= {name: CollabUnavailable(
        name, "the collaboration provider did not report on this area",
        "check the provider adapter — it answers a table with one entry per capability").to_dict()
        for name in CAPABILITIES if name not in table}
    span().set_attributes({"collab.capabilities.available": len(CAPABILITIES) - len(unavailable),
                           "collab.capabilities.unavailable": ",".join(sorted(unavailable))})
    return {"deep": bool(deep), "unavailable": unavailable,
            "available": [name for name in CAPABILITIES if name in table and table[name] is None]}


# ----------------------------------------------------------------------------- files
@governed
def collab_sites(query: str = "", limit: int | None = None, cursor: str | None = None) -> dict:
    """The sites (team workspaces) the lab may reach, optionally narrowed by a free-text `query`.
    Returns {items:[{id,name,description}], cursor, more}: pass the `cursor` straight back to get the
    next page and never try to interpret it. An empty list is a legitimate answer — it means access
    has been granted to nothing yet, not that the call failed. Use a site's id with collab_drives.
    A person's OWN files are not in any site: reach those with collab_user_drive."""
    return _page(server.collab().sites(query, limit, cursor), _site,
                 **{"collab.query.given": bool(query)})     # the phrase itself may name a person


@governed
def collab_drives(site_id: str, limit: int | None = None, cursor: str | None = None) -> dict:
    """The document libraries of ONE site, by the `site_id` collab_sites handed out (never a path you
    composed yourself). Returns {items:[{id,name,site_id,owner}], cursor, more}; most sites have one
    default library and may have several. Use a drive's id with collab_list to see what is in it."""
    return _page(server.collab().drives(site_id, limit, cursor), _drive, **{"collab.site": site_id})


@governed
def collab_user_drive(user_id: str) -> dict:
    """The drive belonging to one PERSON, by their directory id or principal name (e.g.
    maria@example.com) — a single drive, not a list. This is the ONLY way to reach files that nobody
    filed in a shared site: a meeting recorded ad hoc is stored by whoever started it, in their own
    drive, which collab_sites and collab_drives can never see. Returns {id,name,site_id,owner} with
    an empty site_id, because a personal drive belongs to no site. Use its id with collab_list."""
    drive = server.collab().user_drive(user_id)
    span().set_attribute("collab.drive", drive.id)          # the drive, never whose it is
    return _drive(drive)


@governed
def collab_list(drive_id: str, path: str = "", limit: int | None = None,
                cursor: str | None = None) -> dict:
    """The folders and files directly inside `path` of a drive ("" is the drive root). Listing is ONE
    LEVEL DEEP on purpose — recurse yourself, so a run cannot walk an entire library by accident.
    Returns {items:[{id,name,folder,size,modified,path,handle}], cursor, more}: every FILE carries a
    `handle` (collab://…) to fetch it by; a folder has none, and you list it by passing its name in
    `path`. Never fetch content here — collab_fetch is the one verb that moves bytes."""
    return _page(server.collab().items(drive_id, path, limit, cursor), _item,
                 **{"collab.drive": drive_id, "collab.path": path})


@governed
def collab_item(handle: str) -> dict:
    """The metadata of ONE file — name, size, last modified, the folder it sits in — by the
    collab://item/… handle a collab_list gave you. Use it to decide whether a file is worth fetching
    before spending time and bytes on collab_fetch. A handle for a recording or a transcript has no
    drive metadata and is refused here; fetch those directly."""
    return _item(server.collab().item(_handle(handle)))


# ----------------------------------------------------------------------------- meetings
@governed
def collab_meetings(since: str = "", until: str = "", organizer: str = "",
                    limit: int | None = None, cursor: str | None = None) -> dict:
    """The online meetings in a time window — `since`/`until` as ISO-8601 UTC (e.g.
    2026-09-01T00:00:00Z); either may be empty for this deployment's default window. `organizer`
    narrows to one person's meetings, and a deployment may only permit the people it is configured
    for. Returns {items:[{id,subject,organizer,start,end,participants}], cursor, more}. Treat
    `participants` as who was CONNECTED, not who spoke: one device in a room of people is one
    participant. Pass a meeting's id to collab_recordings / collab_transcripts."""
    return _page(server.collab().meetings(since, until, organizer, limit, cursor), _meeting,
                 **{"collab.organizer.given": bool(organizer)})


@governed
def collab_recordings(meeting_id: str, limit: int | None = None, cursor: str | None = None) -> dict:
    """The recordings of ONE meeting, by the id collab_meetings handed out — metadata and a
    collab://recording/… handle only, never the video itself. Returns
    {items:[{id,kind,created,media_type,size,handle}], cursor, more}; an empty list means the meeting
    was never recorded, or that this tenant does not release recordings (run collab_capabilities to
    tell those apart). Fetch the bytes with collab_fetch, which streams them into the upload store."""
    return _page(server.collab().recordings(meeting_id, limit, cursor), _record)


@governed
def collab_transcripts(meeting_id: str, limit: int | None = None, cursor: str | None = None) -> dict:
    """The transcripts of ONE meeting, in exactly the same shape as collab_recordings so a caller
    need not branch on which it is holding: metadata plus a collab://transcript/… handle. A
    transcript is text and cheap, so prefer it over a recording whenever the words are what you
    need. Fetch it with collab_fetch and read the result through the governed object store."""
    return _page(server.collab().transcripts(meeting_id, limit, cursor), _record)


# ----------------------------------------------------------------------------- content
@governed
def collab_fetch(handle: str, name: str = "") -> dict:
    """Fetch the content behind ONE collab:// handle into the lab's upload store and return an
    art://<id>/<name> reference to it. This is the ONLY verb that moves bytes, and it NEVER returns
    them inline: the object is streamed straight into the store (a meeting recording is gigabytes),
    and the caller reads it afterwards through the governed object store. Returns
    {ref, name, content_type, bytes, handle, read_with}. `name` overrides the file name the artifact
    is stored under — a plain name, never a path; a recording or transcript, which carries no name of
    its own, otherwise gets a neutral one from the kind of handle."""
    ref_handle = _handle(handle)
    filename = _named(ref_handle, _filename(name))
    stream = server.collab().open(ref_handle)
    # The provider's own type and length win over any default: the DECLARED size is what lets the
    # store refuse an over-large object before the download is paid for, which is the whole reason
    # a recording is streamed rather than buffered.
    media_type = stream.media_type or _default_media_type(ref_handle, filename)
    body = IteratorReader(stream.chunks)
    ref = server.uploads().put_stream(filename, body, media_type, stream.size or None)
    span().set_attributes({"collab.ref": ref, "collab.bytes": body.count,
                           "collab.content_type": media_type})
    return {"ref": ref, "name": filename, "content_type": media_type, "bytes": body.count,
            "handle": str(ref_handle), "read_with": READ_WITH}


# ----------------------------------------------------------------------------- subscriptions (WRITE)
@governed
def collab_watches(limit: int | None = None, cursor: str | None = None) -> dict:
    """Every change-notification subscription this lab currently owns at the provider — the
    inventory that makes durable, provider-side objects visible and revocable. Returns
    {items:[{id,resource,notification_url,events,expires}], cursor, more}. Read this before creating
    another one: a subscription outlives the run that made it, and a forgotten one keeps delivering."""
    return _page(server.collab().watches(limit, cursor), _watch)


@governed
def collab_watch(resource: str, notification_url: str, events: list[str] | None = None,
                 expires: str = "") -> dict:
    """Create a change-notification subscription: ask the provider to POST to `notification_url`
    whenever one of `events` (created | updated | deleted; created by default) happens to `resource`.
    This is a WRITE: it creates egress to a URL you supply and a durable object at the provider that
    outlives this run, so the destination must be one the lab has explicitly allow-listed — an
    unlisted one is refused, and a deployment that lists nothing refuses every subscription. `expires`
    is ISO-8601 UTC and is clamped to the longest lifetime the provider allows for that resource."""
    made = server.collab().watch(resource, notification_url, _events(events), expires)
    span().set_attribute("collab.watch", made.id)     # not the resource: it can embed a principal
    return _watch(made)


@governed
def collab_watch_renew(watch_id: str, expires: str = "") -> dict:
    """Extend an existing subscription's expiry and return it as the provider now holds it. A
    subscription expires on its own — renewing is how a long-running watch stays alive — and the
    requested expiry is clamped to the maximum the provider allows for what is being watched, so
    asking for too much is adjusted rather than refused. Neither the destination nor the resource can
    be changed here: those were authorised when the subscription was created."""
    renewed = server.collab().renew(watch_id, expires)
    span().set_attribute("collab.watch", watch_id)
    return _watch(renewed)


@governed
def collab_unwatch(watch_id: str) -> dict:
    """Cancel a change-notification subscription, so the provider stops delivering to its
    destination. Idempotent: cancelling one that is already gone is not an error, because the goal is
    that it no longer exists. Use collab_watches to find the id, and prefer cancelling a subscription
    you no longer need over letting it expire — it is egress that outlives the run that made it."""
    server.collab().unwatch(watch_id)
    span().set_attribute("collab.watch", watch_id)
    return {"watch_id": watch_id, "removed": True}


if __name__ == "__main__":
    print(f"graph-mcp: collaboration provider = {config.COLLAB_PROVIDER}, page size <= {MAX_LIMIT}; "
          f"call {CollabTools.capabilities} to see what this tenant actually allows")
    server.serve()
