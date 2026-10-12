"""A web URL resolved to the CUSTODY POINTER the fabric's catalogue is keyed by.

Retrieval — SharePoint search, a Copilot citation, a person pasting a link — names a document the
only way a human can: `https://<tenant>/sites/<site>/Shared%20Documents/BRS.md`. Every record the
fabric holds is keyed by a custody pointer (`{source: collab, handle: collab://item/<drive>/<item>}`).
Nothing joined the two, so the one remaining way to answer "who owns this, is it approved" about a
url was to match on TITLE — which is silently wrong exactly when two records share one, the failure
FR-3.3 exists to surface. This module is that join.

WHY IT ASKS THE PROVIDER (the design decision, recorded here because the alternative looks cheaper).
Two routes were available:

  (a) ask the provider to resolve the url (`CollabRepository.item_by_url`, one governed tool call);
  (b) record the url on the pointer when the item is catalogued, making the lookup a local index read.

(a), for three reasons measured against this repository rather than preferred in the abstract:

  1. **A web url is PATH-based; the item behind it is not.** Rename or move a document and its url
     changes while its drive/item ids do not. A recorded url is therefore stale from the first tidy-up
     of a library — and it goes stale by returning NOTHING, which is indistinguishable from "this
     document is not governed". Asking the provider is always current.
  2. **The sweep does not have the url to record.** `collab_list` renders a `DriveItem` WITHOUT its
     `url` on purpose (`mcp/graph/server.py: _item`) — a listing lands in an agent's context and a
     personal drive's url embeds its owner. (b) therefore starts by reversing a deliberate privacy
     decision on a tool shared with every agent.
  3. **(b) covers one of three doors.** Records arrive from the sweep, from a change NOTIFICATION
     (which carries drive and item ids and no url at all) and from the lab's own outputs. (a) works
     for every record however it arrived, with no backfill of the ones already catalogued.

The cost of (a) is one gateway hop per lookup and a dependency on the provider being reachable — paid
deliberately: it fails LOUDLY (a typed refusal with a sentence) where (b) would fail silently.

The hop is GOVERNED like every other: through the gateway, as the fabric's substrate identity
(`fabric_gateway`), metered, ACL'd per team and on the run's trace.
"""
from __future__ import annotations

from lab.core.collab import normalise_web_url
from lab.platform.contracts import CollabTools
from lab.substrate import fabric_gateway

__all__ = ["pointer_for", "SOURCE"]

#: The pointer source every collaboration-held artifact is catalogued under (`POINTER_SOURCES`).
SOURCE = "collab"


async def pointer_for(url: str, *, call=None) -> dict | None:
    """The custody pointer for one web URL, or `None` when the provider knows no such address.

    `None` is an ABSENCE and never a guess: a caller must be able to answer "that document is not in
    the catalogue" truthfully rather than report the nearest title. A `url` that is not an absolute
    web url is a `ValueError` and never leaves the process. `call(batch)` is the gateway transport,
    injected by a test."""
    wanted = normalise_web_url(url)                 # raises before anything is spent
    go = call or fabric_gateway.call
    try:
        item = (await go([(CollabTools.item_by_url, {"url": wanted})]))[0]
    except Exception as e:                          # noqa: BLE001 — see below; the reason is PRINTED
        # A provider REFUSAL is an absence here. SharePoint answers a `shares/{url}` lookup for an
        # address that does not resolve with 403 rather than 404 (measured in UAT, 12 Oct 2026), so
        # `graph_probe.explain` reads it as a consent problem and the caller is told to grant
        # `Files.Read.All` — when the truth is that nobody has catalogued that document. This function
        # promises "None when the provider knows no such address", and a url the provider will not
        # resolve is exactly that from the fabric's side.
        #
        # Never SILENT, though, because the same 403 is what a genuinely unconsented application
        # returns, and then every lookup would answer "not catalogued" and the catalogue would look
        # empty. This line in the service log is the whole difference between a wrong answer a person
        # can find and one nobody can. The trade is deliberate: the common case is answered truthfully
        # in the researcher's chat, the rare case is loud in the operator's log.
        print(f"[custody] could not resolve a url through the provider — treating it as absent: "
              f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        return None
    handle = (item or {}).get("handle")
    # A folder resolves but carries no handle, so there is nothing to key a record by — an absence,
    # not a malformed pointer the catalogue would be asked about.
    return {"source": SOURCE, "handle": str(handle)} if handle else None
