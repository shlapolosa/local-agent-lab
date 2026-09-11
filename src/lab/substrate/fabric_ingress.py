"""fabric-ingress — the fabric's ONE consumer of change: Event Filtering and Change Attribution (FRS 5.1.2,
5.1.3), then `submit("artifact_intake")`. Two readers feed it:

  workflow:finished   every lab run that ended: its delivered outputs become ArtifactChanged events
                      (the lab's own workflows are the producers — plan v3), with `produced_by` and the
                      delivery context the run knew
  fabric:events       what the source adapters published (a Graph notification received by graph-mcp,
                      a reconciler sweep, the test CLI)

Both end in the same place: allow-list, drop what the fabric itself wrote (the loop guard), then ONE
submit per pointer+version — de-duplicated by `workflows.submit`'s own idempotency claim, so a retried
notification and a reclaimed entry cannot both queue a 10-minute run.

ACKS when the decision is made, whichever way it went; a failure to SUBMIT is left unacked so the
reclaim gives it back (streams were chosen over pub/sub for exactly that), and after MAX_ATTEMPTS it is
parked in the dead-letter stream where a person can see it.

Run: .venv/bin/python -m lab.substrate.fabric_ingress
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from lab.core import ids
from lab.core.collab.model import ContentHandle
from lab.platform import config, delivery, fabric_events, redis_client, streams, workflows
from lab.platform.contracts import ARTIFACT_INTAKE, PROCESSES, ArtifactChanged, ArtifactRef, WorkflowStatus

SERVICE = "fabric-ingress"
FINISHED_GROUP = "fabric-ingress"
CONSUMER = "1"
#: The lab processes whose finished runs produce managed artifacts. The fabric's own two are excluded:
#: their finish is the END of the loop, not another trip round it.
PRODUCERS = tuple(p for p in PROCESSES if p not in (ARTIFACT_INTAKE.name, "artifact_publish"))


# ----------------------------------------------------------------------------- finished runs -> events
def events_from_run(state: dict) -> list[ArtifactChanged]:
    """Every artifact a finished run wrote, as an event each. PURE.

    `delivered` (what a run put into the collaboration platform) yields collab pointers; the run's
    own `*_ref` outputs are lab-store artifacts and yield `lab` pointers. Only DONE runs of a
    producing process count."""
    if state.get("status") != WorkflowStatus.DONE.value or state.get("process") not in PRODUCERS:
        return []
    ctx = delivery.from_run(state)
    actor = str(state.get("requester") or "")
    when = str(state.get("finished_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out: list[ArtifactChanged] = []
    seen: set[str] = set()
    # A meeting deliberately produces up to three DONE runs over one recording, one per speech provider,
    # each delivering its own pair under distinct names. The LANE rides on the pointer so the fabric sees
    # three lanes of one comparison, not three competing versions of one document.
    lane = {"lane": str(inputs.get("provider"))} if isinstance(inputs := state.get("inputs") or {}, dict) and inputs.get("provider") else {}
    for item in state.get("delivered") or []:
        handle = item.get("handle") if isinstance(item, dict) else None
        if not ContentHandle.is_handle(handle) or handle in seen:
            continue
        seen.add(handle)
        out.append(ArtifactChanged(event_id=ids.ulid(), pointer={"source": "collab", "handle": handle, **lane},
                                   source_kind="collab", change="created", actor_oid=actor, occurred_at=when,
                                   produced_by=str(state["process"]), context=ctx.key if ctx else ""))
    for key, value in state.items():
        if key.endswith("_ref") and isinstance(value, str) and ArtifactRef.is_ref(value) and value not in seen:
            seen.add(value)
            out.append(ArtifactChanged(event_id=ids.ulid(), pointer={"source": "lab", "ref": value, **lane},
                                       source_kind="lab", change="created", actor_oid=actor, occurred_at=when,
                                       produced_by=str(state["process"]), context=ctx.key if ctx else ""))
    return out


# ----------------------------------------------------------------------------- filtering and attribution
def admitted(event: ArtifactChanged, allowlist: tuple[str, ...] = None) -> bool:
    """Event Filtering: `lab` sources are ours and always admitted; every other source needs an
    allow-list entry `<source>:<scope>` or `<source>:*`. EMPTY allow-list admits nothing external."""
    allow = config.FABRIC_ALLOWLIST if allowlist is None else allowlist
    if event.source_kind == "lab":
        return True
    scope = ""
    if event.source_kind == "collab" and event.pointer.get("handle"):
        scope = ContentHandle.parse(event.pointer["handle"]).scope
    else:
        scope = event.pointer.get("project") or event.pointer.get("scope") or ""
    return f"{event.source_kind}:*" in allow or (bool(scope) and f"{event.source_kind}:{scope}" in allow)


def attributed(event: ArtifactChanged, *, client) -> ArtifactChanged:
    """Change Attribution: an event for a write the fabric itself made carries the fabric tag, whether
    the adapter set one or the loop guard's memory says so."""
    if event.is_fabric_originated:
        return event
    tag = fabric_events.written_by_fabric(event.pointer_key, event.pointer.get("version", ""), client=client)
    if not tag:
        return event
    return ArtifactChanged(**{**event.__dict__, "fabric_tag": tag})


def idempotency_key(event: ArtifactChanged) -> str:
    return f"{event.pointer_key}@{event.pointer.get('version', '')}"[:200]


def submit_for(event: ArtifactChanged, *, client) -> tuple[str, bool] | None:
    """Filter, attribute, then submit ONE intake run. Returns (request_id, duplicate) or None when the
    event was dropped — and says why on stdout, because a dropped event that nobody can explain is the
    silent failure this module exists to prevent."""
    if not admitted(event):
        print(f"[ingress] dropped {event.pointer_key}: not on FABRIC_ALLOWLIST", flush=True)
        return None
    event = attributed(event, client=client)
    if event.is_fabric_originated:
        print(f"[ingress] dropped {event.pointer_key}: fabric-originated ({event.fabric_tag.get('kind')})", flush=True)
        return None
    inputs = {"pointer": event.pointer, "event_id": event.event_id}
    if event.context:
        inputs["context"] = event.context
    if event.produced_by:
        inputs["produced_by"] = event.produced_by
    return workflows.submit(ARTIFACT_INTAKE.name, inputs, SERVICE, idempotency_key=idempotency_key(event), client=client)


# ----------------------------------------------------------------------------- the two handlers
def handle_finished(entry_id: str, fields: dict, *, client) -> list[str]:
    """One finished run -> N events -> N submits. Always acks: a run that produced nothing for the
    fabric is a decision, not a failure."""
    started: list[str] = []
    try:
        state = workflows.status(fields.get("request_id", ""), client=client)
        for event in events_from_run(state):
            got = submit_for(event, client=client)
            if got and not got[1]:
                started.append(got[0])
    except Exception as e:                    # noqa: BLE001 — one run must not stop the rest
        print(f"[ingress] finished {fields.get('request_id')}: {type(e).__name__}: {e}", flush=True)
    finally:
        workflows.ack_finished(FINISHED_GROUP, entry_id, client=client)
    return started


def handle_event(entry_id: str, fields: dict, *, client) -> str | None:
    """One adapter-published event -> at most one submit. A malformed event is dead-lettered at once
    (retrying cannot fix its shape); a failed submit is retried by reclaim, then dead-lettered."""
    try:
        event = ArtifactChanged.from_fields(fields)
    except ValueError as e:
        fabric_events.dead_letter(entry_id, fields, f"malformed: {e}", client=client)
        return None
    try:
        got = submit_for(event, client=client)
        fabric_events.ack(entry_id, client=client)
        return got[0] if got and not got[1] else None
    except Exception as e:                    # noqa: BLE001 — leave unacked for reclaim, then park
        if fabric_events.attempts(entry_id, client=client) >= fabric_events.MAX_ATTEMPTS:
            fabric_events.dead_letter(entry_id, fields, f"{type(e).__name__}: {e}", client=client)
        else:
            print(f"[ingress] {event.pointer_key}: {type(e).__name__}: {e} (will retry)", flush=True)
        return None


def run_once(*, client=None, block_ms: int = 0) -> list[str]:
    r = client or redis_client.client()
    workflows.ensure_finished_group(FINISHED_GROUP, r)
    fabric_events.ensure_group(r)
    started: list[str] = []
    for eid, f in workflows.finished_events(FINISHED_GROUP, CONSUMER, block_ms=block_ms, count=20, client=r):
        started += handle_finished(eid, f, client=r)
    for eid, f in fabric_events.events(CONSUMER, block_ms=block_ms, count=20, client=r):
        rid = handle_event(eid, f, client=r)
        if rid:
            started.append(rid)
    return started


def dispatch(kind: str, entry: tuple[str, dict], *, client) -> list[str] | str | None:
    """One item of the two-stream read, as `streams.serve` hands it over: `serve` unpacks each read item as
    `(id, fields)` and calls `handle(id, fields)` — here the "id" is which stream it came from and the
    "fields" the stream's own `(entry id, fields)` pair. Measured live: a lambda taking one argument was
    called with two, and every event sat unacked behind a TypeError."""
    eid, fields = entry
    return handle_finished(eid, fields, client=client) if kind == "finished" else handle_event(eid, fields, client=client)


def main() -> None:
    from lab.platform import container
    root = container.build(SERVICE)
    root.tracer()
    r = root.redis()
    workflows.ensure_finished_group(FINISHED_GROUP, r)
    fabric_events.ensure_group(r)
    print(f"{SERVICE}: producers={list(PRODUCERS)} allowlist={list(config.FABRIC_ALLOWLIST) or 'EMPTY (external sources refused)'}", flush=True)

    def read():
        return ([("finished", e) for e in workflows.finished_events(FINISHED_GROUP, CONSUMER, block_ms=streams.BLOCK_MS // 2, count=20, client=r)]
                + [("event", e) for e in fabric_events.events(CONSUMER, block_ms=streams.BLOCK_MS // 2, count=20, client=r)])

    streams.serve(name=SERVICE, ready=f"{SERVICE} ready", read=read,
                  handle=lambda kind, entry: dispatch(kind, entry, client=r))


if __name__ == "__main__":
    main()
