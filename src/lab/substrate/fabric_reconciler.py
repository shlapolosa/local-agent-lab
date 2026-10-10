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
from lab.platform import config, fabric_events, filetypes, streams
from lab.platform.contracts import ArtifactChanged, CollabTools, SemanticTools
from lab.substrate import fabric_gateway, fabric_metrics, fabric_vocabulary

SERVICE = "fabric-reconciler"

# The kinds the fabric can actually read from a listing (`filetypes.kind_for`). `artifact` is absent
# deliberately: a lab-produced render reaches the catalogue through the always-admitted `lab` door,
# carrying the product and run that made it, which a swept copy of the same bytes could not.
SWEEPABLE_KINDS = ("document", "vsdx", "image")


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


async def renew_watches(*, call=None, receivers: tuple[str, ...] | None = None, within_s: int | None = None,
                        now: datetime | None = None) -> list[dict]:
    """Renew the lab's OWN change-notification subscriptions — the ones delivering to a receiver on the
    allow-list — when they are within `within_s` of expiring. A subscription outlives the run that made it
    and dies quietly; a sweep that outlives it would then be the only source of change events. Renewal
    cannot change a destination or a resource, which is why this consumer may hold that verb and no other
    subscription verb. Returns what was renewed."""
    go = call or fabric_gateway.call
    receivers = config.GRAPH_NOTIFICATION_ALLOWLIST if receivers is None else receivers
    within = config.FABRIC_RENEW_WITHIN_S if within_s is None else within_s
    now = now or datetime.now(timezone.utc)
    page = (await go([(CollabTools.watches, {})]))[0] or {}
    renewed = []
    for w in page.get("items") or []:
        if w.get("notification_url") not in receivers:
            continue
        expires = _parse(w.get("expires") or "")
        if expires is None or (expires - now).total_seconds() > within:
            continue
        out = (await go([(CollabTools.watch_renew, {"watch_id": w["id"]})]))[0]
        renewed.append({"id": w["id"], "resource": w.get("resource"), "expires": (out or {}).get("expires")})
    return renewed


def drives(allowlist: tuple[str, ...]) -> list[tuple[str, str]]:
    """(drive id, folder) pairs to sweep — the collab entries of the allow-list that name a drive, from the
    folder they scope (`collab:<drive>/<prefix>`) or the root."""
    out = []
    for entry in allowlist:
        source, _, scope = str(entry).partition(":")
        if source == "collab" and scope and scope != "*":
            drive, _, folder = scope.partition("/")
            out.append((drive, folder.strip("/")))
    return out


def decide(item: dict, row: dict | None) -> ArtifactChanged | None:
    """One listed FILE against what the catalog knows of it: an event when it is new or changed, None when the
    catalog already saw this version (or the item is a folder / carries no handle). Pure."""
    if item.get("folder") or not ContentHandle.is_handle(item.get("handle")):
        return None
    modified = str(item.get("modified") or "")
    # An allow-listed folder is a FOLDER, not a promise about what people put in it. The organiser's
    # Recordings folder holds the meeting transcripts the allow-list was added for AND 28 `.mp4`
    # recordings and 42 per-lane `.json` dumps, and nothing downstream filters by extension — the
    # classifier reads a file's NAME and path, never its bytes, so a raw recording would be
    # catalogued as a document with a plausible type and a draft-review approval, noise a steward
    # cannot tell from a real document. What the fabric can READ is the rule, never a deny-list of
    # what it has already met: a deny-list is wrong about every format nobody has thought of yet.
    # It bounds only what the sweep TAKES IN — a record that already exists is still told when its
    # bytes change, or the catalogue would state a version that is no longer true.
    if row is None and filetypes.kind_for(str(item.get("name") or "")) not in SWEEPABLE_KINDS:
        return None
    if row and str((row.get("pointer") or {}).get("version") or "") == modified and modified:
        return None
    pointer = {"source": "collab", "handle": str(item["handle"])}
    if modified:
        pointer["version"] = modified
    if item.get("path"):                 # the folder the sweep found it in — what a folder-scoped allow-list asks
        pointer["path"] = str(item["path"])
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
    for drive, folder in drives(allow):
        stack: list[tuple[str, int]] = [(folder, 0)]
        while stack and seen < limit:
            path, d = stack.pop()
            page = (await go([(CollabTools.list, {"drive_id": drive, "path": path})]))[0] or {}
            listed = page.get("items") or []
            # A listing PAGES, and this asks once per folder: an ignored `more` means the folder is swept in
            # part for ever, and says nothing — indistinguishable from a folder that really holds that many.
            if page.get("more"):
                print(f"[reconciler] {drive[:12]}…/{path or '(root)'}: TRUNCATED — the listing says `more` and "
                      f"the sweep reads one page, so {len(listed)} item(s) is not all of them", flush=True)
            files: list[dict] = []
            for item in listed:
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
                # Said out loud: a folder of folders is ordinary, a folder whose files were all REJECTED is
                # not, and a total cannot tell them apart.
                if listed:
                    print(f"[reconciler] {drive[:12]}…/{path or '(root)'}: listed {len(listed)}, files 0 "
                          f"(folders, or handles the contract refused)", flush=True)
                continue
            # ONE gateway session per page, not per file: the catalog is asked about every file at once
            rows = await go([(SemanticTools.catalog_get, {"pointer": {"source": "collab", "handle": f["handle"]}})
                             for f in files])
            new = 0
            for item, row in zip(files, rows):
                event = decide(item, row)
                if event is not None:
                    fabric_events.publish(event, client=client)
                    published.append(event)
                    new += 1
            # Per FOLDER, not per file: enough to tell "listed nothing" from "all already known" from
            # "truncated", which have different fixes, without a line per document on every tick.
            print(f"[reconciler] {drive[:12]}…/{path or '(root)'}: listed {len(listed)}, files {len(files)}, "
                  f"new {new}, already known {len(files) - new}", flush=True)
    return published


#: conflicts this PROCESS has already asked about. In memory on purpose: a restart re-asks at most once, and
#: `approvals.channel_events` drops what a person has already decided — the cost of forgetting is one duplicate
#: card, while the cost of a durable "asked" that outlives a withdrawn approval is a question nobody ever sees.
_ASKED: set[str] = set()


def run_once(*, call=None, client=None) -> list[ArtifactChanged]:
    r = client or _client()
    try:
        kept = asyncio.run(renew_watches(call=call))
        if kept:
            print(f"[reconciler] renewed {len(kept)} subscription(s): {[k['id'] for k in kept]}", flush=True)
    except Exception as e:                          # noqa: BLE001 — a renewal that fails is retried next tick
        print(f"[reconciler] renewal failed: {type(e).__name__}: {e}", flush=True)
    out: list[ArtifactChanged] = []
    try:
        out = asyncio.run(sweep(call=call, client=r))
        print(f"[reconciler] swept: {len(out)} change(s) published", flush=True)
    except Exception as e:                          # noqa: BLE001 — a sweep that fails runs again next tick
        print(f"[reconciler] sweep failed: {type(e).__name__}: {e}", flush=True)
    try:    # the steward's questions ride the same cadence: nothing else raises them, and an ambiguity that
            # nobody is asked about is one no document can be linked through, indefinitely and silently
        raised = asyncio.run(fabric_vocabulary.ask_open(call=call))
        if raised:
            print(f"[reconciler] asked a steward about {len(raised)} ambiguity(ies): "
                  f"{[r['term'] for r in raised]}", flush=True)
    except Exception as e:                          # noqa: BLE001 — a question that fails is asked next tick
        print(f"[reconciler] vocabulary questions failed: {type(e).__name__}: {e}", flush=True)
    try:                                            # the measurements ride the same cadence (BR-8)
        m = asyncio.run(fabric_metrics.tick(folder=config.FABRIC_WIKI_FOLDER, client=r, call=call))
        print(f"[reconciler] measured: {m['records']['total']} record(s)", flush=True)
    except Exception as e:                          # noqa: BLE001 — numbers that fail to compute are computed next tick
        print(f"[reconciler] metrics failed: {type(e).__name__}: {e}", flush=True)
    return out


def _client():
    from lab.platform import redis_client
    return redis_client.client()


def main() -> None:
    r = _client()
    waits = [config.FABRIC_SWEEP_FIRST_S]          # the first tick waits out the deploy window; the rest keep the cadence

    def tick():
        time.sleep(waits.pop(0) if waits else config.FABRIC_SWEEP_S)
        return [("sweep", {})]

    streams.serve(name=SERVICE,
                  ready=f"{SERVICE} ready  drives={len(drives(config.FABRIC_ALLOWLIST))} first={config.FABRIC_SWEEP_FIRST_S}s every={config.FABRIC_SWEEP_S}s",
                  read=tick, handle=lambda eid, f: run_once(client=r))


if __name__ == "__main__":
    main()
