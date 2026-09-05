"""Long-lived host for the Visio->ArchiMate workflow — consumes `workflow:requests` in its own group.

Everything generic (the poll loop, crash hygiene, writing every declared output back, acking) lives
in `lab.workloads.consumer`, shared with every other business process. What belongs HERE is only
what this process knows: its identity, how to unpack its own inputs, and which result key carries
its approval.

  python -m lab.workloads.visio_to_archimate.consumer        (./lab.sh consumer locally)

Same OTel service name as the one-shot host — one service name per business process. Concurrency is
replicas: one request at a time per consumer, and a second replica gets its own name (WF_CONSUMER).
"""
from lab.platform.contracts import PROCESSES
from lab.workloads import consumer as base
from lab.workloads.visio_to_archimate.host import SERVICE, _shutdown, run_once

PROCESS = "visio_to_archimate"
SPEC = PROCESSES[PROCESS]        # the ONE source of this process's identity + declared outputs
GROUP = SPEC.group
CONSUMER = base.consumer_name()  # stable per replica -> its pending list survives restarts
_flush = base.flush


async def _run(root, req, on_trace):
    """This process's inputs, by name."""
    return await run_once(root, req.diagram, req.requirements, on_trace=on_trace)


def _outputs(out: dict) -> dict:
    """The two declared outputs whose names differ from the keys the run returns."""
    return {"approval_id": out.get("request_id"), "review_app": out.get("review_app")}


def _describe(req) -> str:
    """What the console line says this run is working on — useless as a process name when several
    requests are in flight and someone is reading logs to find theirs."""
    return f"{req.diagram} + {len(req.requirements)} doc(s)"


def handle(root, entry_id: str, fields: dict) -> None:
    base.handle(root, entry_id, fields, process=PROCESS, run=_run, group=GROUP, outputs=_outputs,
                describe=_describe)


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, outputs=_outputs, describe=_describe,
               shutdown=_shutdown)


if __name__ == "__main__":
    main()
