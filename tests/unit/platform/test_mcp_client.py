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
    hour-long meeting in the shape of a hang, and a retry would do exactly the same again."""
    from lab.platform import config
    from lab.substrate.mcp.speech import http as speech_http
    assert config.TOOL_CALL_TIMEOUT_S > speech_http.TIMEOUT >= 300


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
