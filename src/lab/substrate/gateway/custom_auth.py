"""LiteLLM custom auth: Entra ID JWTs at the gateway (the APIM validate-jwt analogue).

An agent presents `Authorization: Bearer <Entra access token>` obtained with MSAL
client-credentials. This hook validates it (issuer, audience, signature via the tenant's
JWKS) and maps the calling app registration (appid/azp claim) to the agent's LiteLLM
virtual key — so budgets, rate limits, spend and tool ACLs keep enforcing exactly as
before, but the credential is now the IdP's, not a static key.

Static virtual keys (sk-…) and the master key still work: non-JWT tokens fall through to
LiteLLM's normal auth. Mapping lives in ENTRA_CLIENT_TO_KEY (JSON: {client_id: virtual_key});
1:1 key ↔ app registration per the design.
Wire-up: general_settings.custom_auth: lab.substrate.gateway.custom_auth.user_api_key_auth (config/litellm-config.yaml)
"""
import json
import logging
import os
import time
import urllib.request

from fastapi import Request

log = logging.getLogger("lab.custom_auth")

TENANT = os.environ.get("ENTRA_TENANT_ID", "")
AUDIENCE = os.environ.get("ENTRA_GATEWAY_AUDIENCE", "")
ISSUERS = (f"https://login.microsoftonline.com/{TENANT}/v2.0",
           f"https://sts.windows.net/{TENANT}/")           # v1 tokens for api:// audiences
_JWKS = {"keys": None, "at": 0.0}


def _jwks():
    if not _JWKS["keys"] or time.time() - _JWKS["at"] > 3600:
        url = f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"
        _JWKS["keys"] = json.load(urllib.request.urlopen(url, timeout=30))["keys"]
        _JWKS["at"] = time.time()
    return _JWKS["keys"]


def _validate(token: str) -> dict:
    from jwt import PyJWK, decode, get_unverified_header   # PyJWT ships with litellm
    kid = get_unverified_header(token)["kid"]
    key = next(k for k in _jwks() if k["kid"] == kid)
    claims = decode(token, PyJWK(key).key, algorithms=["RS256"],
                    audience=[AUDIENCE, AUDIENCE.replace("api://", "")],
                    options={"verify_iss": False})
    if claims.get("iss") not in ISSUERS:
        raise ValueError(f"untrusted issuer {claims.get('iss')}")
    if claims.get("tid") != TENANT:
        raise ValueError("wrong tenant")
    return claims


async def user_api_key_auth(request: Request, api_key: str):
    """LiteLLM custom-auth contract: return None -> normal key auth on the original
    credential; return a STRING -> normal key auth runs on that key instead (budgets,
    ACLs, spend all enforced by LiteLLM itself). So: Entra JWT -> mapped virtual key
    string; anything else -> None."""
    token = (api_key or "").removeprefix("Bearer ").strip()
    if token.count(".") != 2 or not token.startswith("eyJ"):
        return None                                    # static keys / master key: normal auth
    try:
        claims = _validate(token)
    except Exception as e:                         # noqa: BLE001
        # a JWT, but not one of ours (e.g. the LiteLLM UI's own jwt) -> normal key auth; keep the
        # reason visible so JWKS / clock / audience failures are debuggable instead of silent
        log.debug("entra jwt rejected (%s: %s) — falling through to key auth", type(e).__name__, e)
        return None
    # --- interactive DEVELOPER tokens (delegated scope) -> JIT personal virtual key ---
    if "access_as_user" in (claims.get("scp") or ""):
        return await _developer_key(claims)
    # --- agent (client-credentials) tokens -> static app->key mapping ---
    app_id = claims.get("azp") or claims.get("appid")
    vkey = _client_mapping().get(app_id)
    if not vkey:
        raise ValueError(f"app registration {app_id} has no virtual key mapping (roles={claims.get('roles')})")
    return vkey


_MAPPING = {"raw": None, "parsed": {}}


def _client_mapping() -> dict:
    """ENTRA_CLIENT_TO_KEY ({client_id: virtual_key}) parsed once per distinct value — not per
    request — while still honouring a value that changes in the process env."""
    raw = os.environ.get("ENTRA_CLIENT_TO_KEY", "{}")
    if raw != _MAPPING["raw"]:
        _MAPPING.update(raw=raw, parsed=json.loads(raw))
    return _MAPPING["parsed"]


_REDIS = None


def _redis():
    """The lab's ONE pooled Redis client (lab.platform.redis_client — same URL resolution as every
    other process: REDIS_URL, else REDIS_HOST/PORT). Imported lazily so the hook module loads without
    Redis; one small connection pool, never a new
    client per call (which leaks connections and exhausts a capped Redis on the hot auth path)."""
    global _REDIS
    if _REDIS is None:
        from lab.platform.redis_client import client
        _REDIS = client()
    return _REDIS


async def _developer_key(claims: dict) -> str:
    """One virtual key per developer (Entra oid), created on first login into the
    `developers` team — so /v1/models shows their allowlist and spend attributes per person.
    Uses LiteLLM's INTERNAL key generator (awaited, shares the proxy's Prisma client) — never
    an HTTP call back to this gateway, which would deadlock the worker inside the auth hook.
    The oid->key mapping is cached in Redis; blocking Redis I/O is offloaded off the event loop."""
    import asyncio

    oid = claims.get("oid") or claims.get("sub")
    upn = claims.get("preferred_username") or claims.get("upn") or oid
    cache_key = f"devkey:{oid}"
    key = await asyncio.to_thread(lambda: _redis().get(cache_key))
    if key:
        return key
    team_id = os.environ.get("DEVELOPERS_TEAM_ID")
    if not team_id:
        raise ValueError("DEVELOPERS_TEAM_ID is not set — JIT developer keys need the `developers` team id in .env")
    from litellm.proxy.management_endpoints.key_management_endpoints import generate_key_helper_fn
    resp = await generate_key_helper_fn(
        request_type="key", table_name="key",
        team_id=team_id, key_alias=f"dev-{upn}",
        max_budget=10.0, budget_duration="30d",
        metadata={"entra_oid": oid, "upn": upn, "provisioned": "jit-entra-login"})
    key = resp.get("token") or resp.get("key")
    await asyncio.to_thread(lambda: _redis().set(cache_key, key))
    return key
