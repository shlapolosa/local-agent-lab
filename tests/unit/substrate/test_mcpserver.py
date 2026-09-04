"""src/lab/substrate/mcpserver.py — how every lab MCP server is served. OFFLINE: a two-line FastMCP server
behind `app_for()` driven by Starlette's TestClient (401 without the bearer, through with it), and
`serve()` with uvicorn.run monkeypatched — including the REFUSAL to start off-loopback without
MCP_SHARED_SECRET (wave-1 review F5: an open MCP server on a network is ungoverned) — and the
`LabServer` kit: one span per tool call (name = the function, `mcp.tool` / `mcp.server` attributes,
ERROR status + recorded exception on failure, result untouched, sync and async), stores resolved from
the substrate container (overridable), schemas identical to a plain FastMCP registration (an
image-returning tool keeps NO outputSchema), and `serve()` delegating to the module bootstrap."""
import asyncio
import tempfile

import pytest
from fastmcp import Client, FastMCP
from fastmcp.utilities.types import Image
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.testclient import TestClient

from fixtures.fakes import capture
from lab.platform import config
from lab.substrate import artifacts, mcpserver
from lab.substrate.container import build
from lab.substrate.mcpserver import LabServer, span


def _mcp():
    mcp = FastMCP("tiny")

    @mcp.tool
    def ping() -> str:
        return "pong"
    return mcp


def _with(**vals):
    saved = {k: getattr(config, k) for k in vals}
    for k, v in vals.items():
        setattr(config, k, v)
    return saved


def _restore(saved):
    for k, v in saved.items():
        setattr(config, k, v)


def test_app_for_enforces_bearer_when_secret_set():
    saved = _with(MCP_SHARED_SECRET="s3cr3t")
    try:
        app = mcpserver.app_for(_mcp())
        with TestClient(app) as c:
            r = c.get("/mcp")
            assert r.status_code == 401 and r.json() == {"error": "unauthorized"} and r.headers["www-authenticate"] == "Bearer"
            assert c.get("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
            r = c.get("/mcp", headers={"Authorization": "Bearer s3cr3t"})
            assert r.status_code != 401, "the gateway's bearer gets through to the MCP endpoint"
            assert c.get("/other", headers={"Authorization": "Bearer s3cr3t"}).status_code == 404
    finally:
        _restore(saved)


def test_app_for_open_without_secret_and_custom_path():
    saved = _with(MCP_SHARED_SECRET=None)
    try:
        with TestClient(mcpserver.app_for(_mcp(), path="/tools")) as c:
            assert c.get("/tools").status_code != 401
            assert c.get("/mcp").status_code == 404
    finally:
        _restore(saved)


def test_serve_binds_and_refuses_off_loopback_without_secret():
    import uvicorn
    calls = []
    real = uvicorn.run
    uvicorn.run = lambda app, **kw: calls.append((app, kw))
    saved = _with(BIND_HOST="127.0.0.1", MCP_SHARED_SECRET=None)
    try:
        _, out, _ = capture(mcpserver.serve, _mcp(), "tiny-mcp", 9999)
        assert "tiny-mcp: serving on http://127.0.0.1:9999/mcp" in out and "refusing" not in out
        assert calls[-1][1] == {"host": "127.0.0.1", "port": 9999, "log_level": "info"}
        config.BIND_HOST = "0.0.0.0"
        try:
            capture(mcpserver.serve, _mcp(), "tiny-mcp", 9999)
        except SystemExit as e:
            assert "refusing to start" in str(e) and "MCP_SHARED_SECRET" in str(e) and "0.0.0.0" in str(e)
        else:
            raise AssertionError("off-loopback with no secret must refuse")
        assert len(calls) == 1, "uvicorn never started"
        config.MCP_SHARED_SECRET = "s3cr3t"
        _, out, _ = capture(mcpserver.serve, _mcp(), "tiny-mcp", 9300, path="/mcp", log_level="warning")
        assert "http://0.0.0.0:9300/mcp" in out and calls[-1][1] == {"host": "0.0.0.0", "port": 9300, "log_level": "warning"}
        config.BIND_HOST, config.MCP_SHARED_SECRET = "localhost", None
        capture(mcpserver.serve, _mcp(), "tiny-mcp", 1)
        assert calls[-1][1]["host"] == "localhost", "every loopback spelling is allowed without a secret"
        assert len(calls) == 3
    finally:
        uvicorn.run = real
        _restore(saved)


# ---------------------------------------------------------------- the LabServer kit
class FakeStore:
    def __init__(self): self.puts = []
    def put(self, name, data, content_type): self.puts.append(name); return f"art://fake/{name}"


@pytest.fixture
def kit():
    """A LabServer on a container whose tracer records into memory and whose stores are temp LocalStores."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(exporter))
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as u:
        c = build("kit-mcp", artifacts_url=f"file://{a}", uploads_url=f"file://{u}")
        with c.tracer.override(provider.get_tracer("kit-mcp")):
            yield LabServer("kit-mcp", 9999, container=c), exporter


def _call(mcp, tool, **args):
    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(tool, args, raise_on_error=False)
    return asyncio.run(go())


def _tools(mcp):
    async def go():
        async with Client(mcp) as c:
            return {t.name: t for t in await c.list_tools()}
    return asyncio.run(go())


def test_tool_wraps_sync_and_async_in_one_span_each(kit):
    srv, exporter = kit

    @srv.tool()
    def add(a: int, b: int = 1) -> dict:
        """Add."""
        span().set_attribute("kit.sum", a + b)
        return {"sum": a + b}

    @srv.tool()
    async def shout(text: str) -> str:
        """Shout."""
        span().set_attribute("kit.len", len(text))
        return text.upper()

    assert _call(srv.mcp, "add", a=2).data == {"sum": 3}, "result untouched"
    assert _call(srv.mcp, "shout", text="hi").data == "HI"
    by = {s.name: s for s in exporter.get_finished_spans()}
    assert set(by) == {"add", "shout"}, "one span per call, named after the function"
    assert by["add"].attributes["mcp.tool"] == "add" and by["add"].attributes["mcp.server"] == "kit-mcp"
    assert by["add"].attributes["kit.sum"] == 3, "the tool's own attributes land on the kit's span"
    assert by["shout"].attributes["kit.len"] == 2 and by["shout"].attributes["mcp.tool"] == "shout"
    assert all(s.status.status_code is not StatusCode.ERROR for s in by.values())
    tools = _tools(srv.mcp)
    assert tools["add"].description == "Add." and tools["add"].inputSchema["required"] == ["a"]
    assert tools["add"].inputSchema["properties"]["b"]["default"] == 1, "defaults survive the wrapper"


def test_bare_decorator_is_refused_because_it_would_register_an_untraced_tool(kit):
    """`@server.tool` (no parens) makes FastMCP register the RAW function — it works, is visible to
    the gateway and emits NO span. An ungoverned tool must not be reachable by a typo."""
    srv, exporter = kit
    try:
        srv.tool(lambda ref: ref)
    except TypeError as e:
        assert "parentheses" in str(e) and "untraced" in str(e)
    else:
        raise AssertionError("a callable first argument must be refused")
    assert not exporter.get_finished_spans()


def test_tracer_overridden_after_construction_is_honoured(kit):
    """The tracer is a provider like the stores: a server built at module import (all three of them)
    must still be re-pointable at a recording tracer, or its span attributes can never be asserted."""
    srv, _ = kit

    @srv.tool()
    def ping() -> str:
        """Ping."""
        return "pong"

    later = InMemorySpanExporter()
    provider = TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(later))
    with srv.container.tracer.override(provider.get_tracer("later")):
        assert _call(srv.mcp, "ping").data == "pong"
    assert [s.name for s in later.get_finished_spans()] == ["ping"]


def test_tool_span_is_a_child_of_the_inbound_request_span(kit):
    """One trace per run is why the kit exists: the tool span must join the caller's trace across
    FastMCP's sync-tool thread hop (the ASGI middleware opens the inbound span)."""
    srv, exporter = kit

    @srv.tool()
    def ping() -> str:
        """Ping."""
        return "pong"

    with srv.container.tracer().start_as_current_span("inbound") as inbound:
        ctx = inbound.get_span_context()
        _call(srv.mcp, "ping")
    tool_span = next(s for s in exporter.get_finished_spans() if s.name == "ping")
    assert tool_span.parent.span_id == ctx.span_id and tool_span.context.trace_id == ctx.trace_id


def test_spec_resolves_the_store_only_for_a_ref(kit):
    """A by-value spec must not touch the artifact store: resolving it constructs the backend (a
    Postgres connect + CREATE TABLE by default), so a pure validate would pay a DB round-trip."""
    srv, _ = kit

    class Exploding:
        def get(self, ref):
            raise AssertionError("the store must not be touched")

    with srv.container.artifacts.override(Exploding()):
        assert srv.spec({"name": "m"}) == {"name": "m"}
        assert srv.spec('{"name": "m"}') == {"name": "m"}
    ref = srv.artifacts().put("s.json", b'{"name": "from-ref"}', "application/json")
    assert srv.spec(None, None, ref)["name"] == "from-ref"


def test_tool_failure_marks_the_span_error_and_keeps_the_mcp_error(kit):
    srv, exporter = kit

    @srv.tool()
    def boom(ref: str) -> dict:
        """Fail."""
        raise ValueError(f"unknown artifact {ref}")

    r = _call(srv.mcp, "boom", ref="art://x/y")
    assert r.is_error and "unknown artifact art://x/y" in r.content[0].text
    (s,) = exporter.get_finished_spans()
    assert s.name == "boom" and s.status.status_code is StatusCode.ERROR
    assert s.events[0].name == "exception" and "unknown artifact" in s.events[0].attributes["exception.message"]


def test_schemas_match_a_plain_fastmcp_registration(kit):
    """The kit must not change what the gateway sees: identical input/output schemas, and an
    image-returning tool (no return annotation) keeps NO outputSchema (the fastmcp gotcha)."""
    srv, _ = kit
    plain = FastMCP("plain")

    def picture(ref: str, max_edge: int = 1600):
        """Image."""
        return [Image(data=b"\x89PNG", format="png"), f"{ref} 1x1"]

    def info(ref: str) -> dict:
        """Info."""
        return {"ref": ref}

    for fn in (picture, info):
        srv.tool()(fn); plain.tool()(fn)
    kit_tools, plain_tools = _tools(srv.mcp), _tools(plain)
    for name in ("picture", "info"):
        assert kit_tools[name].inputSchema == plain_tools[name].inputSchema, name
        assert kit_tools[name].outputSchema == plain_tools[name].outputSchema, name
    assert kit_tools["picture"].outputSchema is None and kit_tools["info"].outputSchema
    assert _call(srv.mcp, "picture", ref="a").content[0].mimeType == "image/png"


def test_stores_come_from_the_container_and_can_be_overridden(kit):
    srv, _ = kit
    assert srv.container.config.service_name() == "kit-mcp"
    assert srv.artifacts is srv.container.artifacts and srv.uploads is srv.container.uploads, "the providers"
    assert srv.collab is srv.container.collab, "the collaboration provider, held the same way"
    a, u = srv.artifacts(), srv.uploads()
    assert isinstance(a, artifacts.LocalStore) and isinstance(u, artifacts.LocalStore) and a is not u
    assert a is srv.artifacts(), "singleton per container"
    assert a is artifacts.store(srv.container.config.artifacts_url()), "the SAME object as the legacy call"
    fake = FakeStore()
    with srv.container.artifacts.override(fake):
        assert srv.artifacts() is fake
        assert srv.artifacts().put("x", b"", "text/plain") == "art://fake/x"
    assert srv.artifacts() is a


def test_default_container_is_built_for_the_service():
    srv = LabServer("adoit-mcp", 9100, instrument_urllib=True, path="/tools")
    assert srv.container.config.service_name() == "adoit-mcp" and srv.container.config.instrument_urllib() is True
    assert srv.container.config.artifacts_url() == config.ARTIFACTS_URL
    assert srv.tracer is srv.container.tracer and srv.mcp.name == "adoit-mcp"   # the provider
    assert (srv.service, srv.port, srv.path) == ("adoit-mcp", 9100, "/tools")


def test_serve_delegates_to_the_module_bootstrap(monkeypatch):
    calls = []
    monkeypatch.setattr(mcpserver, "serve", lambda mcp, service, port, **kw: calls.append((mcp, service, port, kw)))
    srv = LabServer("tiny-mcp", 9300, path="/tools")
    srv.serve()
    assert calls == [(srv.mcp, "tiny-mcp", 9300, {"path": "/tools"})]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
