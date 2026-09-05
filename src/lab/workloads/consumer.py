"""The long-lived consumer every business process shares.

The event-driven half of the two-tier design: a producer publishes one durable request on Redis
Streams, and a host in its OWN consumer group runs it and writes progress back (running -> trace id
-> done with the process's declared outputs, or failed with the error), then acks. The Azure
analogue is a Blob upload through Event Grid into a Container Apps host; here it is the upload store
plus Redis Streams plus a long-lived service.

This lived inside the first workload until a second one needed it, and copying it would have been
110 lines duplicated for three changed constants. Everything process-specific is a PARAMETER, so
adding a process stays a one-place change: its `ProcessSpec`, a host that knows how to run it, and
a service that calls `serve`.

Three behaviours are the reason this is worth sharing rather than re-deriving:

  * **Every DECLARED output is written back.** A process's own spec says what a finished run
    publishes, so `<process>_result` can return it. This was a real bug once — a host produced
    artifacts the consumer never recorded, and the tool could not hand them back.
  * **Crash hygiene on start.** Entries this consumer took but never acked (a crash mid-run) are
    marked failed and acked, so a request is never silently stuck pending forever.
  * **A poll shorter than the Redis socket timeout.** With a 5 s block the server's "nothing yet"
    arrived just after the client gave up on a cloud private network: delivery still worked, but
    every idle poll raised and cost a back-off. 3 s leaves the round-trip headroom.
"""
from __future__ import annotations

import asyncio
import signal
import time
import traceback
from typing import Callable

from opentelemetry import trace

from lab.platform import config, container, runlog, workflows
from lab.platform.contracts import PROCESSES, WORKFLOW_OPEN, WorkflowRequest, WorkflowStatus

__all__ = ["consumer_name", "flush", "handle", "serve"]

BLOCK_MS = 3000


def consumer_name() -> str:
    """This replica's name INSIDE its group — stable per replica, so its pending list survives a
    restart. It is not a process selector: two replicas of one process are "1" and "2", and a
    different process's "1" does not collide because the GROUP differs.

    Read through `lab.platform.config`, the ONE env reader, rather than from the environment here:
    a second place reading the same variable is a second place to disagree with it.
    """
    return config.WF_CONSUMER


def flush() -> None:
    tp = trace.get_tracer_provider()
    if hasattr(tp, "force_flush"):
        tp.force_flush()


def handle(root, entry_id: str, fields: dict, *, process: str, run, group: str,
           outputs: Callable | None = None, describe: Callable | None = None) -> None:
    """One request. Never raises: a failed request fails, and the host keeps serving.

    `outputs(out)` lets a process map a result key to a DECLARED output name where the two differ
    (an approval is `request_id` inside a run and `approval_id` on the request hash). `describe(req)`
    is what the console line says a run is working ON — the process name alone is useless when three
    requests are in flight and someone is reading logs to find theirs."""
    r = root.redis()
    if fields.get("process") != process:      # another workload's request on the shared stream
        workflows.ack(group, entry_id, client=r)
        return
    spec = PROCESSES[process]
    req = WorkflowRequest.from_fields(fields)  # the contract: a malformed event fails here, loudly
    rid = req.request_id
    print(f"request {rid} running: {describe(req) if describe else process}", flush=True)
    workflows.mark(rid, WorkflowStatus.RUNNING, consumer=consumer_name(), client=r)
    t0 = time.time()
    try:
        out = asyncio.run(run(root, req, lambda t: workflows.mark(
            rid, WorkflowStatus.RUNNING, trace_id=t, client=r)))
        # Every output the process DECLARES must be written, or `<process>_result` cannot return it.
        done = {"trace_id": out.get("trace_id")}
        done.update(outputs(out) if outputs else {})
        done.update({o: out.get(o) for o in spec.outputs if o in out})
        workflows.mark(rid, WorkflowStatus.DONE, client=r,
                       **{k: v for k, v in done.items() if v is not None})
        print(f"request {rid} done in {time.time() - t0:.0f}s", flush=True)
    except Exception as e:                    # noqa: BLE001 — the request fails, the host serves on
        workflows.mark(rid, WorkflowStatus.FAILED, error=runlog.error_text(e), client=r)
        print(f"request {rid} failed after {time.time() - t0:.0f}s: {type(e).__name__}: {e}",
              flush=True)
        traceback.print_exc()
    finally:
        workflows.ack(group, entry_id, client=r)
        flush()


def serve(*, process: str, service: str, run: Callable, shutdown: Callable | None = None,
          outputs: Callable | None = None, describe: Callable | None = None,
          build=None, once: bool = False) -> None:
    """Run this process's consumer until stopped.

    `run(root, req, on_trace)` is the process's own coroutine — it unpacks its own inputs from
    `req.inputs`, because only it knows their shape. `outputs(out)` renames anything whose declared
    output name differs from the key the run returns. `once=True` serves a single poll, for tests.
    """
    spec = PROCESSES[process]
    group, name = spec.group, consumer_name()
    # THE composition root for every business process: built once, here, per process.
    root = build(service) if build else container.build(service)
    root.tracer()                             # installs the provider (service name) for the process
    r = root.redis()

    stop = {"now": False}

    def _request_stop(*_a):
        """Finish the in-flight request, then leave the poll loop — never killed mid-write."""
        stop["now"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)

    for eid, f in workflows.channel_events(group, name, pending_only=True, count=50, client=r):
        rid = f.get("request_id", "?")
        try:
            if workflows.status(rid, client=r).get("status") in WORKFLOW_OPEN:
                workflows.mark(rid, WorkflowStatus.FAILED, error="consumer restarted mid-run",
                               client=r)
        except KeyError:
            pass
        workflows.ack(group, eid, client=r)
        print(f"request {rid} marked failed (stale from a previous run)", flush=True)

    print(f"consumer ready  service={service} group={group} consumer={name}", flush=True)
    while not stop["now"]:
        try:
            for eid, f in workflows.channel_events(group, name, block_ms=BLOCK_MS, count=1, client=r):
                handle(root, eid, f, process=process, run=run, group=group, outputs=outputs,
                       describe=describe)
        except Exception as e:                # noqa: BLE001 — Redis hiccup: log, back off, serve on
            print(f"consumer loop error: {type(e).__name__}: {e}", flush=True)
            time.sleep(5)
        if once:
            break
    if shutdown:
        shutdown()
    print("consumer stopped", flush=True)
