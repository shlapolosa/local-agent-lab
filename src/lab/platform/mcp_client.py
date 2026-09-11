"""Calling the gateway's MCP surface by tool-name SUFFIX — the ONE resolver, shared by the tiers that need it.

The gateway exposes `<server alias>-<tool>`; a caller is deliberately ALIAS-AGNOSTIC (renaming an alias must
not break a running process), so both preflight and the per-call path resolve by suffix, identically. A
workload reaches this through `lab.workloads.gateway`; a substrate service that must act as a channel (the
continuation runner applying a person's decision to the fabric) reaches it here, with its own credential."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

__all__ = ["resolve", "call_tools_raw", "call_tools"]


def resolve(exposed: Iterable[str], suffix: str) -> str:
    """The gateway's name for a tool, matched by suffix. Raises naming what is exposed."""
    names = list(exposed)
    match = [n for n in names if n.endswith(suffix)]
    if not match:
        raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
    return match[0]


async def call_tools_raw(headers: Mapping[str, str], mcp_url: str, calls, *, client_class=None) -> list[Any]:
    """Call gateway-MCP tools by name suffix; returns the RAW fastmcp results (`.content` is where image
    blocks live). `client_class` is the seam a test replaces; a caller module passes its own so the
    established `patch.object(module, "Client", …)` keeps working."""
    cls = client_class or Client
    async with cls(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        names = [t.name for t in await c.list_tools()]
        return [await c.call_tool(resolve(names, sfx), args) for sfx, args in calls]


async def call_tools(headers: Mapping[str, str], mcp_url: str, calls, *, client_class=None) -> list[Any]:
    """The `.data`-only convenience wrapper — everything that is not an image."""
    return [r.data for r in await call_tools_raw(headers, mcp_url, calls, client_class=client_class)]
