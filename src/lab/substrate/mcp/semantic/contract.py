"""The semantic tools as a CONTRACT FILE — `contracts/semantic-tools.json`, vendored verbatim by an
external consumer (the SAF pack) and diffed on every re-vendor (user decision 24 Oct 2026, FR-5).

Generated from the server's own tool listing, so it cannot describe a tool the server does not
register; `tests/governance/test_semantic_contract_is_current.py` holds the committed file equal to
it, byte for byte. VERSION is bumped BY HAND when the surface changes — major for a removed or renamed
stable tool or a breaking schema change, minor for an addition — so a consumer pins a version, not a
commit. Deterministic: sorted tools, sorted keys, no process-specific metadata.
"""
from __future__ import annotations

import asyncio
import inspect
import json

from lab.platform.contracts import SemanticTools

__all__ = ["VERSION", "render", "dumps"]

VERSION = "1.1.0"
_GRANTS = ("READ", "PIPELINE", "PROMOTE", "REINDEX", "WALK", "RECLASSIFY", "VIEWS", "WRITE")
_KEPT = ("name", "description", "inputSchema", "outputSchema")


def _listed(mcp) -> list:
    tools = mcp.list_tools()
    tools = asyncio.run(tools) if inspect.isawaitable(tools) else tools
    return list(tools.values()) if isinstance(tools, dict) else list(tools)


def render(mcp) -> dict:
    """The contract document for a FastMCP server's tools."""
    tools = []
    for t in _listed(mcp):
        spec = t.to_mcp_tool().model_dump(exclude_none=True)
        tools.append({k: spec[k] for k in _KEPT if k in spec})
    stability = SemanticTools.stability()
    names = sorted(t["name"] for t in tools)
    return {"server": SemanticTools.SERVER, "contract_version": VERSION,
            "tools": sorted(tools, key=lambda t: t["name"]),
            "grants": {g: sorted(getattr(SemanticTools, g)) for g in _GRANTS},
            "stability": {n: stability.get(n, "internal") for n in names}}


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
