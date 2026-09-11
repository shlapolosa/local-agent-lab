"""The substrate's fabric identity: one place that knows the credential, refusing plainly when it is unset."""
import asyncio

import pytest

from lab.platform import config
from lab.substrate import fabric_gateway as G


def test_the_credential_is_required_and_read_in_one_place(monkeypatch):
    monkeypatch.setattr(config, "FABRIC_CURATOR_KEY", "")
    with pytest.raises(RuntimeError, match="FABRIC_CURATOR_KEY"):
        G.headers()
    monkeypatch.setattr(config, "FABRIC_CURATOR_KEY", "sk-cur")
    assert G.headers() == {"Authorization": "Bearer sk-cur"}
    assert G.headers("sk-other") == {"Authorization": "Bearer sk-other"}


def test_call_goes_through_the_shared_resolver_with_that_credential(monkeypatch):
    seen = {}

    async def fake(headers, url, calls):
        seen.update(headers=headers, url=url, calls=calls); return ["ok"]
    monkeypatch.setattr(G.mcp_client, "call_tools", fake)
    monkeypatch.setattr(config, "FABRIC_CURATOR_KEY", "sk-cur")
    assert asyncio.run(G.call([("semantic_catalog_get", {"iri": "u"})])) == ["ok"]
    assert seen["headers"] == {"Authorization": "Bearer sk-cur"} and seen["url"] == config.GATEWAY_MCP_URL
