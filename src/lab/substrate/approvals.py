"""Approval events over Redis Streams — the lab's human-in-the-loop gate.

Why events: a write into the EA repository must wait for a person, and that person may be
at the review app, on Teams or on Telegram. Publishing one durable request event that every channel
consumes (its own consumer group, so each sees every request) and accepting the decision
from whichever channel answers first keeps the workflow/tool side channel-agnostic.

Streams / keys
  approvals:requests   XADD per request; consumer groups = CHANNELS (each channel acks its copy)
  approvals:decisions  XADD per ENDING (approve | decline | update | withdrawn) — the audit log,
                       and the ONE trail of how an approval ended, whichever way it did
  approvals:req:<id>   hash: current state of one request (fast lookup for status/await)
  approvals:pending    set of request ids still awaiting a decision

Three write entry points, deliberately. `decide()` RECORDS a decision (the raw append).
`human_decision()` VALIDATES one taken by a person — identified actor, legal decision, request still
open — and is what every human channel (Teams, the `approvals_decide` MCP tool a Copilot Studio
connector calls, this CLI) goes through, so the guarantees cannot differ per channel; a channel calls
this one and never `decide`. `withdraw()` RETIRES a question nobody is going to answer, which is not
a decision at all — see its docstring for why that distinction is the point. All three end an
approval through the one `_end()` write, so the transactional protocol cannot differ between them.

CLI (any terminal is also a channel):
  python -m lab.substrate.approvals list | show <id> | approve <id> [comment] | decline <id> [comment]
                              | update <id> <comment> | withdraw <id> <reason> | count
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone


from lab.platform import config, redis_client
from lab.platform.streams import StreamGroup
from lab.platform.contracts import APPROVAL_FINAL, ApprovalStatus, Decision, check_answer


REQ, DEC = "approvals:requests", "approvals:decisions"
CHANNELS = ("review-app", "telegram", "teams")
# Consumer groups on the DECISIONS stream. The request stream feeds humans; this one is where
# something ACTS on what a human said, and until now nothing consumed it at all. It is the only
# place where "a person answered, from whichever channel they happened to use" is a single fact,
# because every channel funnels through `human_decision` into this append.
# One group per consumer of DECISIONS. `continuations` starts the run an approval
# releases; `usecase-notifier` tells a submitter what became of their submission, and
# is a separate group so neither can consume the other's entries.
DEC_GROUPS = ("continuations", "usecase-notifier")
DECISIONS = tuple(d.value for d in Decision)         # the contract (lab.platform.contracts) as wire strings


def _r(client=None):
    """The injected client, else the process-wide pooled one (lab.platform.redis_client) — one pool per
    host, never per module. Every public function takes `client=` so a caller that already holds the
    connection (an MCP server's container, a test's fake) passes it instead of reaching for a global."""
    return client if client is not None else redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _requests(channel, consumer="1") -> StreamGroup:
    """This channel's address on the approval-request stream. `start_id="0"` — a channel added later
    must see what is still open, which is why `channel_events` filters rather than the group."""
    return StreamGroup(REQ, channel, f"{channel}-{consumer}", start_id="0")


def ensure_groups(r=None):
    for ch in CHANNELS:
        _requests(ch).ensure(_r(r))


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


def _end(r, key, fields, state, *, release=True):
    """THE write that ends an approval: the hash first, the audit stream second, rolled back together.

    ONE implementation because what it encodes is not a shape but a transactional protocol, and both
    halves of it were learned from live failures. Everything that ends an approval — a decision, a
    withdrawal — goes through here, so tightening it tightens every ending at once. (`update` passes
    `release=False`: changes requested leaves the request open.)

    ORDER. The continuation runner is woken by this stream entry and immediately reads the request
    back — `state.get("answer")` — so announcing an ending whose state is not yet readable loses it.
    It happened live: a human tagged both speakers, `check_answer` accepted the answer, and the
    continuation still died with "speaker_map is required" because it read the hash a moment too
    early. Worse than the request-stream twin, which survives because an unacked entry is redelivered:
    the continuation runner ALWAYS acks, so there is no second chance and the run is simply gone.
    `workflows.mark` states the same rule for the finished-runs stream.

    ROLLBACK. Writing the hash first means a failed append would otherwise leave the request marked
    ended with NOTHING in the audit log — something that happened for every reader and never happened
    for the record. So the prior fields are restored, the fields this ending INTRODUCED are removed,
    and the claim on `approvals:pending` goes back.
    """
    prior = {k: v for k, v in (r.hgetall(key) or {}).items() if k in state}
    r.hset(key, mapping=state)
    if release:
        r.srem("approvals:pending", fields["request_id"])
    try:
        r.xadd(DEC, fields)
    except Exception:
        if prior:
            r.hset(key, mapping=prior)
        for field in set(state) - set(prior):
            r.hdel(key, field)                  # fields this ending INTRODUCED, e.g. the answer
        if release:
            r.sadd("approvals:pending", fields["request_id"])
        raise
    return fields


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
    state = {"status": decision, "decided_by": actor, "decided_via": channel,
             "comment": comment, "decided_at": fields["decided_at"]}
    if "answer" in fields:
        state["answer"] = fields["answer"]
    return _end(r, key, fields, state, release=decision != Decision.UPDATE)


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


def withdraw(request_id, actor, reason="", channel="cli", *, client=None):
    """RETIRE an approval nobody is going to answer. Not a decision — a third way for one to end.

    A lab that is tested leaves questions behind: a run asked, the test moved on, and the card sits in
    `approvals:pending` for ever, re-announced by every channel that restarts (`channel_events` reads
    its group from `0` on purpose, so a channel added later still sees what is open). Until now the
    only closing verbs were a human's — and recording a `decline` to tidy up writes a person's name
    against a judgement they never made, which is precisely what this audit log exists to prevent.

    So it is deliberately NOT in `Decision`:

      * CLOSED — `WITHDRAWN` is in `APPROVAL_FINAL`, which is the one membership every reader already
        consults, so no channel announces it again and `human_decision` refuses to answer it. One
        edit, rather than the same rule copied into three channels and two tools.
      * SOFT — the request hash, its subject and its payload all stay. `withdraw`, not `delete`: what
        was asked is evidence, and a fresh run is only comparable with the one it replaces while the
        one it replaces is still readable.
      * RELEASES NOTHING — the withdrawal is appended to the decisions stream so there is ONE trail
        of how approvals end, and `continuations` starts a run on `approve` alone, so appearing there
        cannot smuggle in the work an approval would have released. `usecase_notifier` skips it for
        the same reason: it announces what an architect DECIDED, and this is not that.

    It records itself in the SAME hash fields a decision does (`decided_by` / `decided_via` /
    `comment` / `decided_at`), with `status` carrying the distinction. Inventing `withdrawn_by`
    alongside them would make a withdrawal invisible to every surface that already renders how an
    approval ended — including `_already`'s own message, which would then name nobody.

    An actor is required exactly as it is for a decision: retiring somebody's question is an act, and
    an act with no name against it is the thing the log is for. Refuses an already-closed request —
    a record of what a person said is never overwritten — and an unknown id.

    Returns the audit fields; ValueError for a blank actor or a closed request, KeyError for an
    unknown one.
    """
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("actor is required — a withdrawal must carry who retired the question")
    r = _r(client)
    key = f"approvals:req:{request_id}"
    st = status(request_id, client=r)
    if not st:
        raise KeyError(f"unknown request {request_id}")
    if st.get("status") in APPROVAL_FINAL:
        raise _already(st)
    # CLAIMED atomically on `approvals:pending`, exactly as `human_decision` claims a final answer,
    # and for the same measured reason: the status check above is a READ, and between it and the write
    # a person may answer through any of several concurrent channels. A check-then-act here would let
    # a withdrawal and an approval each append an ending for the same request — the hash would read
    # `withdrawn` while carrying the approver's name, and the continuation runner, which dispatches on
    # the STREAM entry, would start the run behind a question every human surface says was retired.
    if not r.srem("approvals:pending", request_id):
        raise _already(status(request_id, client=r) or st)
    fields = {"request_id": request_id, "decision": ApprovalStatus.WITHDRAWN.value, "actor": actor,
              "channel": channel, "comment": (reason or "").strip(), "decided_at": _now()}
    state = {"status": ApprovalStatus.WITHDRAWN.value, "decided_by": actor, "decided_via": channel,
             "comment": fields["comment"], "decided_at": fields["decided_at"]}
    try:
        return _end(r, key, fields, state, release=False)   # the claim above already released it
    except Exception:
        r.sadd("approvals:pending", request_id)             # ...and puts it back if the write failed
        raise


def _decisions(group, consumer="1") -> StreamGroup:
    return StreamGroup(DEC, group, consumer, start_id="0")


def ensure_decision_groups(r=None):
    """Consumer groups on the DECISIONS stream — the request-side `ensure_groups` twin. Idempotent."""
    for g in DEC_GROUPS:
        _decisions(g).ensure(_r(r))


def decision_events(group, consumer="1", block_ms=0, count=10, pending_only=False, *, client=None):
    """Decisions this group has not acked yet, RECLAIMED ones first. Same shape as the request-side
    reader, so a consumer of either stream is written the same way — and it now recovers an
    abandoned entry the same way too, which it did not before: `>` returns only entries never
    delivered, so an approved answer this runner took and never acked would have turned into a run
    that simply never started, with nothing anywhere saying so."""
    return _decisions(group, consumer).read(block_ms=block_ms, count=count,
                                            pending_only=pending_only, client=_r(client))


def ack_decision(group, entry_id, *, client=None):
    return _decisions(group).ack(entry_id, _r(client))


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
    r = _r(client)
    got = _requests(channel, consumer).read(block_ms=block_ms, count=count, client=r)
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
    _requests(channel).ack(entry_id, _r(client))


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
    elif a[0] == "withdraw":                         # retire a question nobody will answer
        print(withdraw(a[1], actor, " ".join(a[2:]), "cli"))
    else:
        sys.exit(__doc__)
