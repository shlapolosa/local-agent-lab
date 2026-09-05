"""Long-lived host for `transcript_to_minutes` — its own consumer group on `workflow:requests`.

Normally its requests are published by the continuation runner when an organiser answers a
speaker-mapping approval, not by a person.
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.transcript_to_minutes.host import SERVICE, run_once

PROCESS = "transcript_to_minutes"


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs["transcript"], req.inputs.get("speaker_map") or {},
                          req.inputs.get("owner", ""), on_trace=on_trace)


def _describe(req) -> str:
    """The transcript reference — an id, never a person."""
    return req.inputs["transcript"]


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":
    main()
