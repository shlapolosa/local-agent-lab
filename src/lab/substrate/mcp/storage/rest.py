"""storage-mcp's byte routes — the store end of `/api/artifacts` and `/api/uploads`.

WHY HERE. A presentation surface (the review app, a Power Apps page, a Teams tab) must read the
artifacts a reviewer judges and upload the inputs a person submits — and must hold no store
credential to do it (TO-BE: presentation is a client of the seam). The front door is where `/api`
lands, but it holds Redis only and never dereferences a ref; this server already holds the store
credentials. So the front door FORWARDS these two operations here over the private network, with the
shared secret, and the gateway's role check in front of the front door still decides who may ask.

The MCP tools on this server stay read-only. The upload route writes, but it is unreachable from a
workload: a workload holds a virtual key, and a virtual key is refused on `/api` at the gateway.
"""
from __future__ import annotations

from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import posixpath

from lab.platform.filetypes import content_type_for
from lab.substrate.artifacts import ArtifactTooLarge, _split, check_name
from lab.substrate.mcpserver import error_response as _error

__all__ = ["routes", "read"]


def _name(ref: str) -> str:
    return ref.rstrip("/").rsplit("/", 1)[-1]


def read(server, ref: str) -> bytes:
    """The bytes behind a ref, from whichever store holds it — a ref does not say which: renders
    live in the artifact store, submitted inputs in the upload store (the same store locally).
    KeyError when neither holds it; anything else a store raises is not a miss and propagates."""
    _split(ref)                                   # a ref is never a path — ValueError before any store
    for store in (server.artifacts, server.uploads):
        try:
            return store().get(ref)
        except (KeyError, FileNotFoundError):
            continue
    raise KeyError(ref)


def _upload_name(raw: str) -> str:
    """A caller's filename as an object NAME: its base name only, and refused when that is nothing."""
    return check_name(posixpath.basename(str(raw or "").replace("\\", "/")))


def routes(server) -> list[Route]:
    async def artifact(request: Request) -> Response:
        ref = str(request.query_params.get("ref") or "")
        try:
            data = read(server, ref)
        except ValueError as e:
            return _error(400, f"ref must be an art://<id>/<name> reference ({e})")
        except KeyError:
            return _error(404, f"no artifact {ref!r}")
        except Exception as e:                            # noqa: BLE001 — a store fault, not a miss
            return _error(502, f"the store could not be read: {type(e).__name__}: {e}")
        name = _name(ref).replace('"', "")
        return Response(data, media_type=content_type_for(name),
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def upload(request: Request) -> JSONResponse:
        form = await request.form()
        files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]
        if not files:
            return _error(400, "send one or more files as multipart field 'files'")
        store = server.uploads()
        refs = []
        try:
            for f in files:
                # The original BASE name is kept: workloads decide how to read an input from its suffix.
                # Streamed, so the store's size ceiling refuses an oversize file before it is held whole.
                name = _upload_name(str(f.filename))
                refs.append(store.put_stream(name, f.file, content_type_for(name), size_hint=f.size))
        except ArtifactTooLarge as e:
            return _error(413, str(e))
        except ValueError as e:
            return _error(400, str(e))
        return JSONResponse({"refs": refs}, status_code=201)

    return [Route("/artifacts", artifact, methods=["GET"]),
            Route("/uploads", upload, methods=["POST"])]
