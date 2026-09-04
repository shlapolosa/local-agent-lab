"""The ONE Redis client seam for every lab process (approvals, workflow requests, locks, the staged
registry, the run log, the gateway's JIT-key cache).

Why one place: each host must hold ONE small connection pool per Redis URL, not one per module —
a capped Redis (Redis Cloud's 30-client free tier was blown by LiteLLM alone) punishes every
`redis.Redis(...)` that a module creates for itself. `client()` returns the cached pooled client
for a URL (default `config.REDIS_URL`), so N modules in one process share one pool.

    from lab.platform.redis_client import client
    r = client()                       # config.REDIS_URL, 4 connections, decode_responses=True
    r = client("redis://other:6379/1") # a second URL gets its own cached pool

Constructing a client never connects; the first command does. Callers keep their own failure
policy (locks raise LockUnavailable, staged_registry's reads degrade, runlog goes print-only).
`client=` injection parameters on the modules that offer them bypass this cache (tests).
"""
from __future__ import annotations

import threading

import redis

from lab.platform import config

DEFAULT_MAX_CONNECTIONS = 4
SOCKET_TIMEOUT_S = 5

_CLIENTS: dict[str, redis.Redis] = {}
_LOCK = threading.Lock()


def client(url: str | None = None, *, max_connections: int = DEFAULT_MAX_CONNECTIONS) -> redis.Redis:
    """The process-wide pooled client for `url` (default config.REDIS_URL) — created once, cached."""
    url = url or config.REDIS_URL
    r = _CLIENTS.get(url)
    if r is None:
        with _LOCK:
            r = _CLIENTS.get(url)
            if r is None:
                r = redis.Redis.from_url(url, decode_responses=True, max_connections=max_connections,
                                         socket_timeout=SOCKET_TIMEOUT_S)
                _CLIENTS[url] = r
    return r


def reset() -> None:
    """Drop the cache (tests / after a config change). Existing clients are closed best-effort."""
    with _LOCK:
        for r in _CLIENTS.values():
            try:
                r.close()
            except Exception:            # noqa: BLE001 — closing is best-effort
                pass
        _CLIENTS.clear()


__all__ = ["client", "reset", "DEFAULT_MAX_CONNECTIONS", "SOCKET_TIMEOUT_S"]
