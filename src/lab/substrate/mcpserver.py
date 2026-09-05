"""How every lab MCP server is built and served — ONE kit, four servers (adoit-mcp, semantic-mcp,
storage-mcp, workflow-mcp), so the governance-relevant plumbing cannot drift between them:

  * `LabServer` (Facade + Template Method) — composes the server from the substrate container
    (`lab.substrate.container.build(service)`: config, redis, tracer, artifact + upload stores, the
    collaboration provider), owns
    the `FastMCP` instance and wraps every tool in ONE span named after the function (attributes
    `mcp.tool`, `mcp.server`; ERROR status + the exception recorded on failure; the result untouched).
    Tools that add domain attributes use `span()` — the current span — instead of opening their own.
  * streamable HTTP at `/mcp` (what the LiteLLM gateway registers)
  * OpenTelemetryMiddleware — one inbound span per request, joining the caller's trace through
    the `traceparent` header the gateway forwards (`extra_headers` in litellm-config.yaml)
  * BearerAuthMiddleware — the gateway must present MCP_SHARED_SECRET when it is set; `serve()`
    REFUSES to start off-loopback (BIND_HOST != 127.0.0.1) without one — an open MCP server on a
    network is ungoverned, so misconfiguration must fail loudly, not warn
  * uvicorn bound to config.BIND_HOST (127.0.0.1 locally, 0.0.0.0 in containers)

    server = LabServer("adoit-mcp", config.ADOIT_MCP_PORT, instrument_urllib=True)

    @server.tool()                                       # parentheses required (a bare @server.tool
    def archimate_validate(spec=None, spec_ref=None):    # would register the function UNTRACED)
        spec = server.spec(spec, spec_ref=spec_ref)      # spec | spec_ref | spec_path, one impl
        span().set_attributes({"archimate.elements": n})
        server.artifacts().put(...)                      # the store from the container

    if __name__ == "__main__":
        server.serve()

Tests override what the server depends on through the container (`server.container.artifacts
.override(fake)`, `.tracer.override(...)`) — never by patching module globals. Every dependency is
held as the PROVIDER and resolved per use, so an override works on a server that was already built
(all four are built at module import). Image-returning tools
must have NO return annotation (fastmcp derives an outputSchema from it, and image content cannot
satisfy one); the wrapper preserves the original signature, so that rule is unchanged.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any

from fastmcp import FastMCP
from opentelemetry import trace

from lab.platform import config
from lab.substrate import container as _container
from lab.substrate.mcpauth import BearerAuthMiddleware
from lab.substrate.specref import load_spec

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def span():
    """The span of the tool call in progress (the kit opens one per call) — for domain attributes."""
    return trace.get_current_span()


class LabServer:
    """One lab MCP server: container-composed, every tool traced, served through the lab bootstrap."""

    def __init__(self, service: str, port: int, *, container=None, instrument_urllib: bool = False,
                 path: str = "/mcp"):
        self.service, self.port, self.path = service, port, path
        self.container = container or _container.build(service, instrument_urllib=instrument_urllib)
        # every dependency is the PROVIDER, resolved per use — so `.override(fake)` is honoured even
        # after the server is built, and nothing (tracer provider, DB connection) is opened at import
        self.tracer = self.container.tracer
        self.artifacts = self.container.artifacts
        self.uploads = self.container.uploads
        self.collab = self.container.collab      # the collaboration provider (files + meetings)
        self.speech = self.container.speech      # the speech provider (talk -> attributable words)
        self.mcp = FastMCP(service)

    def tool(self, *args, **kwargs):
        """`@server.tool()` = FastMCP's `@mcp.tool()` plus the per-call span (sync or async tool)."""
        if args and callable(args[0]):
            # FastMCP accepts a bare @mcp.tool, which would register the UNWRAPPED function: a
            # working, gateway-visible, span-less tool. Governance must not be opt-out by typo.
            raise TypeError(f"{self.service}: use @server.tool() WITH parentheses — a bare "
                            "@server.tool would register the function untraced")
        register = self.mcp.tool(*args, **kwargs)
        return lambda fn: register(self._traced(fn))

    def spec(self, spec: Any = None, spec_path: str | None = None, spec_ref: str | None = None) -> dict:
        """A model spec however the caller passed it (value | JSON string | art:// ref | local path).
        The artifact store is resolved ONLY for a ref — constructing it connects to Postgres and runs
        the DDL, which a by-value validate must not pay for."""
        return load_spec(spec, spec_path, spec_ref, store=self.artifacts() if spec_ref else None)

    def _traced(self, fn):
        name = fn.__name__
        attributes = {"mcp.tool": name, "mcp.server": self.service}
        # start_as_current_span records the exception and sets StatusCode.ERROR on the way out by default
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def traced(*a, **kw):
                with self.tracer().start_as_current_span(name, attributes=attributes):
                    return await fn(*a, **kw)
        else:
            @functools.wraps(fn)
            def traced(*a, **kw):
                with self.tracer().start_as_current_span(name, attributes=attributes):
                    return fn(*a, **kw)
        return traced

    def serve(self, routes=()) -> None:
        """Serve this server. `routes` adds a second ingress beside /mcp — see `app_for`."""
        serve(self.mcp, self.service, self.port, path=self.path, routes=routes)


def app_for(mcp, *, path: str = "/mcp", routes=()):
    """The ASGI app for a FastMCP server with the lab's middleware chain applied.

    `routes` adds plain HTTP routes BESIDE the MCP path. That is how one service carries two
    ingresses over the same port — MCP for agents, REST for clients that are not agents — while both
    sit behind the same middleware: the same bearer check, the same request spans, the same trace
    context. A second app would have meant a second copy of all three.
    """
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    app = mcp.http_app(path=path)
    for route in routes:
        app.router.routes.append(route)
    app.add_middleware(OpenTelemetryMiddleware)   # inbound request spans + traceparent extraction
    app.add_middleware(BearerAuthMiddleware)      # gateway must present MCP_SHARED_SECRET (if set)
    return app


def serve(mcp, service: str, port: int, *, path: str = "/mcp", log_level: str = "info",
          routes=()) -> None:
    """Run `mcp` as a streamable-HTTP server on config.BIND_HOST:`port``path` (blocking)."""
    import uvicorn
    if config.BIND_HOST not in LOOPBACK and not config.MCP_SHARED_SECRET:
        raise SystemExit(f"{service}: refusing to start — BIND_HOST={config.BIND_HOST} with no "
                         "MCP_SHARED_SECRET would expose an ungoverned MCP server to the network; "
                         "set MCP_SHARED_SECRET or bind to loopback")
    print(f"{service}: serving on http://{config.BIND_HOST}:{port}{path}", flush=True)
    uvicorn.run(app_for(mcp, path=path, routes=routes), host=config.BIND_HOST, port=port,
                log_level=log_level)


__all__ = ["LabServer", "span", "serve", "app_for", "LOOPBACK"]
