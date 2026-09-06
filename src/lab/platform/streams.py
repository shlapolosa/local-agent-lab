"""Reading a Redis stream as a consumer group, and serving one — the ONE home for both.

There are four streams in this lab (`workflow:requests`, `workflow:finished`, `approvals:requests`,
`approvals:decisions`) and five long-lived processes reading them. Each had grown its own copy of the
same two things, and the copies had drifted in ways that were not decisions:

  * two readers RECLAIMED entries a crashed consumer had taken and never acked, and two did not —
    so a crash lost work silently on half the streams. That is the exact durability Streams were
    chosen over pub/sub to provide, and it is not theoretical: a channel died on its first start and
    left ten OPEN approvals stranded, invisible to the process that replaced it;
  * three loops caught a Redis blip, backed off and kept serving; the two approval CHANNELS did not,
    and were killed mid-delivery by a signal because they had no handler either. The comment in
    `continuations.main` records what an unguarded loop costs — the fix reached the two newer loops
    and never came back to the two older ones, because there was nothing shared to fix.

So: `StreamGroup` is how a stream is read, and `serve` is how a process reads one for its lifetime.
A caller supplies only what is genuinely its own — which stream, which group, and what to do with an
entry. Domain policy stays with the domain (an approval channel still decides that a decided request
needs no delivery); mechanics live here.

This is also the Azure seam. Service Bus or Event Grid replaces the two functions below, and the five
callers do not change.
"""
from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

import redis

from lab.platform import config, redis_client

# Under the client's socket timeout on purpose — `redis_client.blocking_read` explains why, and a
# channel died of getting it wrong. Every consumer here uses the same value unless it says otherwise.
BLOCK_MS = 3000
BACKOFF_S = 5              # after a blip: long enough not to spin, short enough to recover
RECLAIM_IDLE_MS = 60_000   # how long an unacked entry waits before another consumer may take it


@dataclass(frozen=True)
class StreamGroup:
    """One stream, one consumer group, one consumer name — the address a process reads from."""

    stream: str
    group: str
    consumer: str = "1"
    start_id: str = "$"     # "$" = only what happens next; "0" = everything the stream still holds

    def ensure(self, client=None) -> None:
        """Create the group if it is not there. Idempotent: BUSYGROUP is the expected answer on
        every start after the first, and anything else is a real misconfiguration that must not be
        hidden behind "no events ever arrive"."""
        try:
            _r(client).xgroup_create(self.stream, self.group, id=self.start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def read(self, *, block_ms: int = 0, count: int = 10, pending_only: bool = False,
             reclaim: bool = True, client=None) -> list[tuple[str, dict]]:
        """This group's entries as [(entry_id, fields)], reclaimed ones first.

        `pending_only` re-reads what this CONSUMER took and never acked — the crash-hygiene pass a
        process does on start. `reclaim` picks up what ANY consumer of the group abandoned, which is
        what makes a crash a delay rather than a loss; it is best effort, so a server without
        XAUTOCLAIM still gets what is new.
        """
        r = _r(client)
        self.ensure(r)
        stale = [] if (pending_only or not reclaim) else self._reclaim(r, count)
        got = redis_client.blocking_read(
            lambda b: r.xreadgroup(self.group, self.consumer,
                                   {self.stream: "0" if pending_only else ">"},
                                   count=count, block=None if pending_only else b),
            block_ms)
        return stale + [(eid, f) for _stream, entries in got for eid, f in entries]

    def ack(self, entry_id: str, client=None):
        return _r(client).xack(self.stream, self.group, entry_id)

    def _reclaim(self, r, count) -> list[tuple[str, dict]]:
        """XAUTOCLAIM, not XPENDING+XCLAIM: one round trip, and it skips entries whose message is
        gone rather than returning ids that cannot be read."""
        try:
            _cursor, entries, *_ = r.xautoclaim(self.stream, self.group, self.consumer,
                                                min_idle_time=RECLAIM_IDLE_MS, start_id="0-0",
                                                count=count)
        except Exception as e:                      # noqa: BLE001 — an old server, or a blip
            print(f"reclaim skipped for {self.group} ({type(e).__name__}: {e})", flush=True)
            return []
        return [(eid, f) for eid, f in entries if f]


def serve(*, name: str, ready: str, read: Callable[[], Any], handle: Callable[..., Any],
          on_start: Callable[[], Any] | None = None, tick: Callable[[], Any] | None = None,
          backoff_s: float = BACKOFF_S, once: bool = False) -> None:
    """Consume a stream for the life of this process. Returns when a signal asks it to stop.

    Three things every one of these processes needs and only some of them had:

    GUARDED. A Redis read can time out on a busy machine, and each of these is the only thing doing
    its job — the only thing that turns an approved answer into the next run, the only thing that
    tells a human an approval is waiting. A blip costs a log line and a back-off, never the process.

    STOPPABLE. SIGTERM and SIGINT set a flag rather than killing the process where it stands, so a
    container stop lets an in-flight delivery finish instead of losing it.

    HYGIENIC. `on_start` runs the crash-recovery pass before the loop, guarded the same way: a Redis
    blip on STARTUP must not stop a process from ever starting.

    `tick` is anything a caller must do each pass regardless of events (a channel polling its own
    inbound commands). `once` runs a single pass, for tests.
    """
    stop = {"now": False}

    def _request_stop(*_a):
        stop["now"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)
    # ...with the build it is running. Every long-lived consumer prints one line on start and this
    # is it, so `deploy/railway.py substrate versions` can read the COMMIT out of a service that has
    # no HTTP surface at all — which is four of them.
    print(f"{ready}  {config.build_id()}", flush=True)
    if on_start:
        try:
            on_start()
        except Exception as e:                      # noqa: BLE001
            print(f"{name}: crash-hygiene pass failed: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
    while not stop["now"]:
        try:
            for entry in read():
                handle(*entry) if isinstance(entry, tuple) else handle(entry)
            if tick:
                tick()
        except Exception as e:                      # noqa: BLE001 — log, back off, keep serving
            print(f"{name} loop error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            time.sleep(backoff_s)
        if once:
            break
    print(f"{name} stopped", flush=True)


def _r(client=None):
    return client if client is not None else redis_client.client()
