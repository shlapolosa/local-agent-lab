"""The one gateway-MCP resolver: tools by suffix, raw results, `.data` convenience, an injectable client."""
import asyncio
from types import SimpleNamespace

import pytest

from lab.platform import mcp_client


class FakeClient:
    made = []

    def __init__(self, transport):
        FakeClient.made.append(transport); self.calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def list_tools(self): return [SimpleNamespace(name="semantic_mcp-semantic_catalog_get"), SimpleNamespace(name="x-y")]
    async def call_tool(self, name, args):
        self.calls.append((name, args)); return SimpleNamespace(data={"name": name, **args}, content=[])


# ------------------------------------------------------------------ per-server gateways (production: APIM)
class PerServer:
    """One fake MCP server per URL: `/mcp/<alias>/mcp` exposes that alias's UNprefixed tools."""
    made, calls = [], []
    tools = {"semantic_mcp": ["semantic_catalog_get", "semantic_search"], "collab_mcp": ["collab_watch"]}

    def __init__(self, transport):
        self.url = transport.url
        self.alias = self.url.split("/mcp/")[1].split("/")[0]
        PerServer.made.append(transport)

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

    async def list_tools(self):
        return [SimpleNamespace(name=n, inputSchema={}) for n in PerServer.tools[self.alias]]

    async def call_tool(self, name, args):
        PerServer.calls.append((self.alias, name, args))
        return SimpleNamespace(data={"server": self.alias, "tool": name}, content=[])


def test_a_per_server_gateway_is_presented_as_one_catalogue_under_the_same_names(monkeypatch):
    """APIM exposes each MCP server at its own endpoint and cannot aggregate. The client does: the
    catalogue a workload sees is `<server>-<tool>`, exactly LiteLLM's, so contracts, preflight and
    REQUIRED_TOOLS do not know which gateway they are talking to."""
    monkeypatch.setattr(mcp_client.config, "GATEWAY_MCP_SERVERS", ("semantic_mcp", "collab_mcp"))
    PerServer.made.clear()
    PerServer.calls.clear()
    out = asyncio.run(mcp_client.call_tools({"Authorization": "Bearer t"}, "https://apim/mcp/",
                                            [("semantic_catalog_get", {"iri": "u"}), ("collab_watch", {"r": 1})],
                                            client_class=PerServer))
    assert out == [{"server": "semantic_mcp", "tool": "semantic_catalog_get"},
                   {"server": "collab_mcp", "tool": "collab_watch"}]
    assert PerServer.calls == [("semantic_mcp", "semantic_catalog_get", {"iri": "u"}),
                               ("collab_mcp", "collab_watch", {"r": 1})], "each call reaches ITS server by its own name"
    assert {t.url for t in PerServer.made} == {"https://apim/mcp/semantic_mcp/mcp", "https://apim/mcp/collab_mcp/mcp"}
    assert all(t.headers["Authorization"] == "Bearer t" for t in PerServer.made)


def test_the_aggregate_catalogue_lists_every_server_prefixed(monkeypatch):
    monkeypatch.setattr(mcp_client.config, "GATEWAY_MCP_SERVERS", ("semantic_mcp", "collab_mcp"))

    async def names():
        async with mcp_client.gateway_session("https://apim/mcp/", {}, client_class=PerServer) as s:
            return [t.name for t in await s.list_tools()]
    assert sorted(asyncio.run(names())) == ["collab_mcp-collab_watch", "semantic_mcp-semantic_catalog_get",
                                            "semantic_mcp-semantic_search"]


def test_a_server_the_caller_holds_no_grant_on_is_left_out_as_the_single_gateway_hides_it(monkeypatch, capsys):
    """APIM answers 403 on a server a team has no grant on, where LiteLLM simply did not list it. Leaving
    it out keeps the two catalogues the same; a REQUIRED tool behind it still fails preflight by name."""
    import httpx

    class Refusing(PerServer):
        async def __aenter__(self):
            if self.alias == "collab_mcp":
                req = httpx.Request("POST", self.url)
                raise httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req))
            return self

    monkeypatch.setattr(mcp_client.config, "GATEWAY_MCP_SERVERS", ("semantic_mcp", "collab_mcp"))

    async def names():
        async with mcp_client.gateway_session("https://apim/mcp/", {}, client_class=Refusing) as s:
            return [t.name for t in await s.list_tools()]
    assert sorted(asyncio.run(names())) == ["semantic_mcp-semantic_catalog_get", "semantic_mcp-semantic_search"]
    assert "collab_mcp" in capsys.readouterr().err, "what was left out is said, not silent"


def test_any_other_refusal_at_open_still_fails(monkeypatch):
    import httpx

    class Broken(PerServer):
        async def __aenter__(self):
            req = httpx.Request("POST", self.url)
            raise httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))

    monkeypatch.setattr(mcp_client.config, "GATEWAY_MCP_SERVERS", ("semantic_mcp",))

    async def open_():
        async with mcp_client.gateway_session("https://apim/mcp/", {}, client_class=Broken):
            pass
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(open_())


def test_no_server_list_is_the_single_gateway_as_before(monkeypatch):
    monkeypatch.setattr(mcp_client.config, "GATEWAY_MCP_SERVERS", ())
    FakeClient.made.clear()
    out = asyncio.run(mcp_client.call_tools({}, "http://gw/mcp/", [("semantic_catalog_get", {})], client_class=FakeClient))
    assert out[0]["name"] == "semantic_mcp-semantic_catalog_get" and len(FakeClient.made) == 1


def test_resolve_matches_by_suffix_and_names_what_is_exposed():
    assert mcp_client.resolve(["a-b", "c-d"], "d") == "c-d"
    with pytest.raises(RuntimeError, match=r"tool \*z not exposed by gateway \(\['a-b'\]\)"):
        mcp_client.resolve(["a-b"], "z")


def test_call_tools_resolves_calls_and_unwraps_data_through_the_injected_client():
    out = asyncio.run(mcp_client.call_tools({"Authorization": "Bearer k"}, "http://gw/mcp/",
                                            [("semantic_catalog_get", {"iri": "u"})], client_class=FakeClient))
    assert out == [{"name": "semantic_mcp-semantic_catalog_get", "iri": "u"}]
    assert FakeClient.made[-1].headers["Authorization"] == "Bearer k"
    with pytest.raises(RuntimeError):
        asyncio.run(mcp_client.call_tools({}, "http://gw/mcp/", [("nope", {})], client_class=FakeClient))


def test_a_tool_call_that_never_answers_fails_the_run_naming_the_tool_rather_than_hanging():
    """14 Sep 2026: a screening host sat for an hour inside a store call the server had already
    answered — not failed, not done, holding the run board (and every deploy behind it) open."""
    import asyncio
    from types import SimpleNamespace
    from lab.platform import mcp_client

    class Hung:
        def __init__(self, transport): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def list_tools(self): return [SimpleNamespace(name="semantic_mcp-semantic_store_spec")]
        async def call_tool(self, name, args):
            await asyncio.sleep(3600)

    with pytest.raises(TimeoutError, match="did not answer"):
        asyncio.run(mcp_client.call_tools_raw({}, "http://gw/mcp", [("semantic_store_spec", {})],
                                              client_class=Hung, timeout=0.05))


def test_the_default_bound_sits_above_the_longest_legitimate_synchronous_call():
    """Speech transcription is synchronous and 900 s by design; a floor below it would fail an
    hour-long meeting in the shape of a hang, and a retry would do exactly the same again.

    Read the margin exactly: since 15 Sep 2026 the budget covers the whole EXCHANGE — opening the
    session, listing the tools and the call — so the headroom for an hour-long transcription is the
    difference (100 s of setup), not the whole 1000 s. That is ample for a session open measured in
    seconds, and it is not what the number would promise if this assertion were read as a per-call
    budget. The gateway's own LITELLM_MCP_CLIENT_TIMEOUT (300 s) is smaller than both and binds
    first, so none of this applies until somebody raises it."""
    from lab.platform import config
    from lab.substrate.mcp.speech import http as speech_http
    assert config.TOOL_CALL_TIMEOUT_S > speech_http.TIMEOUT >= 300
    assert config.TOOL_CALL_TIMEOUT_S - speech_http.TIMEOUT >= 60, "setup must fit beside the call"


def test_a_session_that_never_opens_or_never_lists_is_bounded_too():
    """The bound must cover the WHOLE exchange. 15 Sep 2026: a host sat for half an hour with the
    gateway's auth span recorded and no tool span at all — hung on the session it had just opened,
    while a bound that only wrapped `call_tool` watched."""
    import asyncio
    from types import SimpleNamespace
    from lab.platform import mcp_client

    class HangsOnOpen:
        def __init__(self, transport): pass
        async def __aenter__(self):
            await asyncio.sleep(3600)
        async def __aexit__(self, *exc): return False

    class HangsOnList(HangsOnOpen):
        async def __aenter__(self): return self
        async def list_tools(self): await asyncio.sleep(3600)
        async def call_tool(self, name, args): return SimpleNamespace(data={})

    for cls in (HangsOnOpen, HangsOnList):
        with pytest.raises(TimeoutError, match="did not answer"):
            asyncio.run(mcp_client.call_tools_raw({}, "http://gw/mcp", [("x", {})],
                                                  client_class=cls, timeout=0.05))
