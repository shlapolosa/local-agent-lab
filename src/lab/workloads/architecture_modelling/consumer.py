"""The long-lived `architecture_modelling` host: consumes `workflow:requests`, runs, writes back.

Thin by design: the composition root, the crash hygiene and the one way a run is closed live in
`lab.workloads.consumer`. Only this process's input names are here.
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.architecture_modelling.host import PROCESS, SERVICE, run_once


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs["documents"], submitter=req.inputs.get("submitter", ""),
                          on_trace=on_trace)


def _describe(req) -> str:
    """The console line: a count, never a person."""
    return f"{len(req.inputs.get('documents') or ())} document(s)"


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":                                    # pragma: no cover
    main()
