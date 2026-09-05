"""workflow-frontdoor — the governed way IN, for callers outside the lab (port 9400).

TWO INGRESSES, ONE PORT. `lab.platform.workflows.submit` is the port: validate against the process's
own contract, take an idempotency claim, publish one `workflow:requests` event. Everything else is
an adapter over it, and which adapter a caller uses is about what the caller IS, not what it can do:

  /mcp  → AGENTS — THIS MODULE. A Copilot Studio agent triggering a process, a workload asking a
          human a question (a workload may not import the substrate, so it must cross the network,
          and it already speaks MCP for storage, collaboration and speech). Use MCP when the caller
          is a model deciding for itself WHICH tool to call: it gets a typed, described, discoverable
          catalogue and needs no knowledge of URLs.
  /api  → EVERYTHING ELSE — `lab.substrate.mcp.workflow.rest`. A low-code flow, a web or mobile
          client, a script. MCP needs a session handshake and answers in server-sent events, which a
          Power Automate HTTP action cannot reasonably consume — so REST exists for them, over the
          SAME function. Use REST when the caller already knows what it wants to do and just needs to
          say so over plain HTTP.

Any call an agent makes could equally be made over REST and vice versa: they are two spellings of
one capability, which is why they live in one service and change together. What they must never
become is a translation layer — REST calling MCP would be a round trip through the protocol REST
was added to avoid, and would cap the REST surface at whatever MCP happens to expose.

WHY IT LOOKED UNUSED. The process tools had no callers for months, which read like dead code and was
not: this was built for external agents, and those agents have not arrived. The client that did
arrive is a flow watching for a saved meeting recording. That is the whole reason `/api` exists.

The tools themselves are GENERATED from `lab.platform.contracts.PROCESSES` — submit, status and
result, less submit for a continuation-only process — and so are the REST routes (`rest.routes`), so
registering a process gives both surfaces at once and neither can drift.
The same server also carries the APPROVAL gate: a run pauses for a human, so the pause belongs to the
front door that exposes the run.
"""
from __future__ import annotations

import inspect
from typing import Annotated, Any, Callable

from pydantic import Field

from lab.platform import config, workflows
from lab.platform.contracts import (PROCESSES, WORKFLOW_FINISHED, InputKind, ProcessSpec,
                                    WorkflowStatus, WorkflowTools)
from lab.substrate.mcp.workflow import approval_tools
from lab.substrate.mcp.workflow import rest
from lab.substrate.mcpserver import LabServer, span

SERVICE = "workflow-frontdoor"     # the SERVICE says what it is; the gateway ALIAS stays
                                  # `workflow_mcp`, naming its MCP surface, consistent with
                                  # ea_mcp / collab_mcp / speech_mcp — and it is what teams
                                  # are granted, so renaming it would invalidate every grant.

# an input field's kind -> the Python annotation the generated tool declares (and fastmcp turns into
# the JSON schema an agent reads). One table: a new kind is one line here and one in InputField.coerce.
ANNOTATION: dict[InputKind, Any] = {InputKind.REF: str, InputKind.REF_LIST: list[str],
                                    InputKind.HANDLE: str, InputKind.IDENTITY: str,
                                    InputKind.MAPPING: dict[str, dict[str, str]]}


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


def _submit(server: LabServer, spec: ProcessSpec, requester: str, values: dict,
            idempotency_key: str | None = None) -> dict:
    """Enqueue-and-acknowledge. The de-duplication itself is `lab.platform.workflows.submit` (SET NX EX,
    so two concurrent retries cannot both queue a run) — this surface only passes the caller's key
    through and TELLS the caller which of the two answers it got, so a connector can distinguish
    "queued" from "you already asked for this"."""
    inputs = spec.validate(values)          # the ProcessSpec IS the validator (one impl, every surface)
    r = _redis(server)
    rid, duplicate = workflows.submit(spec.name, inputs, (requester or "").strip() or "mcp",
                                      spec=spec, idempotency_key=idempotency_key, client=r)
    # a duplicate answers with the run's CURRENT status — the point of retrying is to learn where it got to
    status = workflows.status(rid, client=r).get("status") if duplicate else WorkflowStatus.PENDING.value
    span().set_attributes({"workflow.process": spec.name, "workflow.request_id": rid,
                           "workflow.status": status or "", "workflow.duplicate": duplicate})
    return {"request_id": rid, "process": spec.name, "status": status, "accepted": True,
            "duplicate": duplicate, "poll_with": spec.tool("status"), "result_with": spec.tool("result"),
            "note": (f"already submitted under idempotency_key {idempotency_key!r} — this is the SAME "
                     f"run, nothing new was queued; poll the status tool"
                     if duplicate else
                     "queued — the run takes several minutes; poll the status tool, do not re-submit")}


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
    params.append(_param("idempotency_key", str | None,
                         "Optional key that makes this call SAFE TO RETRY: submitting again with the "
                         "SAME key returns the SAME request_id (with duplicate: true) instead of "
                         "queueing a second run, for 24 hours. Use a stable id you already have for "
                         "this piece of work (the message, ticket or correlation id that asked for "
                         "it) — never a fresh random value per attempt. Omit it and every call is a "
                         "new run, deliberately: re-submitting the same diagram is a legitimate "
                         "re-run.", None))
    doc = (f"Start a run of {spec.title}. {spec.description}\n\n"
           f"Returns IMMEDIATELY with a request_id; it does NOT wait for the run. Poll "
           f"{spec.tool('status')} with that id and read {spec.tool('result')} once the status is "
           f"'{WorkflowStatus.DONE.value}'. Call this ONCE per piece of work — each call queues "
           f"another run, which costs many minutes of real work and stages another human approval. "
           f"If your channel may retry the call, pass an `idempotency_key` and the retry gets the "
           f"first run back (`duplicate: true`) instead of a second one.\nEvery input is an "
           f"art://<id>/<name> reference to a file already uploaded to the lab's upload store; file "
           f"contents and http(s) URLs are not accepted.")
    return _fn(spec.tool("submit"), doc, params,
               lambda requester="mcp", idempotency_key=None, **values:
                   _submit(server, spec, requester, values, idempotency_key))


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
    """The governed tools of one business process, on `server`.

    THREE tools for a process an outside caller may start; TWO for a CONTINUATION-ONLY one
    (`ProcessSpec.external` false), whose submit tool is not generated at all. Not exposing it is
    stronger than refusing it at call time and cheaper than either: a tool that does not exist cannot
    be granted by mistake, cannot be discovered, and cannot be described to an agent as something it
    might try. Status and result stay, because a caller may legitimately observe a run that its own
    approval started.
    """
    makers = {"submit": submit_tool, "status": status_tool, "result": result_tool}
    for verb in WorkflowTools.verbs_for(spec):          # the catalogue decides; this only obeys
        server.tool()(makers[verb](server, spec))


def build(processes: dict[str, ProcessSpec] | None = None) -> LabServer:
    """The server: one tool triple per registered process, plus the approval gate (a run PAUSES for a
    human, so the same front door answers "what is waiting" and "here is the human's decision" —
    lab.substrate.mcp.workflow.approval_tools). `processes` is injected so a test (or a future
    per-tenant deployment) can drive the process tool list from a different registry."""
    server = LabServer(SERVICE, config.WORKFLOW_MCP_PORT)
    for spec in (PROCESSES if processes is None else processes).values():
        register(server, spec)
    approval_tools.register(server)
    return server


server = build()


if __name__ == "__main__":
    print(f"workflow-mcp: processes = {', '.join(PROCESSES) or 'none'}")
    server.serve(routes=rest.routes(server))
