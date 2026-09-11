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
