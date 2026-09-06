"""Workflow run requests over Redis Streams — how a person (or another workflow) triggers a run.

Same shape as src/lab/substrate/approvals.py, for the other direction: the review app's Submit page (or any
producer) publishes ONE durable request event; each long-lived workload host consumes its own
consumer group and acks when the run is finished, writing progress back so the requester can
watch it. A missing consumer just means the request waits (durable) — nothing breaks. This is the
lab's analogue of Blob-upload -> Event Grid -> Container Apps job on Azure.

Streams / keys
  workflow:requests    XADD per request; consumer groups = GROUPS (one per workload host)
  workflow:req:<id>    hash: current state (status pending|running|done|failed + run outputs)
  workflow:pending     set of request ids not yet finished
  workflow:idem:<process>:<key>   the idempotency claim of one submission (SET NX EX) -> its request id

IDEMPOTENCY lives HERE, not in the surfaces. A run costs 600-1000 s of real tokens and stages a
human approval, so a retried submission — a connector's automatic retry, a flaky network, an
impatient user pressing the button twice — must NOT queue a second run. A caller that can name its
own submission passes `idempotency_key=`; the key is claimed with `SET NX EX` (the same atomic
primitive lab.platform.locks uses) so two concurrent retries cannot both win, and the loser is handed
the FIRST request id. Putting it in `submit()` rather than in workflow-mcp means every producer
(workflow-mcp, the review app's Submit page, the CLI, any future REST adapter) gets it by passing
one argument, and there is ONE implementation of the race.

CLI:  python -m lab.platform.workflows list | show <id> | count
                                   | request <process> <diagram-ref> [requirements-ref ...]
"""
import json
import time
import os
import sys
import uuid
from datetime import datetime, timezone

import redis

from lab.platform import redis_client
from lab.platform.contracts import PROCESSES, WORKFLOW_FINISHED, WorkflowRequest, WorkflowStatus

REQ = "workflow:requests"
# Runs that ENDED. The request stream says a run was asked for; nothing said one had finished, so
# anything wanting to act on a result had to poll for it. This is the same shape as
# `approvals:decisions`: one durable append at the single place a run is closed (`mark`), so a
# consumer group can react without every producer knowing who is listening.
DONE = "workflow:finished"
DONE_MAXLEN = 10_000                        # a bounded stream: nothing here reads history (see mark())
RECLAIM_IDLE_MS = 60_000                    # how long an unacked finished-event waits before retry
IDEM = "workflow:idem:"                     # + <process>:<key> -> the request id that claim created
IDEMPOTENCY_TTL = 24 * 60 * 60              # 24 h — see idempotency_key_for()
MAX_KEY = 200                               # a Redis key is not a payload: enough for a GUID or a message id
GROUPS = tuple(spec.group for spec in PROCESSES.values())   # DERIVED: one group per registered process
                                            # (lab.platform.contracts.PROCESSES is the ONE source)
STATUSES = tuple(s.value for s in WorkflowStatus)    # the contract (lab.platform.contracts) as wire strings


def _r(client=None):
    """`client` (a host's injected Redis — its container's Singleton) or the process-wide pooled one."""
    return client if client is not None else redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_groups(r=None):
    r = r or _r()
    for g in GROUPS:
        try:
            r.xgroup_create(REQ, g, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def idempotency_key_for(process, key):
    """`workflow:idem:<process>:<key>` — the Redis key one submission claims.

    NAMESPACED BY PROCESS so two processes may be handed the same caller-side id (a Teams message id
    submitted to two workloads) without colliding. The claim carries a TTL of `IDEMPOTENCY_TTL`
    (24 h): long enough to cover a whole run (600-1000 s), the human approval that follows it and any
    retry a connector or a person makes during a working day; short enough that the keyspace does not
    grow without bound. WHEN IT EXPIRES the key is simply free again — the SAME idempotency_key
    submitted a day later queues a NEW run. That is deliberate: the key is a RETRY window, not a
    permanent uniqueness constraint, and a caller who wants "never run this twice" must keep the
    request id it was given."""
    key = key.strip() if isinstance(key, str) else key
    if not isinstance(key, str) or not key:
        raise ValueError("idempotency_key must be a non-empty string")
    if len(key) > MAX_KEY or not key.isprintable():
        raise ValueError(f"idempotency_key must be at most {MAX_KEY} printable characters")
    return f"{IDEM}{process}:{key}"


def _failed(r, request_id) -> bool:
    """Did this run FAIL (or has its state vanished)? Only then may a repeated key start a new run.

    Deliberately narrow: pending and running are live work and must still de-duplicate, and a DONE run
    is exactly what idempotency is protecting — re-running it would stage a second human approval for
    an answer that already exists."""
    status = r.hget(f"workflow:req:{request_id}", "status")
    if status is None:
        return True                                # no state at all: nothing to protect
    status = status.decode() if isinstance(status, bytes) else status
    return status == WorkflowStatus.FAILED.value


def submit(process, inputs, requester, *, spec=None, idempotency_key=None, ttl=IDEMPOTENCY_TTL, client=None):
    """Publish a run request; returns `(request_id, duplicate)`.

    Validated by the process's OWN contract (`ProcessSpec.validate`) so workflow-mcp, the review app's
    Submit page and the CLI cannot drift apart — nothing reaches the stream unvalidated. `spec` lets a
    caller that already holds one (a server built from its own registry) pass it instead of a global
    lookup; otherwise `PROCESSES[process]` is used and an unknown process is a ValueError.

    `idempotency_key` makes a submission SAFE TO RETRY: the same key publishes ONE event and every
    later call gets the first `request_id` back with `duplicate=True` — UNLESS that run FAILED, which
    releases the key, because de-duplication exists to stop the same work happening twice and a failed
    run did none (see `idempotency_key_for` for
    the TTL and what expiry means). The claim is taken with SET NX EX — atomically, before the stream
    write — so two concurrent retries cannot both create a run; if the write then fails the claim is
    RELEASED, or every retry would return the id of a request that was never published.

    WITHOUT a key nothing is de-duplicated, DELIBERATELY: two submissions of the same diagram are two
    legitimate runs (a re-run after a prompt change, a second opinion, a fresh render). Content-based
    de-duplication would silently refuse the second one, and silently refusing work a human asked for
    is worse than the cost of a run they can see and cancel. A caller that wants retry-safety says so
    by naming its submission."""
    if spec is None:
        spec = PROCESSES.get(process)
        if spec is None:
            raise ValueError(f"unknown process {process!r}; registered: {sorted(PROCESSES)}")
    inputs = spec.validate(inputs)
    r = _r(client)
    claim = idempotency_key_for(process, idempotency_key) if idempotency_key is not None else None
    rid = f"wfr-{uuid.uuid4().hex[:12]}"
    if claim is not None and not r.set(claim, rid, nx=True, ex=int(ttl)):
        held = r.get(claim)
        held = held.decode() if isinstance(held, bytes) else held
        if held and not _failed(r, held):         # the first submission owns this key — hand back its run
            return held, True
        # The held run FAILED, or its state is gone. The claim exists to stop the same work being done
        # TWICE; a failed run did no work, so continuing to honour its key would make the submission
        # unretryable for the whole TTL — for a file-triggered producer, whose key is the file's id,
        # that means one transient error puts that file permanently out of reach for a day. Found the
        # hard way: a Power Automate flow resubmitted a failed recording and was handed the failure
        # back, identical, with nothing having run.
        r.set(claim, rid, ex=int(ttl))
    ensure_groups(r)
    fields = WorkflowRequest(request_id=rid, process=process, inputs=inputs, requester=requester,
                             created_at=_now(), created_ts=f"{time.time():.6f}").to_fields()
    try:
        r.xadd(REQ, fields)
        r.hset(f"workflow:req:{rid}", mapping=fields)
        r.sadd("workflow:pending", rid)
    except Exception:
        if claim is not None:
            r.delete(claim)                       # nothing was queued: the key must not point at a phantom
        raise
    return rid, False


def request(process, inputs, requester, *, spec=None, idempotency_key=None, client=None):
    """`submit()` for the callers that only want the id (the CLI, the review app's Submit page)."""
    return submit(process, inputs, requester, spec=spec, idempotency_key=idempotency_key, client=client)[0]


def mark(request_id, status, *, client=None, **fields):
    """Consumer-side progress: running (started_at, consumer, trace_id) / done (approval_id, …) / failed."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    r = _r(client)
    key = f"workflow:req:{request_id}"
    if not r.exists(key):
        raise KeyError(f"unknown request {request_id}")
    upd = {"status": str(status), **{k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                                for k, v in fields.items() if v is not None}}
    if status == WorkflowStatus.RUNNING and "started_at" not in upd:
        upd["started_at"] = _now()
    if status in WORKFLOW_FINISHED:
        upd.setdefault("finished_at", _now())
        r.srem("workflow:pending", request_id)
    r.hset(key, mapping=upd)
    if status in WORKFLOW_FINISHED:
        # AFTER the hash is written, never before: a consumer woken by this event immediately reads
        # the request, and announcing a result that is not yet readable is a race nobody would
        # diagnose twice. The event carries only ids — a reader fetches the rest itself.
        #
        # GUARDED, and that is the point. Closing a run is a hard requirement; announcing it is best
        # effort. The caller is `consumer.handle`, whose `except` around this call marks the run
        # FAILED — so an unguarded XADD that raised (an OOM'd Redis, a WRONGTYPE on the key, a blip
        # on the second round trip) would record a run that had already succeeded, and published its
        # outputs, as a failure. A missed announcement costs a message; that costs the truth.
        try:
            process = r.hget(key, "process") or ""
            r.xadd(DONE, {"request_id": request_id, "process": process, "status": str(status),
                          "finished_at": upd["finished_at"]},
                   # one entry per finished run, forever, on a Redis with a fixed volume. Nothing
                   # reads history here (the group starts at `$`), so old entries are only cost.
                   maxlen=DONE_MAXLEN, approximate=True)
        except Exception as e:                  # noqa: BLE001 — the run IS closed; telling is extra
            print(f"finished-event not published for {request_id}: {type(e).__name__}: {e}",
                  flush=True)
    return upd


def ensure_finished_group(group: str, r=None) -> None:
    """A consumer group on the finished-runs stream. Idempotent, like the request-side twin."""
    r = _r(r)
    try:
        r.xgroup_create(DONE, group, id="$", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def _reclaim_finished(r, group, consumer, count):
    """Entries a consumer of this group took and never acked, handed back after RECLAIM_IDLE_MS.

    The same XAUTOCLAIM the approval channels use, for the same reason: `>` returns only
    never-delivered entries, so a consumer that crashed mid-handle — or deliberately left an entry
    unacked because its send failed — would otherwise leave it in the pending list forever, visible
    to nobody. That is precisely the durability Streams were chosen over pub/sub to get. Best effort:
    a server without XAUTOCLAIM still gets what is new."""
    try:
        _cursor, entries, *_ = r.xautoclaim(DONE, group, consumer, min_idle_time=RECLAIM_IDLE_MS,
                                            start_id="0-0", count=count)
    except Exception as e:                      # noqa: BLE001 — old server, or a blip
        print(f"finished-event reclaim skipped for {group} ({type(e).__name__}: {e})", flush=True)
        return []
    return [(eid, f) for eid, f in entries if f]


def finished_events(group, consumer="1", block_ms=0, count=10, *, client=None):
    """Runs that ended and this group has not acked, RECLAIMED ones first. Starts at `$` (new events
    only), unlike the request side: a consumer of RESULTS that came up for the first time should not
    announce every run the lab ever completed."""
    r = _r(client)
    ensure_finished_group(group, r)
    stale = _reclaim_finished(r, group, consumer, count)
    got = redis_client.blocking_read(
        lambda b: r.xreadgroup(group, consumer, {DONE: ">"}, count=count, block=b), block_ms)
    return stale + [(eid, fields) for _stream, entries in got for eid, fields in entries]


def annotate(request_id, *, client=None, **fields):
    """Write extra fields onto a request WITHOUT touching its status or publishing anything.

    For a consumer of a FINISHED run that needs to leave a trace where a person will look — the
    notifier records why an announcement failed. Deliberately not `mark()`: mark re-publishes to
    `workflow:finished` for a finished status, so a notifier using it would feed itself its own
    failure forever."""
    if not fields:
        return {}
    upd = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
           for k, v in fields.items() if v is not None}
    _r(client).hset(f"workflow:req:{request_id}", mapping=upd)
    return upd


def ack_finished(group, entry_id, *, client=None):
    return _r(client).xack(DONE, group, entry_id)


def status(request_id, *, client=None):
    """The request hash, decoded symmetrically with `mark()`: every field `mark` JSON-encoded (any
    dict/list value — inputs, summary, import_artifacts, whatever a process declares next) comes back
    as the object it was. Decoding by SHAPE rather than by a list of field names keeps a new
    structured output from needing an edit here."""
    st = _r(client).hgetall(f"workflow:req:{request_id}")
    for k, v in st.items():
        if isinstance(v, str) and v[:1] in ("{", "["):
            try:
                st[k] = json.loads(v)
            except ValueError:
                pass
    return st


def _order(s):
    """Insertion order: the float `created_ts` (µs) — `created_at` is a seconds-resolution DISPLAY
    value, so two requests in one second would otherwise sort non-deterministically."""
    return (float(s.get("created_ts") or 0), s.get("created_at", ""))


def pending(*, client=None):
    r = _r(client)
    return sorted((status(i, client=r) for i in r.smembers("workflow:pending")), key=_order)


def recent(limit=20, *, client=None):
    """Most recent requests (any status), newest first — from the stream's own order."""
    r = _r(client)
    ids = [f["request_id"] for _, f in r.xrevrange(REQ, count=limit)]
    return [status(i, client=r) for i in ids]


def channel_events(group, consumer="1", block_ms=0, count=1, pending_only=False, *, client=None):
    """Read this group's unseen requests (or, with pending_only, the entries it already received
    but never acked — what a consumer re-reads after a crash). Returns [(entry_id, fields)]."""
    r = _r(client); ensure_groups(r)
    res = redis_client.blocking_read(
        lambda b: r.xreadgroup(group, f"{group}-{consumer}", {REQ: "0" if pending_only else ">"},
                               count=count, block=None if pending_only else b),
        block_ms)
    return [(eid, f) for _, entries in res for eid, f in entries]


def ack(group, entry_id, *, client=None):
    _r(client).xack(REQ, group, entry_id)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        for s in recent(30):
            print(f'{s.get("request_id")}  {s.get("status", ""):8} {s.get("process", ""):20} '
                  f'{(s.get("inputs") or {}).get("diagram", "")}  ({s.get("requester")}, {s.get("created_at")})')
    elif a[0] == "count":
        print(len(pending()))
    elif a[0] == "show":
        print(json.dumps(status(a[1]), indent=1))
    elif a[0] == "request" and len(a) >= 3:
        try:                                    # the process's own contract validates: report, don't traceback
            print(request(a[1], {"diagram": a[2], "requirements": a[3:]}, os.environ.get("USER", "cli")))
        except ValueError as e:
            sys.exit(f"rejected: {e}")
    else:
        sys.exit(__doc__)
