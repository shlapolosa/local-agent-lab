"""Long-lived host for the Visio->ArchiMate workflow — consumes `workflow:requests`.

The event-driven shape of the two-tier design: the review app's Submit page (or any producer)
publishes one durable request on Redis Streams; this process, in its own consumer group
("wf-visio"), runs `host.run_once` per request and writes progress back (running -> trace id ->
done/approval or failed/error), then acks. Azure analogue: Blob upload -> Event Grid -> a
Container Apps host; here Bucket + Redis Streams + a long-lived Railway service.

  python -m lab.workloads.visio_to_archimate.consumer        (./lab.sh consumer locally)

Same OTel service name as the one-shot host (one service per business process). `main()` is the
composition root: it builds the process container ONCE (`lab.platform.container.build(SERVICE)`) —
the tracer is installed for the life of the process and flushed after each run, never shut down per
run; the request stream and the run-log use the container's one Redis client. Concurrency is
replicas: one request at a time per consumer; a second replica gets its own consumer name
(WF_CONSUMER). On start, entries this consumer received earlier but never acked (a crash mid-run)
are marked failed and acked, so nothing is silently stuck.
"""
import asyncio
import os
import signal
import time
import traceback

from opentelemetry import trace

from lab.platform import container, runlog, workflows
from lab.platform.contracts import PROCESSES, WORKFLOW_OPEN, WorkflowRequest, WorkflowStatus
from lab.workloads.visio_to_archimate.host import SERVICE, _shutdown, run_once

PROCESS = "visio_to_archimate"
SPEC = PROCESSES[PROCESS]        # the ONE source of this process's identity + declared outputs
GROUP = SPEC.group
CONSUMER = os.environ.get("WF_CONSUMER", "1")     # stable per replica -> its pending list survives restarts
_stop = False


def _flush():
    tp = trace.get_tracer_provider()
    if hasattr(tp, "force_flush"):
        tp.force_flush()


def handle(root, entry_id: str, fields: dict) -> None:
    r = root.redis()
    if fields.get("process") != PROCESS:          # another workload's request on the shared stream
        workflows.ack(GROUP, entry_id, client=r)
        return
    req = WorkflowRequest.from_fields(fields)      # the contract: a malformed event fails here, loudly
    rid, diagram, reqs = req.request_id, req.diagram, req.requirements
    print(f"request {rid} running: {diagram} + {len(reqs)} doc(s)", flush=True)
    workflows.mark(rid, WorkflowStatus.RUNNING, consumer=CONSUMER, client=r)
    t0 = time.time()
    try:
        out = asyncio.run(run_once(root, diagram, reqs,
                                   on_trace=lambda t: workflows.mark(rid, WorkflowStatus.RUNNING, trace_id=t, client=r)))
        # every output the process DECLARES must be written, or `<process>_result` cannot return it
        # (the repository's import artifacts were missing here while host.py wrote them).
        done = {"approval_id": out.get("request_id"), "review_app": out.get("review_app"),
                "trace_id": out.get("trace_id")}
        done.update({o: out.get(o) for o in SPEC.outputs if o in out})
        workflows.mark(rid, WorkflowStatus.DONE, client=r, **{k: v for k, v in done.items() if v is not None})
        print(f"request {rid} done in {time.time() - t0:.0f}s -> approval {out['request_id']}", flush=True)
    except Exception as e:                        # noqa: BLE001 — the request fails, the host keeps serving
        workflows.mark(rid, WorkflowStatus.FAILED, error=runlog.error_text(e), client=r)
        print(f"request {rid} failed after {time.time() - t0:.0f}s: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
    finally:
        workflows.ack(GROUP, entry_id, client=r)
        _flush()


def _request_stop(*_) -> None:
    """Signal handler: finish the in-flight request, then leave the poll loop."""
    global _stop
    _stop = True


def main() -> None:
    root = container.build(SERVICE)                 # the composition root: once per process
    root.tracer()                                   # installs the provider (service name) for the process
    r = root.redis()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)
    # crash hygiene: what this consumer took before but never acked
    for eid, f in workflows.channel_events(GROUP, CONSUMER, pending_only=True, count=50, client=r):
        rid = f.get("request_id", "?")
        try:
            if workflows.status(rid, client=r).get("status") in WORKFLOW_OPEN:
                workflows.mark(rid, WorkflowStatus.FAILED, error="consumer restarted mid-run", client=r)
        except KeyError:
            pass
        workflows.ack(GROUP, eid, client=r)
        print(f"request {rid} marked failed (stale from a previous run)", flush=True)
    print(f"consumer ready  service={SERVICE} group={GROUP} consumer={CONSUMER}", flush=True)
    # BLOCK must be shorter than the Redis client's socket_timeout (5 s, lab.platform.redis_client):
    # with BLOCK 5000 the server's "nothing yet" reply arrived just after the client gave up on
    # the cloud host's private network, so every idle poll raised TimeoutError (delivery still worked,
    # but the log filled and each miss cost a 5 s back-off). 3 s leaves the RTT headroom.
    while not _stop:
        try:
            for eid, f in workflows.channel_events(GROUP, CONSUMER, block_ms=3000, count=1, client=r):
                handle(root, eid, f)
        except Exception as e:                    # noqa: BLE001 — Redis hiccup: log, back off, keep serving
            print(f"consumer loop error: {type(e).__name__}: {e}", flush=True)
            time.sleep(5)
    _shutdown()
    print("consumer stopped", flush=True)


if __name__ == "__main__":
    main()
