"""Long-lived host for `artifact_publish` — its own consumer group on `workflow:requests`. Its requests are
published by the continuation runner when an owner approves a record's review; never by a person."""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.artifact_publish.host import SERVICE, run_once

PROCESS = "artifact_publish"


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs["artifact_iri"], req.inputs["approval_id"], on_trace=on_trace)


def _describe(req) -> str:
    return f'{req.inputs.get("artifact_iri", "?")} <- {req.inputs.get("approval_id", "?")}'


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":
    main()
