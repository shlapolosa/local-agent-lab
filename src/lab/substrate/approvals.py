"""Approval events over Redis Streams — the lab's human-in-the-loop gate.

Why events: a write into the EA repository must wait for a person, and that person may be
at the review app or on Telegram. Publishing one durable request event that every channel
consumes (its own consumer group, so each sees every request) and accepting the decision
from whichever channel answers first keeps the workflow/tool side channel-agnostic.

Streams / keys
  approvals:requests   XADD per request; consumer groups = CHANNELS (each channel acks its copy)
  approvals:decisions  XADD per decision (approve | decline | update) — the audit log
  approvals:req:<id>   hash: current state of one request (fast lookup for status/await)
  approvals:pending    set of request ids still awaiting a decision

CLI (any terminal is also a channel):
  python -m lab.substrate.approvals list | show <id> | approve <id> [comment] | decline <id> [comment]
                              | update <id> <comment> | count
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import redis

from lab.platform import redis_client
from lab.platform.contracts import APPROVAL_FINAL, ApprovalStatus, Decision

REQ, DEC = "approvals:requests", "approvals:decisions"
CHANNELS = ("review-app", "telegram")
DECISIONS = tuple(d.value for d in Decision)         # the contract (lab.platform.contracts) as wire strings


def _r():
    """The process-wide pooled client (lab.platform.redis_client) — one pool per host, never per module."""
    return redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_groups(r=None):
    r = r or _r()
    for ch in CHANNELS:
        try:
            r.xgroup_create(REQ, ch, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def request(kind, subject, payload, requester, trace_id=None):
    """Publish an approval request. Returns the request id."""
    r = _r(); ensure_groups(r)
    rid = f"apr-{uuid.uuid4().hex[:12]}"
    fields = {"request_id": rid, "kind": kind, "subject": subject, "payload": json.dumps(payload),
              "requester": requester, "trace_id": trace_id or "", "status": ApprovalStatus.PENDING.value,
              "created_at": _now(), "created_ts": f"{time.time():.6f}"}
    r.xadd(REQ, fields)
    r.hset(f"approvals:req:{rid}", mapping=fields)
    r.sadd("approvals:pending", rid)
    return rid


def decide(request_id, decision, actor, channel, comment=""):
    """Record a decision from any channel. 'update' = changes requested (stays open)."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    r = _r()
    key = f"approvals:req:{request_id}"
    if not r.exists(key):
        raise KeyError(f"unknown request {request_id}")
    fields = {"request_id": request_id, "decision": decision, "actor": actor, "channel": channel,
              "comment": comment, "decided_at": _now()}
    r.xadd(DEC, fields)
    r.hset(key, mapping={"status": decision, "decided_by": actor, "decided_via": channel,
                         "comment": comment, "decided_at": fields["decided_at"]})
    if decision != Decision.UPDATE:
        r.srem("approvals:pending", request_id)
    return fields


def status(request_id):
    st = _r().hgetall(f"approvals:req:{request_id}")
    if st.get("payload"):
        st["payload"] = json.loads(st["payload"])
    return st


def _order(s):
    """Insertion order: the float `created_ts` (µs) — `created_at` is a seconds-resolution DISPLAY
    value, so two requests in one second would otherwise sort non-deterministically."""
    return (float(s.get("created_ts") or 0), s.get("created_at", ""))


def pending():
    r = _r()
    return sorted((status(i) for i in r.smembers("approvals:pending")), key=_order)


def history(limit=50):
    return [f for _, f in _r().xrevrange(DEC, count=limit)]


def channel_events(channel, consumer="1", block_ms=0, count=20):
    """Read this channel's unseen request events (consumer group), returning
    [(entry_id, fields)]; call ack(channel, entry_id) once delivered to the human."""
    r = _r(); ensure_groups(r)
    res = r.xreadgroup(channel, f"{channel}-{consumer}", {REQ: ">"}, count=count, block=block_ms or None)
    return [(eid, f) for _, entries in res for eid, f in entries] if res else []


def ack(channel, entry_id):
    _r().xack(REQ, channel, entry_id)


def await_decision(request_id, timeout_s=300, poll_s=2):
    end = time.time() + timeout_s
    while time.time() < end:
        st = status(request_id)
        if st.get("status") in APPROVAL_FINAL:
            return st
        time.sleep(poll_s)
    return status(request_id)


if __name__ == "__main__":
    a = sys.argv[1:]
    actor = os.environ.get("USER", "cli")
    if not a or a[0] == "list":
        for s in pending():
            print(f'{s["request_id"]}  {s["status"]:8} {s["kind"]:13} {s["subject"]}  ({s["requester"]}, {s["created_at"]})')
    elif a[0] == "count":
        print(len(pending()))
    elif a[0] == "show":
        print(json.dumps(status(a[1]), indent=1))
    elif a[0] in DECISIONS:
        print(decide(a[1], a[0], actor, "cli", " ".join(a[2:])))
    else:
        sys.exit(__doc__)
