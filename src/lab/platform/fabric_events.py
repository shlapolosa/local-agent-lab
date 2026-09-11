"""Port 1 of the Documentation Fabric — the Change Events product (docs/fabric/notes/2026-09-11-ports-adapters-events.md).

  fabric:events        XADD per ArtifactChanged; ONE consumer group, the fabric's ingress
  fabric:events:dead   entries the ingress gave up on after MAX_ATTEMPTS, kept for a person
  fabric:written:<key> what the fabric itself wrote (pointer key -> version, kind, run): the loop
                       guard's memory, so an event for a write the fabric made is dropped by Change
                       Attribution rather than re-entering the pipeline (principle 1, FRS 5.1.3)

Reading goes through `lab.platform.streams.StreamGroup` — reclaim of abandoned entries, bounded
blocking — for the same reasons every other stream in the lab does. `emit` is the manual trigger for
tests: in-process, so an outside caller still cannot start intake (plan §Exposure).
"""
from __future__ import annotations

import json
import sys

from lab.core import ids
from lab.platform import config, redis_client, streams
from lab.platform.contracts import ArtifactChanged

STREAM = config.FABRIC_EVENTS
DEAD = STREAM + ":dead"
GROUP = "fabric-ingress"
MAXLEN = 50_000
MAX_ATTEMPTS = 3
WRITTEN = "fabric:written:"
WRITTEN_TTL = 7 * 24 * 60 * 60


def _r(client=None):
    return client or redis_client.client()


def _group(consumer: str = "1") -> streams.StreamGroup:
    # "0": a stream of WORK — an ingress that was down must run what queued while it was down.
    return streams.StreamGroup(STREAM, GROUP, consumer, start_id="0")


def ensure_group(client=None) -> None:
    _group().ensure(_r(client))


def publish(event: ArtifactChanged, *, client=None) -> str:
    """One event onto the stream. Returns the entry id."""
    return _r(client).xadd(STREAM, event.to_fields(), maxlen=MAXLEN, approximate=True)


def events(consumer: str = "1", block_ms: int = 0, count: int = 10, *, client=None) -> list[tuple[str, dict]]:
    return _group(consumer).read(block_ms=block_ms, count=count, client=_r(client))


def ack(entry_id: str, *, client=None) -> None:
    _group().ack(entry_id, _r(client))


def attempts(entry_id: str, *, client=None) -> int:
    """How many times this entry has been handed out, from the group's own pending list."""
    r = _r(client)
    try:
        for row in r.xpending_range(STREAM, GROUP, min=entry_id, max=entry_id, count=1):
            return int(row.get("times_delivered") or row.get("delivered") or 1)
    except Exception:                          # noqa: BLE001 — an old server, or a fake without it
        pass
    return 1


def dead_letter(entry_id: str, fields: dict, reason: str, *, client=None) -> None:
    """Give up on an entry: park it where a person can see it, then ack so it stops recirculating."""
    r = _r(client)
    r.xadd(DEAD, {**{k: str(v) for k, v in fields.items()}, "reason": reason[:300], "entry_id": entry_id},
           maxlen=MAXLEN, approximate=True)
    ack(entry_id, client=r)
    print(f"[fabric:events] dead-lettered {entry_id} ({fields.get('pointer', '?')[:80]}): {reason[:160]}", flush=True)


# ----------------------------------------------------------------------------- the loop guard's memory
def mark_written(pointer_key: str, version: str, kind: str, run_id: str, *, client=None) -> None:
    """Record that the fabric wrote this item at this version. Called by whoever holds the write — today
    the projector — AFTER the write lands, never before. An EMPTY version tags every version of the item:
    right for a page the fabric owns outright, wrong for anything a person is expected to edit."""
    _r(client).set(WRITTEN + pointer_key, json.dumps({"version": version, "kind": kind, "runId": run_id}),
                   ex=WRITTEN_TTL)


def written_by_fabric(pointer_key: str, version: str = "", *, client=None) -> dict | None:
    """The fabric tag for an item the fabric wrote, or None. With a version, only that version matches:
    a later edit by a person is a real change and must enter the pipeline."""
    raw = _r(client).get(WRITTEN + pointer_key)
    if not raw:
        return None
    tag = json.loads(raw)
    if version and tag.get("version") and str(tag["version"]) != str(version):
        return None
    return tag


# ----------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """`python -m lab.platform.fabric_events emit '<ArtifactChanged json>'` — the test trigger."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "emit":
        print("usage: python -m lab.platform.fabric_events emit '<json>'", file=sys.stderr)
        return 2
    d = json.loads(argv[1])
    event = ArtifactChanged(event_id=d.get("eventId") or d.get("event_id") or ids.ulid(),
                            pointer=d["pointer"], source_kind=d.get("sourceKind") or d.get("source_kind") or d["pointer"]["source"],
                            change=d.get("change", "updated"), actor_oid=d.get("actor", {}).get("oid", "") if isinstance(d.get("actor"), dict) else d.get("actor_oid", ""),
                            occurred_at=d.get("occurredAt") or d.get("occurred_at") or "", fabric_tag=d.get("fabricTag"),
                            produced_by=d.get("producedBy") or d.get("produced_by") or "", context=d.get("context") or "")
    print(publish(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
