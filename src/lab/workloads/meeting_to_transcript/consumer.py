"""Long-lived host for `meeting_to_transcript` — consumes `workflow:requests` in its own group.

Everything generic lives in `lab.workloads.consumer`; what belongs here is only what this process
knows: its identity, and how to unpack its own inputs.

  python -m lab.workloads.meeting_to_transcript.consumer
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.meeting_to_transcript.host import SERVICE, run_once

PROCESS = "meeting_to_transcript"


async def _run(root, req, on_trace):
    """This process's inputs, by name. The generic request object carries `inputs` and nothing
    process-shaped, so a second workload cannot accidentally depend on the first one's fields."""
    return await run_once(root, req.inputs["recording"], req.inputs["owner"], on_trace=on_trace)


def _describe(req) -> str:
    """The recording, by its handle — an id, never a person."""
    return req.inputs["recording"]


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":
    main()
