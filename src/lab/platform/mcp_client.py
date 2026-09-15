"""Calling the gateway's MCP surface by tool-name SUFFIX — the ONE resolver, shared by the tiers that need it.

The gateway exposes `<server alias>-<tool>`; a caller is deliberately ALIAS-AGNOSTIC (renaming an alias must
not break a running process), so both preflight and the per-call path resolve by suffix, identically. A
workload reaches this through `lab.workloads.gateway`; a substrate service that must act as a channel (the
continuation runner applying a person's decision to the fabric) reaches it here, with its own credential."""
from __future__ import annotations

import asyncio

from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform import config

__all__ = ["resolve", "call_tools_raw", "call_tools"]


def resolve(exposed: Iterable[str], suffix: str) -> str:
    """The gateway's name for a tool, matched by suffix. Raises naming what is exposed."""
    names = list(exposed)
    match = [n for n in names if n.endswith(suffix)]
    if not match:
        raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
    return match[0]


async def call_tools_raw(headers: Mapping[str, str], mcp_url: str, calls, *, client_class=None,
                         timeout: float | None = None) -> list[Any]:
    """Call gateway-MCP tools by name suffix; returns the RAW fastmcp results (`.content` is where image
    blocks live). `client_class` is the seam a test replaces; a caller module passes its own so the
    established `patch.object(module, "Client", …)` keeps working.

    Every call is bounded by `timeout` (default `config.TOOL_CALL_TIMEOUT_S`): a call the server has
    answered but whose response never reaches the client would otherwise block the run FOREVER —
    not failed, not done, holding the run board open and every deploy behind it. A run that fails
    naming the tool is recoverable; a run that hangs is not even visible."""
    cls = client_class or Client
    limit = config.TOOL_CALL_TIMEOUT_S if timeout is None else timeout
    async with cls(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        names = [t.name for t in await c.list_tools()]
        out = []
        for sfx, args in calls:
            name = resolve(names, sfx)
            try:
                out.append(await asyncio.wait_for(c.call_tool(name, args), limit))
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"tool {name} did not answer within {limit:.0f}s — the call is "
                                   f"hung, not slow; the run fails here rather than never") from exc
        return out


async def call_tools(headers: Mapping[str, str], mcp_url: str, calls, *, client_class=None) -> list[Any]:
    """The `.data`-only convenience wrapper — everything that is not an image."""
    return [r.data for r in await call_tools_raw(headers, mcp_url, calls, client_class=client_class)]
