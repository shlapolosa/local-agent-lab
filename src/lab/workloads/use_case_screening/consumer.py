"""The long-lived `use_case_screening` host: consumes `workflow:requests`, runs, writes back.

Thin by design — the composition root, the crash hygiene and the one way a run is closed all live
in `lab.workloads.consumer`. What is here is only what THIS process's inputs are called.
"""
from __future__ import annotations

from lab.workloads import consumer as base
from lab.workloads.use_case_screening.host import PROCESS, SERVICE, run_once


async def _run(root, req, on_trace):
    return await run_once(root, req.inputs.get("submission", ""),
                          req.inputs.get("submitter", ""),
                          handle=req.inputs.get("submission_handle", ""),
                          attachments=req.inputs.get("attachments") or (),
                          intake=req.inputs.get("intake") or {},
                          conversation=req.inputs.get("conversation", ""),
                          on_trace=on_trace)


def _describe(req) -> str:
    """The console line: a reference, never the submitter — logs are read by other people."""
    return req.inputs.get("submission") or req.inputs.get("submission_handle") or "(no document)"


def main() -> None:
    base.serve(process=PROCESS, service=SERVICE, run=_run, describe=_describe)


if __name__ == "__main__":                                    # pragma: no cover
    main()
