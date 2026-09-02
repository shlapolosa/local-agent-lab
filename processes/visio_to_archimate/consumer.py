"""Long-lived host for the Visio->ArchiMate workflow — consumes `workflow:requests`.

The event-driven shape of the two-tier design: the review app's Submit page (or any producer)
publishes one durable request on Redis Streams; this process, in its own consumer group
("wf-visio"), runs `host.run_once` per request and writes progress back (running -> trace id ->
done/approval or failed/error), then acks. Azure analogue: Blob upload -> Event Grid -> a
Container Apps host; here Bucket + Redis Streams + a long-lived Railway service.

  python -m processes.visio_to_archimate.consumer        (./lab.sh consumer locally)

Same OTel service name as the one-shot host (one service per business process); the tracer is
set up ONCE for the life of the process and flushed after each run — never shut down per run.
Concurrency is replicas: one request at a time per consumer; a second replica gets its own
consumer name (WF_CONSUMER). On start, entries this consumer received earlier but never acked
(a crash mid-run) are marked failed and acked, so nothing is silently stuck.
"""
import asyncio
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

from opentelemetry import trace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from shared import workflows  # noqa: E402
from processes.visio_to_archimate.host import SERVICE, _shutdown, run_once, tracer  # noqa: E402

GROUP = "wf-visio"
PROCESS = "visio_to_archimate"
CONSUMER = os.environ.get("WF_CONSUMER", "1")     # stable per replica -> its pending list survives restarts
_stop = False


def _flush():
    tp = trace.get_tracer_provider()
    if hasattr(tp, "force_flush"):
        tp.force_flush()


def handle(entry_id: str, fields: dict) -> None:
    rid = fields.get("request_id", "?")
    if fields.get("process") != PROCESS:          # another workload's request on the shared stream
        workflows.ack(GROUP, entry_id)
        return
    inputs = json.loads(fields["inputs"])
    diagram, reqs = inputs["diagram"], list(inputs.get("requirements") or [])
    print(f"request {rid} running: {diagram} + {len(reqs)} doc(s)", flush=True)
    workflows.mark(rid, "running", consumer=CONSUMER)
    t0 = time.time()
    try:
        out = asyncio.run(run_once(diagram, reqs,
                                   on_trace=lambda t: workflows.mark(rid, "running", trace_id=t)))
        workflows.mark(rid, "done", approval_id=out["request_id"], review_app=out.get("review_app"),
                       xml_ref=out["xml_ref"], summary=out["summary"], trace_id=out["trace_id"])
        print(f"request {rid} done in {time.time() - t0:.0f}s -> approval {out['request_id']}", flush=True)
    except Exception as e:                        # noqa: BLE001 — the request fails, the host keeps serving
        workflows.mark(rid, "failed", error=f"{type(e).__name__}: {str(e)[:400]}")
        print(f"request {rid} failed after {time.time() - t0:.0f}s: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
    finally:
        workflows.ack(GROUP, entry_id)
        _flush()


def main() -> None:
    global _stop
    tracer()                                        # once per process
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: globals().__setitem__("_stop", True))
    # crash hygiene: what this consumer took before but never acked
    for eid, f in workflows.channel_events(GROUP, CONSUMER, pending_only=True, count=50):
        rid = f.get("request_id", "?")
        try:
            if workflows.status(rid).get("status") in ("pending", "running"):
                workflows.mark(rid, "failed", error="consumer restarted mid-run")
        except KeyError:
            pass
        workflows.ack(GROUP, eid)
        print(f"request {rid} marked failed (stale from a previous run)", flush=True)
    print(f"consumer ready  service={SERVICE} group={GROUP} consumer={CONSUMER}", flush=True)
    # BLOCK must be shorter than the Redis client's socket_timeout (5 s in shared/approvals.py):
    # with BLOCK 5000 the server's "nothing yet" reply arrived just after the client gave up on
    # Railway's private network, so every idle poll raised TimeoutError (delivery still worked,
    # but the log filled and each miss cost a 5 s back-off). 3 s leaves the RTT headroom.
    while not _stop:
        try:
            for eid, f in workflows.channel_events(GROUP, CONSUMER, block_ms=3000, count=1):
                handle(eid, f)
        except Exception as e:                    # noqa: BLE001 — Redis hiccup: log, back off, keep serving
            print(f"consumer loop error: {type(e).__name__}: {e}", flush=True)
            time.sleep(5)
    _shutdown()
    print("consumer stopped", flush=True)


if __name__ == "__main__":
    main()
