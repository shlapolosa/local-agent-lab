"""The OpenAI vector-store FAÇADE over the governed corpus — what LiteLLM's `pg_vector` provider
talks to, mounted beside /mcp on reference-mcp.

WHY A SECOND TRANSPORT. The user's rule is that retrieval goes THROUGH the gateway: registered,
ACL'd per team, metered, traced. LiteLLM's vector-store surface gives exactly that — a store is a
grant unit (`object_permission.vector_stores`), a search is a spend-logged call — but its
`pg_vector` provider is an HTTP client expecting a service that speaks the OpenAI vector-store
API, not a Postgres client. So this module speaks it. It is an ADAPTER over the one read path,
`pg_library.search`, not a second implementation: the same pin, the same signature check, the same
refusal on a stale index, the same consumption row.

WHAT MAKES IT GOVERNED RATHER THAN A HOLE. The OpenAI shape has no notion of a run, so the run's
identity travels in `filters` — `pin_id`, `run_id`, `process`, `field` — and a search without them
is 400. That is what keeps a read through this door attributed exactly like one through the MCP
tool (FR-44): the consumption row is written inside the read, or the read does not happen. It is
also why `file_search` tool injection is refused by design: the hook carries no pin and sees only
the last user message.

The store id is the artifact id. A store therefore searches ONE artifact, which is what lets a
team be granted the capability map and nothing else.
"""
from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lab.core.reference.errors import (
    ArtifactUnverified,
    CorpusUnreachable,
    IndexUnavailable,
    NotPinned,
    NotSearchable,
    PinExpired,
    ReferenceError,
    ReferenceUnavailable,
)
from lab.core.reference.derive import split_record_passage
from lab.core.reference.model import RunRef
from lab.substrate.mcpserver import error_response, json_body, span

__all__ = ["RUN_FIELDS", "routes"]

#: The run identity a search MUST carry in `filters`. Absent, the read is unattributable and
#: refused — there is no "report your sources afterwards" for a run to forget.
RUN_FIELDS = ("pin_id", "run_id", "process", "field")

#: A refusal's HTTP status. LiteLLM relays the body, so the sentence reaches the caller either
#: way; the status is for the caller that reads only the code.
_STATUS = {ReferenceUnavailable: 404, NotPinned: 404, PinExpired: 410, IndexUnavailable: 409,
           NotSearchable: 409, ArtifactUnverified: 409, CorpusUnreachable: 503}


def _status(exc: ReferenceError) -> int:
    for kind, status in _STATUS.items():
        if isinstance(exc, kind):
            return status
    return 400


def _hit(p: Any) -> dict:
    """One OpenAI `vector_store.search_result`. `file_id` is the passage, `filename` the
    HUMAN-readable signed master (what a person opens — DR-02 at the point of use), and the
    attributes carry what a caller needs to follow a hit with an exact read."""
    # A record-backed hit names the PATH its passage opens with (the map's disambiguator) and
    # the leaf label, so a caller reads them as attributes rather than re-splitting the text
    # with knowledge of how the index was written.
    path = split_record_passage(p.text)[0] if p.record_id else ""
    return {"file_id": p.passage_id, "filename": p.citation.master_ref, "score": p.score,
            "content": [{"type": "text", "text": p.text}],
            "attributes": {"artifact_id": p.citation.artifact_id, "version": p.citation.version,
                           "signature_id": p.citation.signature_id, "record_id": p.record_id,
                           "key": json.dumps(dict(p.key), sort_keys=True) if p.key else "",
                           "anchor": p.citation.anchor, "path": path,
                           "label": path.rsplit(" > ", 1)[-1] if path else ""}}


def _search_route(server, max_hits: int):
    async def search(request: Request) -> JSONResponse:
        store_id = request.path_params["store_id"]
        try:
            body = await json_body(request)
        except ValueError as exc:
            return error_response(400, str(exc))
        query = body.get("query")
        if isinstance(query, list):
            query = " ".join(str(q) for q in query)
        if not isinstance(query, str) or not query.strip():
            return error_response(400, "`query` must be a non-empty string (or a list of them)")
        filters = body.get("filters") or {}
        if not isinstance(filters, dict):
            return error_response(400, "`filters` must be an object carrying the run identity")
        missing = [f for f in RUN_FIELDS if not str(filters.get(f, "")).strip()]
        if missing:
            return error_response(
                400, f"a search names the run it is for: `filters` must carry {list(RUN_FIELDS)}, "
                     f"missing {missing}. Take a pin with reference_pin and pass its pin_id; a "
                     f"read this corpus cannot attribute to a derived field is refused, not "
                     f"served", missing=missing)
        try:
            k = int(body.get("max_num_results") or 8)
        except (TypeError, ValueError):
            return error_response(400, "`max_num_results` must be an integer")
        k = max(1, min(k, max_hits))

        library = server.reference()
        try:
            run = RunRef(run_id=str(filters["run_id"]), process=str(filters["process"]),
                         field=str(filters["field"]))
            pin = library.pin_by_id(str(filters["pin_id"]))
            out = library.search(pin, question=query, run=run, artifact_ids=[store_id], k=k)
        except ReferenceError as exc:
            return error_response(_status(exc), exc.sentence, artifact=exc.artifact_id)
        span().set_attribute("reference.passages", len(out.passages))   # a COUNT, never the text
        return JSONResponse({"object": "vector_store.search_results.page",
                             "search_query": query,
                             "data": [_hit(p) for p in out.passages]})
    return search


def routes(server, *, max_hits: int) -> list[Route]:
    """The routes `LabServer.serve(routes=)` mounts beside /mcp — behind the same bearer check,
    the same request spans, the same trace context."""
    return [Route("/v1/vector_stores/{store_id}/search", _search_route(server, max_hits),
                  methods=["POST"])]
