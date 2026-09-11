"""Long-lived host for `artifact_intake` — its own consumer group on `workflow:requests`.

Its requests are published by the fabric's ingress (an ArtifactChanged event), never by a person: the
process is `external=False`, so no submit tool exists for it.
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.artifact_intake.host import SERVICE, run_once

PROCESS = "artifact_intake"


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs["pointer"], req.inputs["event_id"],
                          context=req.inputs.get("context") or "", produced_by=req.inputs.get("produced_by") or "",
                          requester=getattr(req, "requester", "") or "", on_trace=on_trace)


def _describe(req) -> str:
    """The event id and the item — ids, never a person."""
    p = req.inputs.get("pointer") or {}
    return f'{req.inputs.get("event_id", "?")} {p.get("source", "?")}:{p.get("ref") or p.get("handle") or p.get("itemId") or "?"}'


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":
    main()
