"""The collaboration adapter's INBOUND door — Port 1 of note 003 as Microsoft Graph delivers it.

Graph POSTs change notifications to a public URL with no bearer of ours; it proves itself with the
`clientState` we gave it when the subscription was created, and asks us to prove we own the URL by
echoing a `validationToken`. This module is the pure handler plus the Starlette route that mounts it
BESIDE /mcp on graph-mcp (`app_for(routes=…, public_paths=…)`), exempt from the bearer check because
the caller is not the gateway.

What it does with a notification: resolve the resource to a content handle, ask the provider for the
item (its version, its actor when the provider says), and publish ONE ArtifactChanged per item onto
`fabric:events`. It decides nothing else — filtering and attribution are the ingress's (FRS 5.1.2/3).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from lab.core import ids
from lab.core.collab.model import ContentHandle
from lab.platform import config, fabric_events
from lab.platform.contracts import ArtifactChanged

PATH = "/notifications"
_RESOURCE = re.compile(r"drives/(?P<drive>[^/]+)/items/(?P<item>[^/]+)", re.I)
CHANGE = {"created": "created", "updated": "updated", "deleted": "deleted"}


def event_from_notification(n: dict, *, collab, now: str | None = None) -> ArtifactChanged | None:
    """ONE notification -> an event, or None when the resource is not a drive item we can name.
    PURE apart from `collab.item` (the version and the actor live on the item, not in the notice)."""
    m = _RESOURCE.search(str(n.get("resource") or ""))
    if not m:
        return None
    handle = ContentHandle.item(m.group("drive"), m.group("item"))
    change = CHANGE.get(str(n.get("changeType") or "updated").lower(), "updated")
    version, actor = "", ""
    if change != "deleted":
        try:
            item = collab.item(handle)
            version = item.modified or ""
        except Exception:                          # noqa: BLE001 — a deleted-since item is still a change
            pass
    data = n.get("resourceData") or {}
    actor = str((data.get("lastModifiedBy") or {}).get("user", {}).get("id") or "") if isinstance(data, dict) else ""
    pointer = {"source": "collab", "handle": str(handle)}
    if version:
        pointer["version"] = version
    return ArtifactChanged(event_id=ids.ulid(), pointer=pointer, source_kind="collab", change=change,
                           actor_oid=actor, occurred_at=now or datetime.now(timezone.utc).isoformat(timespec="seconds"))


def handle_batch(body: dict, *, client_state: str, collab, redis) -> dict:
    """Every notification in a batch: refused as a whole if any carries the wrong client state (a
    forged batch is a forged batch), else one event published per resolvable resource."""
    items = body.get("value") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return {"accepted": 0, "error": "no value[]"}
    if not client_state:
        return {"accepted": 0, "error": "FABRIC_NOTIFY_CLIENT_STATE is not set — refusing every notification"}
    if any(str(n.get("clientState") or "") != client_state for n in items if isinstance(n, dict)):
        return {"accepted": 0, "error": "clientState mismatch"}
    published = 0
    for n in items:
        if not isinstance(n, dict):
            continue
        event = event_from_notification(n, collab=collab)
        if event is not None:
            fabric_events.publish(event, client=redis)
            published += 1
    return {"accepted": published}


def route_for(server) -> Route:
    async def endpoint(request: Request):
        token = request.query_params.get("validationToken")
        if token:                                  # the ownership handshake: echo it, text/plain, 200
            return PlainTextResponse(token)
        if request.method != "POST":
            return JSONResponse({"error": "POST a notification batch"}, status_code=405)
        try:
            body = await request.json()
        except Exception:                          # noqa: BLE001
            return JSONResponse({"error": "body is not JSON"}, status_code=400)
        result = handle_batch(body, client_state=config.FABRIC_NOTIFY_CLIENT_STATE,
                              collab=server.collab(), redis=server.container.redis())
        # Graph expects 202 quickly; a refused batch is still 202 to the provider (it retries a 4xx
        # and we do not want a forger to learn anything), and the reason is on stdout for us.
        if result.get("error"):
            print(f"[notifications] refused: {result['error']}", flush=True)
        return JSONResponse(result, status_code=202)
    return Route(PATH, endpoint, methods=["GET", "POST"])


__all__ = ["PATH", "route_for", "handle_batch", "event_from_notification"]
