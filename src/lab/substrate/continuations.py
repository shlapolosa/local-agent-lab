"""The continuation runner: what turns "a human approved" into "the next run started".

The approval gate is TERMINAL by construction. A run stages its question, publishes it and ends; the
host closes the run log and the consumer acks the request. Until now nothing consumed the decisions
stream at all, so approving something released nothing — a person answered and the answer sat there.

This is the smallest honest thing that closes that loop, and the reason it sits HERE rather than in
any channel is that `approvals:decisions` is the only place where "a person answered, from whichever
channel they happened to use" is a single fact. Every channel — the review app, chat, the command
line, a low-code connector calling the MCP tool — funnels through `approvals.human_decision` into
that one append. Putting the logic in a channel would mean writing it four times and getting it
wrong three.

WHAT APPROVING RELEASES IS DECLARED BY THE ASKER, on the approval payload, not in a registry: a
static "A is followed by B" edge cannot carry the run-specific inputs of THIS run.

Deliberately bounded, and each bound is a decision:
  * only `approve` continues — `decline` releases nothing and `update` means "changes requested", so
    the request stays open and may be approved later;
  * exactly one continuation per approval; no chains, no conditionals, no fan-out;
  * the approval id is the IDEMPOTENCY KEY, so a redelivered decision (a crash before the ack)
    queues nothing and returns the same run;
  * it never creates an approval and never decides one. It acts on decisions; it does not make them.

Run: .venv/bin/python -m lab.substrate.continuations
"""
from __future__ import annotations

import signal
import sys
import time

from lab.platform import config, workflows
from lab.platform.contracts import Decision, continuation_of
from lab.substrate import approvals

SERVICE = "continuations"
GROUP = approvals.DEC_GROUPS[0]
CONSUMER = "1"
BLOCK_MS = 3000            # under the Redis client's socket timeout, like every other consumer here

_stop = False


def _handle(entry_id: str, fields: dict, *, client) -> str | None:
    """One decision. Returns the request id of the run it started, or None.

    ALWAYS acks, even when it starts nothing. An entry left unacked is redelivered forever and every
    later decision queues up behind it, so a single malformed continuation would stop the whole
    mechanism for everyone. A failure is recorded on the request, where a human can see it.
    """
    rid = fields.get("request_id", "")
    started = None
    try:
        if fields.get("decision") != Decision.APPROVE:
            return None                                  # decline releases nothing; update stays open
        state = approvals.status(rid, client=client)
        cont = continuation_of(state.get("payload") or {})
        if cont is None:
            return None                                  # most approvals release nothing at all
        inputs = dict(cont.inputs)
        if cont.answer_input:
            inputs[cont.answer_input] = state.get("answer") or {}
        # The process's OWN contract validates these inputs inside submit(), so a malformed answer is
        # refused loudly at this boundary rather than inside a workload an hour later.
        started, duplicate = workflows.submit(
            cont.process, inputs, cont.requester or fields.get("actor") or SERVICE,
            idempotency_key=rid, client=client)
        print(f"{rid} approved -> {cont.process} {started}"
              f"{' (already queued)' if duplicate else ''}", flush=True)
        return None if duplicate else started
    except Exception as e:                               # noqa: BLE001 — the stream must not wedge
        _record_failure(rid, e, client=client)
        return None
    finally:
        approvals.ack_decision(GROUP, entry_id, client=client)


def _record_failure(request_id: str, error: Exception, *, client) -> None:
    """Put the failure where a human will find it: on the approval they just answered."""
    text = f"{type(error).__name__}: {error}"[:300]
    print(f"continuation for {request_id} failed — {text}", file=sys.stderr, flush=True)
    try:
        client.hset(f"approvals:req:{request_id}", mapping={"continuation_error": text})
    except Exception:                                    # noqa: BLE001 — never fail while failing
        pass


def run_once(*, client=None, pending_only: bool = False) -> list[str]:
    """One pass over whatever this group has not acked. Returns the run ids actually started."""
    # resolved ONCE: reading the stream and acting on it must use the same connection, or a caller
    # that injected a fake would silently have half the work done against the real one.
    r = client if client is not None else _client()
    events = list(approvals.decision_events(GROUP, CONSUMER, block_ms=0, count=50,
                                            pending_only=pending_only, client=r))
    return [rid for rid in (_handle(eid, fields, client=r) for eid, fields in events) if rid]


def _client():
    from lab.platform import redis_client
    return redis_client.client()


def main() -> None:
    def _request_stop(*_a):
        global _stop
        _stop = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)
    r = _client()
    approvals.ensure_decision_groups(r)
    print(f"continuation runner ready  group={GROUP} consumer={CONSUMER} "
          f"review={config.REVIEW_APP_URL}", flush=True)
    # crash hygiene: anything this consumer took before but never acked
    run_once(client=r, pending_only=True)
    while not _stop:
        for eid, fields in approvals.decision_events(GROUP, CONSUMER, block_ms=BLOCK_MS, count=10,
                                                     client=r):
            _handle(eid, fields, client=r)
        time.sleep(0.1)
    print("continuation runner stopped", flush=True)


if __name__ == "__main__":
    main()
