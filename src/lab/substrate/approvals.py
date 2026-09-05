"""Approval events over Redis Streams — the lab's human-in-the-loop gate.

Why events: a write into the EA repository must wait for a person, and that person may be
at the review app, on Teams or on Telegram. Publishing one durable request event that every channel
consumes (its own consumer group, so each sees every request) and accepting the decision
from whichever channel answers first keeps the workflow/tool side channel-agnostic.

Streams / keys
  approvals:requests   XADD per request; consumer groups = CHANNELS (each channel acks its copy)
  approvals:decisions  XADD per decision (approve | decline | update) — the audit log
  approvals:req:<id>   hash: current state of one request (fast lookup for status/await)
  approvals:pending    set of request ids still awaiting a decision

Two write entry points, deliberately: `decide()` RECORDS a decision (the raw append), and
`human_decision()` VALIDATES one taken by a person — identified actor, legal decision, request still
open — and is what every human channel (Teams, the `approvals_decide` MCP tool a Copilot Studio
connector calls, this CLI) goes through, so the guarantees cannot differ per channel.

CLI (any terminal is also a channel):
  python -m lab.substrate.approvals list | show <id> | approve <id> [comment] | decline <id> [comment]
                              | update <id> <comment> | count
"""
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import redis

from lab.platform import config, redis_client
from lab.platform.contracts import APPROVAL_FINAL, ApprovalStatus, Decision, check_answer

log = logging.getLogger("lab.approvals")

REQ, DEC = "approvals:requests", "approvals:decisions"
CHANNELS = ("review-app", "telegram", "teams")
# Consumer groups on the DECISIONS stream. The request stream feeds humans; this one is where
# something ACTS on what a human said, and until now nothing consumed it at all. It is the only
# place where "a person answered, from whichever channel they happened to use" is a single fact,
# because every channel funnels through `human_decision` into this append.
DEC_GROUPS = ("continuations",)
DECISIONS = tuple(d.value for d in Decision)         # the contract (lab.platform.contracts) as wire strings


def _r(client=None):
    """The injected client, else the process-wide pooled one (lab.platform.redis_client) — one pool per
    host, never per module. Every public function takes `client=` so a caller that already holds the
    connection (an MCP server's container, a test's fake) passes it instead of reaching for a global."""
    return client if client is not None else redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_groups(r=None):
    r = _r(r)
    for ch in CHANNELS:
        try:
            r.xgroup_create(REQ, ch, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def request(kind, subject, payload, requester, trace_id=None, *, client=None):
    """Publish an approval request. Returns the request id."""
    r = _r(client); ensure_groups(r)
    rid = f"apr-{uuid.uuid4().hex[:12]}"
    fields = {"request_id": rid, "kind": kind, "subject": subject, "payload": json.dumps(payload),
              "requester": requester, "trace_id": trace_id or "", "status": ApprovalStatus.PENDING.value,
              "created_at": _now(), "created_ts": f"{time.time():.6f}"}
    r.xadd(REQ, fields)
    r.hset(f"approvals:req:{rid}", mapping=fields)
    r.sadd("approvals:pending", rid)
    return rid


def decide(request_id, decision, actor, channel, comment="", *, answer=None, client=None):
    """Record a decision from any channel. 'update' = changes requested (stays open). This is the raw
    RECORDER — it does not ask whether a human made the decision or whether the request is still open;
    `human_decision()` below is the validated path every human channel goes through."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    r = _r(client)
    key = f"approvals:req:{request_id}"
    if not r.exists(key):
        raise KeyError(f"unknown request {request_id}")
    fields = {"request_id": request_id, "decision": decision, "actor": actor, "channel": channel,
              "comment": comment, "decided_at": _now()}
    # Only present when a question was actually answered. An empty key on every decision would
    # otherwise sit in the audit log forever, and would change the shape every existing consumer
    # already reads — the addition must be invisible to the approvals that ask nothing.
    if answer:
        fields["answer"] = json.dumps(answer)
    r.xadd(DEC, fields)
    state = {"status": decision, "decided_by": actor, "decided_via": channel,
             "comment": comment, "decided_at": fields["decided_at"]}
    if "answer" in fields:
        state["answer"] = fields["answer"]
    r.hset(key, mapping=state)
    if decision != Decision.UPDATE:
        r.srem("approvals:pending", request_id)
    return fields


def status(request_id, *, client=None):
    st = _r(client).hgetall(f"approvals:req:{request_id}")
    if st.get("payload"):
        st["payload"] = json.loads(st["payload"])
    if st.get("answer"):
        st["answer"] = json.loads(st["answer"])
    return st


def _already(st):
    return ValueError(f"{st['request_id']} is already {st['status']} (by {st.get('decided_by') or '?'} via "
                      f"{st.get('decided_via') or '?'} at {st.get('decided_at') or '?'}) — a final decision "
                      "is not re-decided; raise a new request instead")


def human_decision(request_id, decision, actor, channel, comment="", *, answer=None, client=None):
    """THE path a HUMAN'S decision takes, whatever carried it — the Teams/Copilot Studio inbound call,
    the `approvals_decide` MCP tool, the review channels, the CLI. One implementation, so no channel
    can decide on weaker terms than another. It adds to `decide()` (the raw recorder) exactly what a
    governed human gate needs, and nothing a channel should re-implement:

      * an IDENTIFIED human — a blank/absent `actor` is a ValueError, never an anonymous default:
        "who released this EA-repository write" is the whole point of the audit log;
      * a decision value from the contract (`Decision`);
      * a request that is still OPEN, and only ONE final answer to it. `update` = changes requested,
        so it stays open and CAN be decided later; approve/decline are final. The final answer is
        CLAIMED atomically on `approvals:pending` (SREM returns whether this caller held it), because
        there are now several concurrent writers — the review app, Telegram, the CLI and a connector
        polling the MCP tool — and a check-then-act on the status field would let two of them each
        append a final decision to the audit log.

    Returns the recorded decision fields; ValueError for a bad actor/decision/re-decision, KeyError
    for an unknown request id."""
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("actor is required — a decision must carry the human who made it")
    decision = (decision or "").strip()
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    r = _r(client)
    st = status(request_id, client=r)
    if not st:
        raise KeyError(f"unknown request {request_id}")
    if st.get("status") in APPROVAL_FINAL:
        raise _already(st)
    # Only APPROVING requires the answer. Declining is refusing to answer, and `update` means
    # "changes requested" — a reviewer saying the question itself is wrong, or that they cannot tell
    # two voices apart, must not be forced to invent a complete answer first. Both leave the request
    # in a state a later approval can still complete.
    #
    # And it is checked BEFORE the claim below: doing it after would let one malformed submission
    # burn the single final answer and lock every other channel out of a request nobody has actually
    # answered.
    answer = check_answer(st.get("payload") or {}, answer) if decision == Decision.APPROVE else None
    final = decision in APPROVAL_FINAL
    if final and not r.srem("approvals:pending", request_id):      # someone else answered first
        raise _already(status(request_id, client=r) or st)
    try:
        return decide(request_id, decision, actor, channel, (comment or "").strip(),
                      answer=answer, client=r)
    except Exception:
        if final:
            r.sadd("approvals:pending", request_id)                # the claim is released if the write failed
        raise


def _blocking(r, read, block_ms):
    """Run a BLOCKING stream read, translating a socket timeout into "nothing arrived".

    Two things go wrong with `XREAD ... BLOCK` and they cost a channel its life. The client is built
    with `socket_timeout=redis_client.SOCKET_TIMEOUT_S`, so a block at or above that timeout races the
    socket read — and at exactly 5000 ms against a 5 s timeout (what every channel used) the socket
    usually wins, raising `redis.TimeoutError` out of the loop and killing the process within seconds
    of starting. The block is therefore CLAMPED below the socket timeout so the normal path never
    depends on an exception, and the exception is still caught because a slow network can produce it
    anyway. An expired block means no events, which is `[]` — not a failure.
    """
    limit = int(redis_client.SOCKET_TIMEOUT_S * 1000) - 500
    try:
        return read(min(block_ms, limit) if block_ms else None) or []
    except redis.TimeoutError:
        return []


def ensure_decision_groups(r=None):
    """Consumer groups on the DECISIONS stream — the request-side `ensure_groups` twin. Idempotent."""
    r = _r(r)
    for g in DEC_GROUPS:
        try:
            r.xgroup_create(DEC, g, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def decision_events(group, consumer="1", block_ms=0, count=10, pending_only=False, *, client=None):
    """Decisions this group has not acked yet. Same shape as the request-side reader, so a consumer
    of either stream is written the same way."""
    r = _r(client)
    ensure_decision_groups(r)
    streams = {DEC: "0" if pending_only else ">"}
    got = _blocking(r, lambda b: r.xreadgroup(group, consumer, streams, count=count, block=b), block_ms)
    for _stream, entries in got:
        for eid, fields in entries:
            yield eid, fields


def ack_decision(group, entry_id, *, client=None):
    return _r(client).xack(DEC, group, entry_id)


def trace_url(trace_id, jaeger_url=None):
    """The link to the run that produced an approval, or None — ONE construction, shared by every
    channel that shows a human where the model came from."""
    base = (config.JAEGER_UI_URL if jaeger_url is None else jaeger_url) or ""
    return f"{base.rstrip('/')}/trace/{trace_id}" if trace_id else None


def _order(s):
    """Insertion order: the float `created_ts` (µs) — `created_at` is a seconds-resolution DISPLAY
    value, so two requests in one second would otherwise sort non-deterministically."""
    return (float(s.get("created_ts") or 0), s.get("created_at", ""))


def pending(*, client=None):
    r = _r(client)
    return sorted((status(i, client=r) for i in r.smembers("approvals:pending")), key=_order)


def history(limit=50, *, client=None):
    return [f for _, f in _r(client).xrevrange(DEC, count=limit)]


RECLAIM_IDLE_MS = 60_000   # an entry taken but unacked this long is presumed abandoned: a channel
                           # acks as soon as it has delivered, so a minute is already generous.


def _fresh(r, channel, me, count, block_ms):
    res = _blocking(r, lambda b: r.xreadgroup(channel, me, {REQ: ">"}, count=count, block=b), block_ms)
    return [(eid, f) for _, entries in res for eid, f in entries] if res else []


def _reclaim(r, channel, me, count):
    """Entries a previous consumer of this group took and never acked, handed to this one.

    XAUTOCLAIM, not XPENDING+XCLAIM: one round trip, and it skips entries whose stream message is
    gone rather than returning ids that cannot be read. Failure here is never fatal — a channel that
    cannot reclaim should still deliver what is new."""
    try:
        _cursor, entries, *_ = r.xautoclaim(REQ, channel, me, min_idle_time=RECLAIM_IDLE_MS,
                                            start_id="0-0", count=count)
    except Exception as e:                               # noqa: BLE001 — old server, or a blip
        log.debug("reclaim skipped for %s (%s: %s)", channel, type(e).__name__, e)
        return []
    return [(eid, f) for eid, f in entries if f]


def channel_events(channel, consumer="1", block_ms=0, count=20, *, only_open=True, client=None):
    """Read this channel's unseen request events (consumer group), returning
    [(entry_id, fields)]; call ack(channel, entry_id) once delivered to the human.

    `only_open` (the default) drops — and acks — events for requests a person has ALREADY decided.

    Why that belongs here and not in each channel: a channel is a NOTIFIER, and its job is "what needs
    a person now", not "everything that ever happened". The stream is durable and a channel that has
    been off (unconfigured, crashed, added later) accumulates a backlog of requests that were decided
    long ago through some other channel. Announcing those on startup is not thoroughness — it buries
    the few that matter and teaches people to ignore the channel. Measured on this lab's own stream:
    216 requests, 11 still open, so a newly-configured channel would have posted 59 cards of which 48
    needed nobody.

    They are ACKED rather than merely skipped, because leaving them unacked keeps them in the group's
    pending list forever, where they look like undelivered work. A decided request needs no delivery.
    An UNKNOWN request (its hash expired or was removed) is treated the same way: there is nothing to
    show a human and nothing to come back for.

    It also RECLAIMS what a previous consumer of this channel took and never acked. `>` returns only
    entries never delivered to the group, so anything a crashed channel had in flight stays in its
    pending list forever and is never shown to anybody — which would make a crash lose approvals
    silently, the exact failure Streams were chosen over pub/sub to prevent. This is not theoretical:
    the Teams channel died on its first start (a blocking read racing the socket timeout, fixed in
    `_blocking`) and left ten OPEN approvals stranded, invisible to the restarted process.

    Pass `only_open=False` for an audit or replay consumer that genuinely wants every event.
    """
    r = _r(client); ensure_groups(r)
    me = f"{channel}-{consumer}"
    got = _reclaim(r, channel, me, count) + _fresh(r, channel, me, count, block_ms)
    if not only_open:
        return got
    open_ = []
    for eid, f in got:
        st = r.hgetall(f'approvals:req:{f.get("request_id")}')
        # `APPROVAL_FINAL`, not `== PENDING`: `update` means CHANGES REQUESTED, which leaves the
        # request open for a later approval to complete — a channel coming back must still show it.
        # An empty hash (expired or removed) counts as closed: nothing to show, nothing to return for.
        if st and st.get("status") not in APPROVAL_FINAL:
            open_.append((eid, f))
        else:
            ack(channel, eid, client=r)     # decided, or gone: nothing for a human to do
    return open_


def ack(channel, entry_id, *, client=None):
    _r(client).xack(REQ, channel, entry_id)


def await_decision(request_id, timeout_s=300, poll_s=2, *, client=None):
    end = time.time() + timeout_s
    while time.time() < end:
        st = status(request_id, client=client)
        if st.get("status") in APPROVAL_FINAL:
            return st
        time.sleep(poll_s)
    return status(request_id, client=client)


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
    elif a[0] in DECISIONS:                          # the terminal is a channel like any other
        print(human_decision(a[1], a[0], actor, "cli", " ".join(a[2:])))
    else:
        sys.exit(__doc__)
