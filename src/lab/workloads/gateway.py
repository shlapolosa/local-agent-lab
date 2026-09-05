"""How a workload talks to the gateway's MCP surface — the ONE implementation, shared by every
business process.

A workload holds no tool credentials and reaches every capability through the gateway, so this is
the only transport it has. It lived inside the first workload until a second one needed it; putting
it here is the DRY rule ("one home per piece of logic", and a helper used by more than one workload
belongs to the tier, not to a process).

Two behaviours are the reason this is shared rather than copied:

  * **Tools are resolved by NAME SUFFIX.** The gateway exposes `<server alias>-<tool>`, and a
    workload is deliberately ALIAS-AGNOSTIC: renaming an alias must not break a running process.
    Both the preflight and the per-call path resolve identically, or preflight would pass on a name
    the call then fails to find.
  * **A version mismatch costs zero tokens.** The tools a run needs are knowable before the first
    node executes. A cloud run once died 320 seconds in, after an agent had already spent its
    budget, because the workload and the gateway were deployed from different commits — so the whole
    list is checked up front and the run is refused with the missing names spelled out.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform.contracts import ArtifactRef

__all__ = ["preflight", "call_tools", "call_tools_raw", "ref_from", "resolve"]


def resolve(exposed: Iterable[str], suffix: str) -> str:
    """The gateway's name for a tool, matched by suffix. Raises naming what is exposed."""
    names = list(exposed)
    match = [n for n in names if n.endswith(suffix)]
    if not match:
        raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
    return match[0]


async def preflight(mcp_url: str, headers: Mapping[str, str], required: Iterable[str]) -> None:
    """Refuse the run if the gateway does not expose every tool this workload needs.

    Resolution is by suffix, identically to `call_tools_raw`, so renaming a gateway alias does not
    fail preflight — what DOES fail it is a renamed or withdrawn TOOL, which is the actual defect
    this catches.
    """
    async with Client(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        exposed = [t.name for t in await c.list_tools()]
    missing = [t for t in required if not any(n.endswith(t) for n in exposed)]
    if missing:
        raise RuntimeError(
            f"gateway does not expose {missing} — this workload and the gateway are running different "
            f"versions, or this identity is not granted those servers. Redeploy both from the same "
            f"image (the deploy CLI's `substrate images` shows what each service runs) or fix "
            f"the team grant. Exposed: {sorted(exposed)}")


async def call_tools_raw(headers: Mapping[str, str], mcp_url: str, calls) -> list[Any]:
    """Call gateway-MCP tools by name suffix; returns the RAW fastmcp results.

    Raw because `.content` is where image blocks live — `.data` is None for an image result, so a
    caller that needs pictures cannot use the convenience wrapper below.
    """
    async with Client(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        names = [t.name for t in await c.list_tools()]
        return [await c.call_tool(resolve(names, sfx), args) for sfx, args in calls]


async def call_tools(headers: Mapping[str, str], mcp_url: str, calls) -> list[Any]:
    """The `.data`-only convenience wrapper — everything that is not an image."""
    return [r.data for r in await call_tools_raw(headers, mcp_url, calls)]


def ref_from(res: Any, key: str = "spec_ref") -> str:
    """The `art://` ref out of an MCP result — a dict, or a JSON string (MCP results can arrive as
    strings) — validated as a well-formed reference, so a malformed one fails HERE rather than three
    tool calls later where the cause is no longer obvious."""
    return str(ArtifactRef.parse((res if isinstance(res, dict) else json.loads(res))[key]))
