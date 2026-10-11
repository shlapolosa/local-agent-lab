"""The fabric app's web surface: four static pages and the drawing itself.

A SUBSTRATE service, like the review app. It holds no bot — the Copilot Studio agent is this app's bot
and already has the tools — so everything here is about one thing a conversation cannot be: a picture.

THE DRAWING IS FETCHED, NEVER RENDERED HERE. `semantic_view_corpus` builds it through the gateway,
with whichever adapter `FABRIC_CORPUS_RENDERER` names; this service reads the artifact and serves the
bytes. A tab that drew its own picture would be a second renderer to keep in step with the first, and
the port exists precisely so there is one.
"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from lab.platform import config, mcp_client
from lab.platform.contracts import SemanticTools
from lab.substrate import netbind
from lab.substrate.fabricapp import tab

__all__ = ["web", "main", "SERVICE", "CACHE_S"]

SERVICE = "fabric-app"
#: How long a drawn corpus is served before it is drawn again. The same reasoning as the projector's
#: 300 s debounce: a whole-catalogue redraw is O(the catalogue) — 4.9 s at 61 records, measured — and a
#: tab that redrew on every open would make a channel of five people five redraws. A picture a minute
#: old costs a reader nothing; the records it describes are not changing that fast.
CACHE_S = 60


async def _draw(call) -> bytes:
    """The corpus, as bytes, through the gateway. `call` is the transport (injected by a test)."""
    view = (await call([(SemanticTools.view_corpus, {})]))[0]
    ref = str((view or {}).get("ref") or "")
    if not ref:
        raise RuntimeError("semantic_view_corpus returned no ref")
    return ref


def web(*, call=None, read=None, now=None) -> FastAPI:
    """The app. `call` reaches the gateway, `read` reads an `art://` ref — both injected so the pages
    can be exercised without a gateway or a store."""
    from lab.substrate import artifacts, fabric_gateway

    go = call or fabric_gateway.call
    fetch = read or (lambda ref: artifacts.store().get(ref))
    clock = now or (lambda: asyncio.get_event_loop().time())
    app = FastAPI()
    cached: dict = {}

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/tab/config", response_class=HTMLResponse)
    def config_page() -> str:
        return tab.config_page()

    @app.get("/tab/privacy", response_class=HTMLResponse)
    def privacy() -> str:
        return tab.privacy_page()

    @app.get("/tab/terms", response_class=HTMLResponse)
    def terms() -> str:
        return tab.terms_page()

    @app.get("/tab", response_class=HTMLResponse)
    def shell(request: Request) -> str:
        # The view a person LANDS on, by the role the install declares. A courtesy, never a control —
        # every mode is one click away on the drawing itself, and authority lives in the gateway.
        role = str(request.query_params.get("role") or "").strip().lower()
        return tab.shell_page("/corpus", mode=tab.MODE_FOR.get(role, "about"))

    @app.get("/corpus")
    async def corpus() -> Response:
        drawn = cached.get("bytes")
        if drawn is None or clock() - cached.get("at", 0) > CACHE_S:
            ref = await _draw(go)
            drawn = fetch(ref)
            cached.update(bytes=drawn, at=clock())
        # NO X-Frame-Options: a tab IS an iframe, and the header that protects every other surface in
        # this lab would make this one render as an empty box in the only place it is meant to be seen.
        return Response(content=drawn, media_type="text/html; charset=utf-8")

    return app


def main() -> None:
    port = config.FABRIC_APP_PORT
    netbind.refuse_open(SERVICE)
    print(f"{SERVICE} ready  port={port}", flush=True)
    netbind.run(web(), port, sockets=netbind.dual_stack_sockets(port))


if __name__ == "__main__":
    main()
