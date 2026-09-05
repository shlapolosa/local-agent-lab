"""The REST ingress: the same front door, for clients that are not agents.

WHY THIS EXISTS. `workflow-frontdoor` was built as the governed way in for callers OUTSIDE the lab,
and the first ones imagined were agents — a Copilot Studio agent, an orchestrator — so it spoke only
MCP. Those agents have not arrived; what arrived instead is a low-code flow that watches for a saved
meeting recording, and Power Automate cannot speak MCP. Its HTTP action sends JSON and expects JSON,
while MCP demands a session handshake and answers in server-sent events.

So this is a SECOND ADAPTER OVER THE SAME PORT, not a translation layer. Both surfaces call
`ProcessSpec.validate` and then `lab.platform.workflows.submit` — the identical function the review
app calls in-process — so validation, idempotency, the audit trail and the declared outputs cannot
differ between them. A REST call that went out to the gateway to invoke MCP to reach that function
would be a round trip through the protocol we added REST to avoid.

  MCP  (/mcp)  → AGENTS AND WORKLOADS — `lab.substrate.mcp.workflow.server`, the other half of this
                 service: a Copilot Studio agent, a workload asking a human a question. Use it when
                 the caller is a model choosing its own next tool, and wants a described, discoverable
                 catalogue rather than a URL scheme.
  REST (/api)  → EVERYTHING ELSE — THIS MODULE: a low-code flow, a web or mobile client, a script.
                 Use it when the caller already knows what it wants and needs plain request/response
                 HTTP, which is all a Power Automate action or a browser can offer.

Neither is a fallback for the other and neither is primary; a caller picks by what it IS. Both reach
`lab.platform.workflows.submit` directly, so a capability added to one is added to both or to
neither — the surfaces are generated from the same registry precisely so that cannot drift.

ROUTES ARE GENERATED from `PROCESSES`, exactly as the MCP tools are, so registering a process gives
both surfaces at once and neither can drift from the other.

AUTHENTICATION AND AUTHORISATION ARE THE GATEWAY'S, and deliberately not this module's. Every route
is reached through the gateway, where an Entra token is validated (issuer, audience, signature
against the tenant's JWKS), mapped to the caller's virtual key, and — for these paths — checked
against the app role `lab.substrate.apipolicy` requires for the operation. That check has to live
there rather than here: LiteLLM's pass-through sends the backend a STATIC Authorization and drops
incoming headers that collide with it, so (measured) the only headers arriving are accept,
authorization, connection, host and user-agent. The caller's identity does not survive the hop, and
enforcing where the identity already exists beats forwarding it. The service still requires the
gateway's shared secret, like every other substrate server — that answers "did this come through the
governed plane", which is a different question from "who is asking".

WHAT THIS MODULE DOES ENFORCE is the one thing no role check could: `ProcessSpec.external`. A
continuation-only process gets no submit route, for every caller, including the master key.
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lab.platform import workflows
from lab.platform.contracts import (APPROVAL_FINAL, PROCESSES, Decision, ProcessSpec,
                                    speaker_prompts)
from lab.substrate import approvals

__all__ = ["routes", "API_PREFIX"]

API_PREFIX = "/api"


def _error(status: int, message: str, **extra) -> JSONResponse:
    """One error shape. A low-code flow shows the caller whatever it is handed, so the message has
    to be the sentence a person needs — not a code they then have to look up."""
    return JSONResponse({"error": message, **extra}, status_code=status)


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        got = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"the request body is not JSON: {e}") from e
    if not isinstance(got, dict):
        raise ValueError("the request body must be a JSON object")
    return got


def _submit_route(server, spec: ProcessSpec):
    async def submit(request: Request) -> JSONResponse:
        try:
            body = await _body(request)
        except ValueError as e:
            return _error(400, str(e))
        requester = str(body.pop("requester", "") or "").strip()
        idempotency_key = body.pop("idempotency_key", None)
        try:
            # The process's OWN contract validates every surface — one implementation, so a REST
            # caller cannot submit something the MCP tool would have refused.
            inputs = spec.validate(body)
        except ValueError as e:
            return _error(422, str(e), process=spec.name,
                          expected={f.name: f.description for f in spec.inputs})
        rid, duplicate = workflows.submit(spec.name, inputs, requester or "api", spec=spec,
                                          idempotency_key=idempotency_key,
                                          client=server.container.redis())
        status = workflows.status(rid, client=server.container.redis()).get("status")
        return JSONResponse({"request_id": rid, "process": spec.name, "status": status,
                             "accepted": True, "duplicate": duplicate,
                             "poll": f"{API_PREFIX}/processes/{spec.name}/runs/{rid}"}, status_code=202)
    return submit


def _run_route(server, spec: ProcessSpec):
    async def run(request: Request) -> JSONResponse:
        rid = request.path_params["request_id"]
        state = workflows.status(rid, client=server.container.redis())
        if not state:
            return _error(404, f"no such run {rid!r}")
        if state.get("process") != spec.name:
            # An id belonging to another process must say so rather than 404 — the caller has the
            # right id and the wrong path, and those are different problems.
            return _error(409, f"{rid} belongs to {state.get('process')!r}, not {spec.name!r}",
                          process=state.get("process"))
        out = {k: state.get(k) for k in ("request_id", "process", "status", "created_at",
                                         "started_at", "finished_at", "trace_id", "error")
               if state.get(k)}
        out |= {k: state[k] for k in spec.outputs if state.get(k) is not None}
        return JSONResponse(out)
    return run


def _approvals_route(server):
    async def listing(request: Request) -> JSONResponse:
        """Everything still waiting on a person. What a flow polls when it did not raise the
        question itself."""
        items = approvals.pending(client=server.container.redis())
        return JSONResponse({"approvals": [_brief(a) for a in items], "count": len(items)})
    return listing


def _approval_route(server):
    async def one(request: Request) -> JSONResponse:
        """One approval in full, INCLUDING its question as a flat list a card template can loop
        over. Flat on purpose: the intended renderer is a low-code adaptive card, not our own UI."""
        state = approvals.status(request.path_params["approval_id"], client=server.container.redis())
        if not state:
            return _error(404, f'no such approval {request.path_params["approval_id"]!r}')
        payload = state.get("payload") or {}
        out = _brief(state) | {
            "question": payload.get("question") or {},
            "speakers": [p.to_dict() for p in speaker_prompts(payload)],
            "answer_labels": list(payload.get("answer_labels") or []),
            "answer_required": bool(payload.get("answer_labels")),
            "artifacts": {k: v for k, v in payload.items() if isinstance(v, str) and v.startswith("art://")},
        }
        return JSONResponse(out)
    return one


def _decide_route(server):
    async def decide(request: Request) -> JSONResponse:
        """Record a HUMAN'S decision, relayed by a client that authenticated them.

        `actor` is the signed-in person, never the calling system: "who identified these speakers"
        is the whole point of the audit log, and `human_decision` refuses a blank one. The channel is
        recorded as the caller's, so a relay is never logged as a decision taken at the review app.
        """
        aid = request.path_params["approval_id"]
        try:
            body = await _body(request)
        except ValueError as e:
            return _error(400, str(e))
        decision = str(body.get("decision") or "").strip()
        if decision not in {d.value for d in Decision}:
            return _error(422, f"decision must be one of {[d.value for d in Decision]}")
        try:
            fields = approvals.human_decision(
                aid, decision, str(body.get("actor") or ""),
                f'api:{str(body.get("channel") or "").strip() or "rest"}',
                str(body.get("comment") or ""), answer=body.get("answer"),
                client=server.container.redis())
        except KeyError:
            return _error(404, f"no such approval {aid!r}")
        except ValueError as e:
            # a blank actor, an incomplete answer, or an already-decided request — each is a
            # sentence the caller can show a person, not a code to look up
            return _error(422, str(e))
        return JSONResponse({"request_id": aid, "decision": fields["decision"],
                             "actor": fields["actor"], "decided_at": fields["decided_at"],
                             "final": decision in {d.value for d in APPROVAL_FINAL}})
    return decide


def _brief(state) -> dict:
    return {k: state.get(k) for k in ("request_id", "kind", "subject", "requester", "status",
                                      "created_at", "trace_id") if state.get(k)}


def routes(server) -> list[Route]:
    """One submit and one run-status route per registered process, plus a listing.

    Generated from `PROCESSES`, so adding a process adds both surfaces at once — the same reason the
    MCP tools are generated rather than written out.
    """
    out: list[Route] = [
        Route(f"{API_PREFIX}/processes", _index, methods=["GET"]),
        # The human-in-the-loop gate, for a client that authenticated its own person.
        Route(f"{API_PREFIX}/approvals", _approvals_route(server), methods=["GET"]),
        Route(f"{API_PREFIX}/approvals/{{approval_id}}", _approval_route(server), methods=["GET"]),
        Route(f"{API_PREFIX}/approvals/{{approval_id}}/decide", _decide_route(server),
              methods=["POST"]),
    ]
    for spec in PROCESSES.values():
        # A continuation-only process gets NO submit route — the same refusal the MCP surface makes by
        # not generating its submit tool, for the same reason: `transcript_to_minutes` takes a human's
        # speaker mapping as input, so a caller able to start it directly would supply its own
        # attribution and walk past the one gate the meeting pipeline has. The run-status route stays:
        # a caller may observe a run its own approval started.
        if spec.external:
            out.append(Route(f"{API_PREFIX}/processes/{spec.name}/runs",
                             _submit_route(server, spec), methods=["POST"]))
        out.append(Route(f"{API_PREFIX}/processes/{spec.name}/runs/{{request_id}}",
                         _run_route(server, spec), methods=["GET"]))
    return out


async def _index(request: Request) -> JSONResponse:
    """What this door will start, and what each one needs — so a flow author can read it rather than
    guess, and so a wrong body comes back with the field descriptions attached."""
    return JSONResponse({"processes": [{
        "name": spec.name, "title": spec.title, "description": spec.description,
        # None, not a path, for a continuation-only process: the catalogue is what a flow author
        # reads to decide what to call, so advertising a submit URL that answers 404 would send
        # them to write the one integration this door refuses.
        "submit": f"{API_PREFIX}/processes/{spec.name}/runs" if spec.external else None,
        "startable": spec.external,
        "inputs": [{"name": f.name, "kind": f.kind.value, "required": f.required,
                    "description": f.description} for f in spec.inputs],
        "outputs": list(spec.outputs),
    } for spec in PROCESSES.values()]})
