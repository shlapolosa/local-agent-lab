"""A server's tools as a CONTRACT FILE — `contracts/<name>-tools.json`, vendored verbatim by an external
consumer (the SAF pack) and diffed on every re-vendor (FR-5 for semantic-mcp, FR-11 for the EA port).

Generated from the server's own tool listing, so it cannot describe a tool the server does not register;
a governance test per contract holds the committed file equal to it, byte for byte. The VERSION is the
caller's, bumped BY HAND when the surface changes — major for a removed or renamed stable tool or a
breaking schema change, minor for an addition — so a consumer pins a version, not a commit.
Deterministic: sorted tools, sorted keys, no process-specific metadata (fastmcp's `meta` is dropped).
"""
from __future__ import annotations

import asyncio
import inspect
import json

__all__ = ["render", "dumps"]

_KEPT = ("name", "description", "inputSchema", "outputSchema")


def _listed(mcp) -> list:
    tools = mcp.list_tools()
    tools = asyncio.run(tools) if inspect.isawaitable(tools) else tools
    return list(tools.values()) if isinstance(tools, dict) else list(tools)


def render(mcp, catalogue, version: str, grants: tuple[str, ...] = ()) -> dict:
    """The contract document for a FastMCP server: its tools, `catalogue`'s named grant tuples and the
    stability tier of every tool (`ToolCatalogue.stability`)."""
    tools = []
    for t in _listed(mcp):
        spec = t.to_mcp_tool().model_dump(exclude_none=True)
        tools.append({k: spec[k] for k in _KEPT if k in spec})
    stability = catalogue.stability()
    names = sorted(t["name"] for t in tools)
    return {"server": catalogue.SERVER, "contract_version": version,
            "tools": sorted(tools, key=lambda t: t["name"]),
            "grants": {g: sorted(getattr(catalogue, g)) for g in grants},
            "stability": {n: stability.get(n, "internal") for n in names}}


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
