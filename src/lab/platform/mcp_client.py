"""Calling the gateway's MCP surface by tool-name SUFFIX — the ONE resolver, shared by the tiers that need it.

The gateway exposes `<server alias>-<tool>`; a caller is deliberately ALIAS-AGNOSTIC (renaming an alias must
not break a running process), so both preflight and the per-call path resolve by suffix, identically. A
workload reaches this through `lab.workloads.gateway`; a substrate service that must act as a channel (the
continuation runner applying a person's decision to the fabric) reaches it here, with its own credential."""
from __future__ import annotations

import asyncio
import copy
import sys
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform import config

__all__ = ["resolve", "call_tools_raw", "call_tools", "gateway_session"]

#: Between a server's alias and its tool name, as LiteLLM names them (`collab_mcp-collab_watch`).
SEP = "-"


def _renamed(tool, name):
    """`tool` under another name, every other attribute (its inputSchema) kept."""
    if hasattr(tool, "model_copy"):
        return tool.model_copy(update={"name": name})
    other = copy.copy(tool)
    other.name = name
    return other


class _Aggregate:
    """Several per-server MCP sessions presented as ONE catalogue under `<server>-<tool>` names — what
    LiteLLM's single /mcp does, done by the client because APIM exposes each server on its own."""

    def __init__(self, sessions):
        self._sessions = sessions                                  # {alias: open session}

    async def list_tools(self):
        return [_renamed(t, f"{alias}{SEP}{t.name}") for alias, s in self._sessions.items()
                for t in await s.list_tools()]

    async def call_tool(self, name, args):
        alias, _, tool = name.partition(SEP)
        if alias not in self._sessions:
            raise RuntimeError(f"no MCP server {alias!r} behind the gateway ({sorted(self._sessions)})")
        return await self._sessions[alias].call_tool(tool, args)


@asynccontextmanager
async def gateway_session(mcp_url: str, headers: Mapping[str, str], *, client_class=None):
    """The gateway's MCP surface as one session: the aggregated endpoint as it is (dev), or one session
    per `config.GATEWAY_MCP_SERVERS` entry at `<mcp_url><server>/mcp` presented as one (production)."""
    cls = client_class or Client
    hdrs = dict(headers or {})
    if not config.GATEWAY_MCP_SERVERS:
        async with cls(StreamableHttpTransport(mcp_url, headers=hdrs)) as c:
            yield c
        return
    async with AsyncExitStack() as stack:
        base = mcp_url.rstrip("/")
        sessions, refused = {}, []
        for alias in config.GATEWAY_MCP_SERVERS:
            try:
                sessions[alias] = await stack.enter_async_context(
                    cls(StreamableHttpTransport(f"{base}/{alias}/mcp", headers=hdrs)))
            except httpx.HTTPStatusError as exc:
                # 403 = this caller holds no grant on that server. The single gateway did not list such a
                # server at all, so leaving it out keeps the catalogue the same; a REQUIRED tool behind
                # it still fails preflight by name. Anything else (401, 5xx) is a fault and raises.
                if exc.response.status_code != 403:
                    raise
                refused.append(alias)
        if refused:
            print(f"mcp: no grant on {', '.join(refused)} — left out of the catalogue", file=sys.stderr)
        yield _Aggregate(sessions)


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

    The WHOLE exchange is bounded by `timeout` (default `config.TOOL_CALL_TIMEOUT_S`) — opening the
    session, listing the tools and every call — because a run hangs wherever the gateway stops
    answering, not only on the call itself. Bounding the call alone was measured to be not enough:
    15 Sep 2026 a screening host sat for half an hour with the gateway's auth span recorded and no
    tool span at all, hung on the session it had just opened, while a 1000 s bound on `call_tool`
    watched. Not failed, not done, the run board open and every deploy behind it. A run that fails
    naming where it stopped is recoverable; a run that hangs is not even visible."""
    cls = client_class or Client
    limit = config.TOOL_CALL_TIMEOUT_S if timeout is None else timeout
    wanted = [sfx for sfx, _args in calls]

    async def exchange():
        async with gateway_session(mcp_url, headers, client_class=cls) as c:
            names = [t.name for t in await c.list_tools()]
            return [await c.call_tool(resolve(names, sfx), args) for sfx, args in calls]

    try:
        return await asyncio.wait_for(exchange(), limit)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"the gateway did not answer {wanted} within {limit:.0f}s — opening the "
                           f"session, listing the tools or the call itself is hung, not slow; the "
                           f"run fails here rather than never") from exc


async def call_tools(headers: Mapping[str, str], mcp_url: str, calls, *, client_class=None) -> list[Any]:
    """The `.data`-only convenience wrapper — everything that is not an image."""
    return [r.data for r in await call_tools_raw(headers, mcp_url, calls, client_class=client_class)]
