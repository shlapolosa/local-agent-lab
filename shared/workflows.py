"""Workflow run requests over Redis Streams — how a person (or another workflow) triggers a run.

Same shape as shared/approvals.py, for the other direction: the review app's Submit page (or any
producer) publishes ONE durable request event; each long-lived workload host consumes its own
consumer group and acks when the run is finished, writing progress back so the requester can
watch it. A missing consumer just means the request waits (durable) — nothing breaks. This is the
lab's analogue of Blob-upload -> Event Grid -> Container Apps job on Azure.

Streams / keys
  workflow:requests    XADD per request; consumer groups = GROUPS (one per workload host)
  workflow:req:<id>    hash: current state (status pending|running|done|failed + run outputs)
  workflow:pending     set of request ids not yet finished

CLI:  python shared/workflows.py list | show <id> | count
                                   | request <process> <diagram-ref> [requirements-ref ...]
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import redis

REQ = "workflow:requests"
GROUPS = ("wf-visio",)                      # one consumer group per workload host
STATUSES = ("pending", "running", "done", "failed")


def _approvals():
    """Reuse approvals' pooled Redis client (one small pool per process, not one per module)."""
    try:
        from . import approvals
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from shared import approvals
    return approvals


def _r():
    return _approvals()._r()


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


def request(process, inputs, requester):
    """Publish a run request. `inputs` = {"diagram": art://…, "requirements": [art://…]}."""
    r = _r(); ensure_groups(r)
    rid = f"wfr-{uuid.uuid4().hex[:12]}"
    fields = {"request_id": rid, "process": process, "inputs": json.dumps(inputs),
              "requester": requester, "status": "pending", "created_at": _now()}
    r.xadd(REQ, fields)
    r.hset(f"workflow:req:{rid}", mapping=fields)
    r.sadd("workflow:pending", rid)
    return rid


def mark(request_id, status, **fields):
    """Consumer-side progress: running (started_at, consumer, trace_id) / done (approval_id, …) / failed."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    r = _r()
    key = f"workflow:req:{request_id}"
    if not r.exists(key):
        raise KeyError(f"unknown request {request_id}")
    upd = {"status": status, **{k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                                for k, v in fields.items() if v is not None}}
    if status == "running" and "started_at" not in upd:
        upd["started_at"] = _now()
    if status in ("done", "failed"):
        upd.setdefault("finished_at", _now())
        r.srem("workflow:pending", request_id)
    r.hset(key, mapping=upd)
    return upd


def status(request_id):
    st = _r().hgetall(f"workflow:req:{request_id}")
    for k in ("inputs", "summary"):
        if st.get(k):
            try:
                st[k] = json.loads(st[k])
            except ValueError:
                pass
    return st


def pending():
    r = _r()
    return sorted((status(i) for i in r.smembers("workflow:pending")), key=lambda s: s.get("created_at", ""))


def recent(limit=20):
    """Most recent requests (any status), newest first — from the stream's own order."""
    ids = [f["request_id"] for _, f in _r().xrevrange(REQ, count=limit)]
    return [status(i) for i in ids]


def channel_events(group, consumer="1", block_ms=0, count=1, pending_only=False):
    """Read this group's unseen requests (or, with pending_only, the entries it already received
    but never acked — what a consumer re-reads after a crash). Returns [(entry_id, fields)]."""
    r = _r(); ensure_groups(r)
    res = r.xreadgroup(group, f"{group}-{consumer}", {REQ: "0" if pending_only else ">"},
                       count=count, block=None if pending_only else (block_ms or None))
    return [(eid, f) for _, entries in res for eid, f in entries] if res else []


def ack(group, entry_id):
    _r().xack(REQ, group, entry_id)


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
        print(request(a[1], {"diagram": a[2], "requirements": a[3:]}, os.environ.get("USER", "cli")))
    else:
        sys.exit(__doc__)
