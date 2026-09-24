"""A gateway credential as request headers — the ONE place a key or a token becomes headers.

Two credential shapes reach the gateway: an Entra TOKEN (a JWT) and a durable KEY (a LiteLLM virtual key
in dev, an APIM subscription key in production). The gateways read a key differently — LiteLLM from
`Authorization: Bearer`, refusing `api-key` on /mcp; APIM from `api-key` alone (measured 24 Sep 2026) —
so a key travels in BOTH and one client serves both gateways. A token travels as a Bearer only: APIM
would try an `api-key` holding a token as a subscription key, and refuse the call.
"""
from __future__ import annotations

__all__ = ["headers"]


def _is_token(value: str) -> bool:
    return value.count(".") == 2


def headers(value: str) -> dict[str, str]:
    """The headers that present `value` to the gateway; none for no credential."""
    if not value:
        return {}
    out = {"Authorization": f"Bearer {value}"}
    if not _is_token(value):
        out["api-key"] = value
    return out
