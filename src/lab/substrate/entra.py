"""ONE Entra access-token check for the substrate: signature against the tenant's published keys,
audience, issuer and tenant. The gateway's front door and the meeting app's tab both need exactly this,
so it lives once; each caller passes its own tenant and audiences — nothing here reads configuration.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Callable, Iterable

__all__ = ["validate", "tenant_keys"]

_KEYS: dict[str, tuple[float, list]] = {}
_KEYS_TTL_S = 3600


def tenant_keys(tenant: str) -> list:
    """The tenant's signing keys, refreshed hourly (Entra rolls them; a stale set refuses good tokens)."""
    at, keys = _KEYS.get(tenant, (0.0, []))
    if not keys or time.time() - at > _KEYS_TTL_S:
        url = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
        with urllib.request.urlopen(url, timeout=30) as r:
            keys = json.load(r)["keys"]
        _KEYS[tenant] = (time.time(), keys)
    return keys


def validate(token: str, *, tenant: str, audiences: Iterable[str],
             keys: Callable[[], list] | None = None) -> dict:
    """The token's claims, or an exception. v2 (`login.microsoftonline.com/<t>/v2.0`) and v1
    (`sts.windows.net/<t>/`) issuers are both this tenant's, as the gateway has always accepted."""
    from jwt import PyJWK, decode, get_unverified_header
    kid = get_unverified_header(token)["kid"]
    key = next(k for k in (keys or (lambda: tenant_keys(tenant)))() if k["kid"] == kid)
    claims = decode(token, PyJWK(key).key, algorithms=["RS256"], audience=list(audiences),
                    options={"verify_iss": False})
    if claims.get("iss") not in (f"https://login.microsoftonline.com/{tenant}/v2.0",
                                 f"https://sts.windows.net/{tenant}/"):
        raise ValueError(f"untrusted issuer {claims.get('iss')}")
    if claims.get("tid") != tenant:
        raise ValueError("wrong tenant")
    return claims
