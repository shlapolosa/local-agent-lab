"""The long-lived `use_case_investment` host: consumes `workflow:requests`, runs, writes back.

Thin by design — the composition root, the crash hygiene and the one way a run is closed live in
`lab.workloads.consumer`. Only this process's input names are here.
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.use_case_investment.host import PROCESS, SERVICE, run_once


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs["design_ref"], req.inputs.get("conformance") or {}, on_trace=on_trace,
                          submitter=req.inputs.get("submitter", ""),
                          conversation=req.inputs.get("conversation", ""))


def _describe(req) -> str:
    """The console line: a reference, never a person."""
    return req.inputs.get("design_ref", "(none)")


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":                                    # pragma: no cover
    main()
