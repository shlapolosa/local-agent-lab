"""Governance: the tool catalogue in `lab.platform.contracts` IS what each substrate MCP server registers —
both directions, per server — so a workload built against the contract can never name a tool the gateway
does not expose, and a server cannot grow a tool the contract (and the governance registry) does not know.
Offline: the server modules are imported with the environment pinned (a temp file:// store, no OTLP,
an empty reference-models dir), and the FastMCP instance is found generically (a module attribute, or
`<attr>.mcp` on a server kit) so the test survives the servers being rebuilt on a shared kit.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/governance/test_contracts_match_servers.py"""
import asyncio
import importlib
import inspect
import os
import tempfile

import pytest
import yaml
from fastmcp import FastMCP

from lab.platform import config, contracts

LITELLM_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "config", "litellm-config.yaml")

SERVER_MODULES = {                       # gateway alias -> the server module that registers the tools
    "storage_mcp": "lab.substrate.mcp.storage.server",
    "semantic_mcp": "lab.substrate.mcp.semantic.server",
    "adoit_mcp": "lab.substrate.mcp.adoit.server",
}


@pytest.fixture(scope="module")
def pinned_env():
    """Import-time pins the servers need: a throwaway store, no tracing, no licensed workbooks."""
    tmp = tempfile.mkdtemp(prefix="contracts-parity-")
    os.makedirs(os.path.join(tmp, "no-ref-models"))
    saved = {k: os.environ.get(k) for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "MCP_SHARED_SECRET")}
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None); os.environ["MCP_SHARED_SECRET"] = "shh"
    saved_cfg = {k: getattr(config, k) for k in ("ARTIFACTS_URL", "UPLOADS_URL", "REFERENCE_MODELS_DIR")}
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    config.REFERENCE_MODELS_DIR = os.path.join(tmp, "no-ref-models")
    yield
    for k, v in saved_cfg.items():
        setattr(config, k, v)
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _fastmcp_of(module) -> FastMCP:
    """The server's FastMCP: a module attribute, or `.mcp` on a module attribute (a server kit object)."""
    for _, v in vars(module).items():
        if isinstance(v, FastMCP):
            return v
    for _, v in vars(module).items():
        inner = getattr(v, "mcp", None)
        if isinstance(inner, FastMCP):
            return inner
    raise AssertionError(f"no FastMCP instance found in {module.__name__}")


def registered_tools(module) -> frozenset[str]:
    tools = _fastmcp_of(module).list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    return frozenset(t.name for t in (tools.values() if isinstance(tools, dict) else tools))


@pytest.mark.parametrize("alias", sorted(SERVER_MODULES))
def test_contract_catalogue_equals_the_servers_registered_tools(alias, pinned_env):
    module = importlib.import_module(SERVER_MODULES[alias])
    registered, contract = registered_tools(module), contracts.SERVERS[alias].names()
    assert registered - contract == set(), f"{alias}: server tools missing from the contract"
    assert contract - registered == set(), f"{alias}: contract names no server tool"


def test_every_gateway_server_alias_has_a_contract():
    """The contract's aliases ARE the gateway's `mcp_servers` keys — read from litellm-config.yaml, because
    the alias is what `StorageTools.gateway()` bakes into the agents' `allowed_tools`: rename one in the
    YAML only and an agent silently gets zero tools."""
    registered = set(yaml.safe_load(open(LITELLM_CONFIG, encoding="utf-8"))["mcp_servers"])
    assert registered == set(contracts.SERVERS) == set(SERVER_MODULES)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
