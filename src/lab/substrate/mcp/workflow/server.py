"""workflow-mcp — the ONE governed, discoverable front door to every business process (port 9400, /mcp).

Why a server, and why in the substrate: a workload is a deterministic Agent Framework workflow that
CONTAINS agents; containment is an implementation detail, not an interface
(docs/decisions/2026-09-04-workload-external-contract.md). Exposing it as an MCP server keeps the
TYPED task contract (submit / status / result), and the gateway's MCP registry already IS governed
discovery: registered in config/litellm-config.yaml, granted per team via
`object_permission.mcp_servers`, tool list filtered by grant, every call metered, PII-scanned and
traced. So workloads stay pure MCP CLIENTS and never face outward — every MCP server lives here.

ASYNC IS MANDATORY. A run takes 600-1000 s (measured); no connector, gateway or mobile client holds
a request that long. `<process>_submit` publishes ONE durable `workflow:requests` event
(lab.platform.workflows, Redis Streams — the same event the review app's Submit page emits) and
returns a `request_id` immediately; the long-lived workload host consumes it and writes progress
back, which `<process>_status` / `<process>_result` read. A tool call NEVER blocks on a run.

The tools are GENERATED from `lab.platform.contracts.PROCESSES` — three per process:

    <process>_submit(<input fields…>, requester)  -> {request_id, status: pending, poll_with, …}
    <process>_status(request_id)                  -> {status, trace_id, approval_id, error, …}
    <process>_result(request_id)                  -> the finished outputs, or finished: false

Adding a business process is therefore ONE `ProcessSpec` entry in `lab.platform.contracts.PROCESSES`
(plus its consumer group in `lab.platform.workflows.GROUPS`) — no change in this file. Input
validation is the ProcessSpec's own (`spec.validate`) — the validator this surface uses; moving the
review app's Submit page and the `workflows.py` CLI onto it is the next step (they publish unvalidated
today), after which every producer accepts exactly the same payloads.

CREDENTIALS: this role holds REDIS ONLY — no artifact/upload store, no bucket, no ADOIT. Inputs are
`art://` references that were uploaded through the substrate's own writer (the review app) and are
read by the workload through storage-mcp; nothing here touches an object store.
"""
from __future__ import annotations

import inspect
from typing import Annotated, Any, Callable

from pydantic import Field

from lab.platform import config, workflows
from lab.platform.contracts import (PROCESSES, WORKFLOW_FINISHED, InputKind, ProcessSpec,
                                    WorkflowStatus)
from lab.substrate.mcpserver import LabServer, span

SERVICE = "workflow-mcp"

# an input field's kind -> the Python annotation the generated tool declares (and fastmcp turns into
# the JSON schema an agent reads). One table: a new kind is one line here and one in InputField.coerce.
ANNOTATION: dict[InputKind, Any] = {InputKind.REF: str, InputKind.REF_LIST: list[str]}


def annotation_of(field) -> Any:
    """An OPTIONAL single reference must also accept `null`: LLM clients routinely fill every declared
    parameter, and pydantic would reject `None` against a bare `str` before `coerce` ever sees it."""
    ann = ANNOTATION[field.kind]
    return ann if field.required or field.kind is InputKind.REF_LIST else ann | None


# ----------------------------------------------------------------------------- tool bodies
def _redis(server: LabServer):
    return server.container.redis()


def _state(server: LabServer, spec: ProcessSpec, request_id: str) -> dict:
    """The request hash, or ValueError — including when the id belongs to a DIFFERENT process (an
    agent holding two processes' ids must be told which tool to use, not handed the wrong shape)."""
    st = workflows.status(request_id, client=_redis(server))
    if not st:
        raise ValueError(f"unknown request {request_id!r} — no such {spec.name} run")
    if st.get("process") != spec.name:
        raise ValueError(f"{request_id!r} is a {st.get('process')!r} run, not {spec.name!r}; "
                         f"use that process's own status/result tool")
    span().set_attributes({"workflow.process": spec.name, "workflow.request_id": request_id,
                           "workflow.status": st.get("status", "")})
    return st


def _submit(server: LabServer, spec: ProcessSpec, requester: str, values: dict) -> dict:
    inputs = spec.validate(values)          # the ProcessSpec IS the validator (one impl, every surface)
    rid = workflows.request(spec.name, inputs, (requester or "").strip() or "mcp",
                            spec=spec, client=_redis(server))   # this server's registry, not a global
    span().set_attributes({"workflow.process": spec.name, "workflow.request_id": rid,
                           "workflow.status": WorkflowStatus.PENDING.value})
    return {"request_id": rid, "process": spec.name, "status": WorkflowStatus.PENDING.value,
            "accepted": True, "poll_with": spec.tool("status"), "result_with": spec.tool("result"),
            "note": "queued — the run takes several minutes; poll the status tool, do not re-submit"}


def _status(server: LabServer, spec: ProcessSpec, request_id: str) -> dict:
    st = _state(server, spec, request_id)
    return {**st, "finished": st.get("status") in WORKFLOW_FINISHED}


def _result(server: LabServer, spec: ProcessSpec, request_id: str) -> dict:
    st = _state(server, spec, request_id)
    status = st.get("status")
    head = {"request_id": request_id, "process": spec.name, "status": status}
    if status == WorkflowStatus.FAILED:
        return {**head, "finished": True, "error": st.get("error", "the run failed")}
    if status != WorkflowStatus.DONE:
        return {**head, "finished": False,
                "message": f"not finished yet — {status}; poll {spec.tool('status')} until it is "
                           f"{WorkflowStatus.DONE.value}"}
    outputs = {k: st[k] for k in spec.outputs if st.get(k) not in (None, "")}
    return {**head, "finished": True, **outputs}


# ----------------------------------------------------------------------------- tool generation
def _fn(name: str, doc: str, params: list[inspect.Parameter], body: Callable[..., dict]):
    """A named function with a REAL signature — fastmcp derives the tool's JSON schema from it (and
    LabServer.tool() wraps it in the per-call span). Generated, so a process declares fields, not code."""
    def fn(**kw):
        return body(**kw)
    fn.__name__ = name
    fn.__doc__ = doc
    fn.__signature__ = inspect.Signature(params, return_annotation=dict)
    fn.__annotations__ = {p.name: p.annotation for p in params} | {"return": dict}
    return fn


def _param(name: str, annotation: Any, description: str, default: Any = inspect.Parameter.empty):
    return inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default,
                             annotation=Annotated[annotation, Field(description=description)])


def _request_id_param(spec: ProcessSpec):
    return _param("request_id", str, f"The id {spec.tool('submit')} returned (`wfr-…`).")


def submit_tool(server: LabServer, spec: ProcessSpec):
    params = [_param(f.name, annotation_of(f), f.description,
                     inspect.Parameter.empty if f.required else ([] if f.kind is InputKind.REF_LIST else None))
              for f in spec.inputs]
    params.append(_param("requester", str, "Who is asking (agent name, user principal or channel) — "
                                           "recorded on the request for audit.", "mcp"))
    doc = (f"Start a run of {spec.title}. {spec.description}\n\n"
           f"Returns IMMEDIATELY with a request_id; it does NOT wait for the run. Poll "
           f"{spec.tool('status')} with that id and read {spec.tool('result')} once the status is "
           f"'{WorkflowStatus.DONE.value}'. Call this ONCE per piece of work — each call queues "
           f"another run.\nEvery input is an art://<id>/<name> reference to a file already uploaded "
           f"to the lab's upload store; file contents and http(s) URLs are not accepted.")
    return _fn(spec.tool("submit"), doc, params,
               lambda requester="mcp", **values: _submit(server, spec, requester, values))


def status_tool(server: LabServer, spec: ProcessSpec):
    doc = (f"Progress of one {spec.name} run. `status` is "
           f"{' | '.join(s.value for s in WorkflowStatus)}: pending = queued, no host has taken it "
           f"yet; running = in progress. Also returns created_at/started_at/finished_at, the "
           f"requester, the inputs, the OpenTelemetry trace_id of the run, the approval_id of the "
           f"human approval it raised, and `error` when it failed. Poll this every 30-60 s — a run "
           f"takes minutes. Use {spec.tool('result')} for the outputs.")
    return _fn(spec.tool("status"), doc, [_request_id_param(spec)],
               lambda request_id: _status(server, spec, request_id))


def result_tool(server: LabServer, spec: ProcessSpec):
    doc = (f"The outputs of a FINISHED {spec.name} run: {', '.join(spec.outputs)}. While the run is "
           f"still pending or running this answers `finished: false` with no outputs (poll "
           f"{spec.tool('status')} instead of calling this in a loop); a failed run answers its "
           f"`error`. Artifacts come back as art://<id>/<name> references.")
    return _fn(spec.tool("result"), doc, [_request_id_param(spec)],
               lambda request_id: _result(server, spec, request_id))


def register(server: LabServer, spec: ProcessSpec) -> None:
    """The three governed tools of one business process, on `server`."""
    for make in (submit_tool, status_tool, result_tool):
        server.tool()(make(server, spec))


def build(processes: dict[str, ProcessSpec] | None = None) -> LabServer:
    """The server, with one tool triple per registered process. `processes` is injected so a test (or
    a future per-tenant deployment) can drive the tool list from a different registry."""
    server = LabServer(SERVICE, config.WORKFLOW_MCP_PORT)
    for spec in (PROCESSES if processes is None else processes).values():
        register(server, spec)
    return server


server = build()


if __name__ == "__main__":
    print(f"workflow-mcp: processes = {', '.join(PROCESSES) or 'none'}")
    server.serve()
