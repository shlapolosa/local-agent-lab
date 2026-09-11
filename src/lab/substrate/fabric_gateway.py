"""The substrate's fabric identity at the gateway — ONE place that knows the credential, used by every fabric
consumer that must act through the gateway (the curator, the projector, the reconciler).

`FABRIC_CURATOR_KEY` is a virtual key on the `fabric-curator` team: semantic WRITE + READ (the PROMOTE grant no
workload holds) and the collaboration reads plus `put`. It is a CHANNEL identity — what it writes at rung H
is attributed to the person the channel authenticated, never to itself. Unset, every fabric consumer refuses
plainly rather than acting anonymously. The credential enters here and nowhere else, so moving it to a
managed identity or a vault is a one-module change."""
from __future__ import annotations

from lab.platform import config, mcp_client


def headers(key: str | None = None) -> dict[str, str]:
    key = config.FABRIC_CURATOR_KEY if key is None else key
    if not key:
        raise RuntimeError("FABRIC_CURATOR_KEY is not configured — the substrate cannot reach the fabric's tools")
    return {"Authorization": f"Bearer {key}"}


async def call(calls, *, key: str | None = None):
    """Gateway-MCP tools by suffix, as the fabric's substrate identity. `calls` is a list of (suffix, args);
    the answers come back in order. Batch what you can: every call is one session."""
    return await mcp_client.call_tools(headers(key), config.GATEWAY_MCP_URL, calls)


__all__ = ["headers", "call"]
