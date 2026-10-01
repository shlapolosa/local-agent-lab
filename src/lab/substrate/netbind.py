"""Binding a substrate HTTP service to the network — the part every server shares, kept LIGHT.

It used to live in `lab.substrate.mcpserver`, which imports fastmcp, the DI container, Redis and the
stores. A service that is not an MCP server — the voiceprint model, which ships in its own image with
only the model's own dependencies — needs these few lines and none of that, so they live here and
`mcpserver` imports them. Stdlib, uvicorn and `lab.platform.config` only.
"""
from __future__ import annotations

from lab.platform import config

__all__ = ["LOOPBACK", "dual_stack_sockets", "refuse_open", "run"]

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def refuse_open(service: str) -> None:
    """An open service on a network is ungoverned, so a misconfiguration must fail loudly, not warn."""
    if config.BIND_HOST not in LOOPBACK and not config.MCP_SHARED_SECRET:
        raise SystemExit(f"{service}: refusing to start — BIND_HOST={config.BIND_HOST} with no "
                         "MCP_SHARED_SECRET would expose an ungoverned service to the network; "
                         "set MCP_SHARED_SECRET or bind to loopback")


def dual_stack_sockets(port: int) -> list:
    """One IPv6 socket AND one IPv4 socket on `port`, for a server that must answer BOTH the private
    network and the public edge.

    asyncio (and so uvicorn) sets IPV6_V6ONLY on a `::` listener, so a host of `::` is IPv6-only: the
    gateway reaches an MCP server over Railway's IPv6-only private DNS, but the public edge that a
    provider's change notification arrives through is IPv4 — measured 11 Sep 2026, graph-mcp's public
    domain answered every request with 502 and Graph refused the subscription. Two sockets, one server."""
    import socket
    made = []
    for family, host in ((socket.AF_INET6, "::"), (socket.AF_INET, "0.0.0.0")):
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)     # the IPv4 side is its own socket
        sock.bind((host, port if made == [] else made[0].getsockname()[1]))
        sock.listen(128)
        sock.set_inheritable(True)
        made.append(sock)
    return made


def run(app, port: int, *, sockets=None, log_level: str = "info") -> None:
    """Serve `app` on config.BIND_HOST:`port`, or on pre-bound `sockets` (the dual-stack case)."""
    import uvicorn
    if sockets is None:
        uvicorn.run(app, host=config.BIND_HOST, port=port, log_level=log_level)
        return
    uvicorn.Server(uvicorn.Config(app, host=config.BIND_HOST, port=port, log_level=log_level)).run(sockets=sockets)
