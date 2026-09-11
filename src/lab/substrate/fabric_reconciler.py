"""The reconciler: what a missed notification would have said, said later.

Change notifications are best effort — a subscription lapses, a receiver is down for a deploy, a tenant
throttles — so the Change Events product has a second source: a timer sweep that LISTS the allow-listed
drives (one level at a time, bounded depth, bounded count) and compares each file's `modified` stamp with
what the catalog last saw of it. A file the catalog has never seen, or saw at another version, becomes an
`ArtifactChanged` on `fabric:events` exactly as a notification would — so the ingress, its allow-list, its
attribution and its idempotency apply unchanged. It never writes the catalog; it only asks it.

Runs with the substrate's fabric identity (`FABRIC_CURATOR_KEY`): `collab_list` and `semantic_catalog_get`
through the gateway. `FABRIC_ALLOWLIST` entries `collab:<drive id>` are what it sweeps; `collab:*` is an
admission rule for the ingress, not a drive, and is skipped here.

Run: .venv/bin/python -m lab.substrate.fabric_reconciler
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from lab.core import ids
from lab.core.collab.model import ContentHandle
from lab.platform import config, fabric_events, streams
from lab.platform.contracts import ArtifactChanged, CollabTools, SemanticTools
from lab.substrate import fabric_gateway

SERVICE = "fabric-reconciler"


def drives(allowlist: tuple[str, ...]) -> list[str]:
    """The drive ids to sweep — the collab entries of the allow-list that name a drive."""
    out = []
    for entry in allowlist:
        source, _, scope = str(entry).partition(":")
        if source == "collab" and scope and scope != "*":
            out.append(scope)
    return out


def decide(item: dict, row: dict | None) -> ArtifactChanged | None:
    """One listed FILE against what the catalog knows of it: an event when it is new or changed, None when the
    catalog already saw this version (or the item is a folder / carries no handle). Pure."""
    if item.get("folder") or not ContentHandle.is_handle(item.get("handle")):
        return None
    modified = str(item.get("modified") or "")
    if row and str((row.get("pointer") or {}).get("version") or "") == modified and modified:
        return None
    pointer = {"source": "collab", "handle": str(item["handle"])}
    if modified:
        pointer["version"] = modified
    return ArtifactChanged(event_id=ids.ulid(), pointer=pointer, source_kind="collab",
                           change="updated" if row else "created", actor_oid="",
                           occurred_at=modified or datetime.now(timezone.utc).isoformat(timespec="seconds"))


async def sweep(*, call=None, allowlist: tuple[str, ...] | None = None, depth: int | None = None,
                limit: int | None = None, client=None) -> list[ArtifactChanged]:
    """List every allow-listed drive to `depth`, ask the catalog about each file, publish what changed.
    Returns the events published. `call(calls)` is the gateway transport (injected by a test)."""
    go = call or fabric_gateway.call
    allow = config.FABRIC_ALLOWLIST if allowlist is None else allowlist
    depth = config.FABRIC_SWEEP_DEPTH if depth is None else depth
    limit = config.FABRIC_SWEEP_LIMIT if limit is None else limit
    published: list[ArtifactChanged] = []
    seen = 0
    for drive in drives(allow):
        stack: list[tuple[str, int]] = [("", 0)]
        while stack and seen < limit:
            path, d = stack.pop()
            page = (await go([(CollabTools.list, {"drive_id": drive, "path": path})]))[0] or {}
            files: list[dict] = []
            for item in page.get("items") or []:
                if item.get("folder"):
                    if d < depth:
                        stack.append((f"{path}/{item['name']}".strip("/"), d + 1))
                    continue
                if seen >= limit:
                    break
                seen += 1
                if ContentHandle.is_handle(item.get("handle")):
                    files.append(item)
            if not files:
                continue
            # ONE gateway session per page, not per file: the catalog is asked about every file at once
            rows = await go([(SemanticTools.catalog_get, {"pointer": {"source": "collab", "handle": f["handle"]}})
                             for f in files])
            for item, row in zip(files, rows):
                event = decide(item, row)
                if event is not None:
                    fabric_events.publish(event, client=client)
                    published.append(event)
    return published


def run_once(*, call=None, client=None) -> list[ArtifactChanged]:
    r = client or _client()
    try:
        out = asyncio.run(sweep(call=call, client=r))
        print(f"[reconciler] swept: {len(out)} change(s) published", flush=True)
        return out
    except Exception as e:                          # noqa: BLE001 — a sweep that fails runs again next tick
        print(f"[reconciler] sweep failed: {type(e).__name__}: {e}", flush=True)
        return []


def _client():
    from lab.platform import redis_client
    return redis_client.client()


def main() -> None:
    r = _client()

    def tick():
        time.sleep(config.FABRIC_SWEEP_S)
        return [("sweep", {})]

    streams.serve(name=SERVICE,
                  ready=f"{SERVICE} ready  drives={len(drives(config.FABRIC_ALLOWLIST))} every={config.FABRIC_SWEEP_S}s",
                  on_start=lambda: run_once(client=r), read=tick, handle=lambda eid, f: run_once(client=r))


if __name__ == "__main__":
    main()
