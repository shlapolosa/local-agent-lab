"""`CollabRepository` — the DOMAIN port for collaboration: the files and meetings a business process
needs from wherever the organisation actually collaborates.

A DOMAIN port (CLAUDE.md: "abstraction layer -> adapters -> DI seam") states what the domain needs
in the domain's own words and imports nothing. A concrete provider is an ADAPTER living where its
credentials do (the substrate, as an MCP server), with a MAPPER translating that provider's payloads
into the objects in `model.py`; the composition root is the only place that names one. So this file
is deliberately a `Protocol` and nothing else: no base class to inherit, no behaviour to accidentally
depend on, structural typing so a test double is a plain object with the right methods.

Three properties every implementation must honour:

  * **Content by handle, never inline.** A listing mints a `ContentHandle`; `open()` is the one verb
    that produces bytes, as a STREAM, so a recording is never held in memory whole.
  * **Paged with an opaque cursor, hard-capped.** Callers pass `limit`/`cursor` and echo the cursor
    back; the size is clamped through `model.clamp_limit` because a listing is read by an agent.
  * **A refusal is typed.** Anything the provider will not serve raises (or, from `capabilities()`,
    RETURNS) a `CollabUnavailable` naming the capability, the reason and the remedy — never an
    opaque status code.

The write side (`watch` / `renew` / `unwatch`) is separated on purpose: a subscription is egress to
a caller-supplied URL and a durable object on the provider's side that outlives the run that made
it, so it is granted apart from reading and is not for a workload's own agents.
"""
from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from lab.core.collab.errors import CollabUnavailable
from lab.core.collab.model import ChangeType, ContentHandle, Drive, DriveItem, MediaRecord, Meeting, Page, Site, Watch

__all__ = ["CAPABILITIES", "CollabRepository"]

# The areas a probe reports on, and the keys `capabilities()` answers with — one per group of verbs,
# because a tenant grants them separately (reading files is a different permission from reading a
# meeting's transcript, and subscribing is different again).
CAPABILITIES: tuple[str, ...] = ("sites", "drives", "items", "content", "meetings", "recordings",
                                 "transcripts", "watches")


@runtime_checkable
class CollabRepository(Protocol):
    """What the domain needs from a collaboration provider. Implementations are adapters."""

    def capabilities(self, deep: bool = False) -> dict[str, CollabUnavailable | None]:
        """What this provider/tenant will actually serve: one key per `CAPABILITIES` entry, mapped to
        `None` when the capability is available or to the `CollabUnavailable` explaining why it is
        not. It REPORTS rather than raises, so one call renders the whole table.
        `deep=True` additionally probes each area with one cheap live call instead of only reading
        the credential's declared permissions — slower, but it catches a grant that was consented
        and a policy that was never applied."""

    def sites(self, query: str = "", limit: int | None = None, cursor: str | None = None) -> Page[Site]:
        """The sites the lab may reach, filtered by a free-text `query` when given. An empty page is
        a legitimate answer (per-site access granted to nothing yet); a refusal raises."""

    def drives(self, site_id: str, limit: int | None = None, cursor: str | None = None) -> Page[Drive]:
        """The document libraries of one site — a site usually has one default library and may have
        several. `site_id` is a `Site.id` this port handed out, not a path a caller composed."""

    def items(self, drive_id: str, path: str = "", limit: int | None = None,
              cursor: str | None = None) -> Page[DriveItem]:
        """The folders and files directly inside `path` of a drive ("" is the drive root). Listing is
        one level deep: recursion is the caller's, so a run cannot walk a whole library by accident."""

    def item(self, handle: ContentHandle) -> DriveItem:
        """The metadata of one file, by the handle a listing minted for it — name, size, modified.
        Raises `ValueError` for a handle of the wrong kind, `CollabUnavailable` when it cannot be read."""

    def open(self, handle: ContentHandle) -> Iterator[bytes]:
        """The content, STREAMED in chunks — the single verb that produces bytes, for every kind of
        handle (a file, a recording, a transcript). It streams because a recording does not fit in
        memory; the caller writes the chunks straight into the store and keeps only the reference."""

    def meetings(self, since: str = "", until: str = "", organizer: str = "",
                 limit: int | None = None, cursor: str | None = None) -> Page[Meeting]:
        """The meetings in a time window (ISO-8601 UTC bounds, either may be empty), optionally
        narrowed to one organizer. The window is the cheap, non-metered path; a provider-wide feed
        is not part of the port."""

    def recordings(self, meeting_id: str, limit: int | None = None,
                   cursor: str | None = None) -> Page[MediaRecord]:
        """The recordings of one meeting, as `MediaRecord`s of kind `recording` — metadata and a
        handle only. The bytes come from `open()`."""

    def transcripts(self, meeting_id: str, limit: int | None = None,
                    cursor: str | None = None) -> Page[MediaRecord]:
        """The transcripts of one meeting, as `MediaRecord`s of kind `transcript`. Same shape as a
        recording on purpose — the caller does not branch on which it is holding."""

    def watches(self, limit: int | None = None, cursor: str | None = None) -> Page[Watch]:
        """Every change-notification subscription this identity currently owns — the inventory that
        makes the durable, provider-side objects visible and revocable."""

    def watch(self, resource: str, notification_url: str, events: tuple[ChangeType, ...],
              expires: str = "") -> Watch:
        """Subscribe: ask the provider to notify `notification_url` when one of `events` happens to
        `resource`, until `expires` (the provider's maximum when empty). WRITE — it creates egress to
        a caller-supplied URL and an object that outlives the run, so an implementation refuses a
        destination that is not explicitly allow-listed."""

    def renew(self, watch_id: str, expires: str) -> Watch:
        """Extend an existing subscription's expiry and return it as the provider now holds it."""

    def unwatch(self, watch_id: str) -> None:
        """Cancel a subscription. Idempotent: cancelling one that is already gone is not an error —
        the goal is that it no longer exists."""
