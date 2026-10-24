"""semantic-mcp's vocabulary routes — the store end of `/api/vocabulary/*` (FR-6, user decision 24 Oct
2026).

WHY. The SAF pack is the taxonomy master at go-live and implements the fabric's spec; when the fabric
lands in the work tenant, SAF's flows and Dataverse custom APIs switch to the fabric through a CUSTOM
CONNECTOR, which speaks REST, not MCP. So the STABLE vocabulary verbs — match, propose, alias, master —
are also reachable through `/api`. The front door holds Redis only and forwards these here, where the
fabric store lives; the gateway's role check (Vocabulary.Read / .Propose / .Steward) sits in front.

ONE implementation: each route calls the same domain method its MCP tool calls. The in-flux verbs
(resolve, place, relate) are deliberately absent until they settle.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lab.platform.contracts.fabric import VOCAB_ALIAS_FIELDS, VOCAB_PROPOSE_FIELDS
from lab.substrate.mcpserver import error_response as _error, json_body as _body

__all__ = ["routes"]

PROPOSE_FIELDS = tuple(name for name, _, _ in VOCAB_PROPOSE_FIELDS)
ALIAS_FIELDS = tuple(name for name, _, _ in VOCAB_ALIAS_FIELDS)


async def _fields(request: Request, allowed: tuple[str, ...]) -> dict:
    body = await _body(request)
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise ValueError(f"unknown field(s) {unknown}; this operation takes {list(allowed)}")
    return {k: str(v) if v is not None else "" for k, v in body.items()}


def routes(*, fabric, master) -> list[Route]:
    """`fabric()` returns the domain service; `master(scheme, owner, version)` stages the vocabulary
    master (async) — both injected, the same callables the MCP tools use."""

    async def match(request: Request) -> JSONResponse:
        term = str(request.query_params.get("term") or "").strip()
        if not term:
            return _error(400, "term is required — the word whose meaning is wanted")
        try:
            limit = int(request.query_params.get("limit", 5))
        except ValueError:
            return _error(400, "limit must be a whole number")
        return JSONResponse(fabric().concept_match(term, scheme=request.query_params.get("scheme", ""),
                                                   limit=limit))

    async def propose(request: Request) -> JSONResponse:
        try:
            body = await _fields(request, PROPOSE_FIELDS)
            label = body.pop("label", "")
            return JSONResponse(fabric().vocab_propose(label, **body), status_code=201)
        except ValueError as e:
            return _error(422, str(e))

    async def alias(request: Request) -> JSONResponse:
        try:
            body = await _fields(request, ALIAS_FIELDS)
            cid = body.pop("concept_id", "")
            return JSONResponse(fabric().vocab_amend(cid, **body), status_code=201)
        except (KeyError, TypeError) as e:
            return _error(422, f"missing field: {e}")
        except ValueError as e:
            return _error(422, str(e))

    async def stage(request: Request) -> JSONResponse:
        scheme = str(request.query_params.get("scheme") or "").strip()
        if not scheme:
            return _error(400, "scheme is required")
        try:
            return JSONResponse(await master(scheme, request.query_params.get("owner", "ea@doh"),
                                             request.query_params.get("version", "")))
        except (KeyError, ValueError) as e:
            return _error(422, str(e))

    return [Route("/vocabulary/match", match, methods=["GET"]),
            Route("/vocabulary/proposals", propose, methods=["POST"]),
            Route("/vocabulary/aliases", alias, methods=["POST"]),
            Route("/vocabulary/master", stage, methods=["GET"])]
