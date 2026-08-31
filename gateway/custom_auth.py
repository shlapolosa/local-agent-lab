"""LiteLLM custom auth: Entra ID JWTs at the gateway (the APIM validate-jwt analogue).

An agent presents `Authorization: Bearer <Entra access token>` obtained with MSAL
client-credentials. This hook validates it (issuer, audience, signature via the tenant's
JWKS) and maps the calling app registration (appid/azp claim) to the agent's LiteLLM
virtual key — so budgets, rate limits, spend and tool ACLs keep enforcing exactly as
before, but the credential is now the IdP's, not a static key.

Static virtual keys (sk-…) and the master key still work: non-JWT tokens fall through to
LiteLLM's normal auth. Mapping lives in ENTRA_CLIENT_TO_KEY (JSON: {client_id: virtual_key});
1:1 key ↔ app registration per the design.
Wire-up: general_settings.custom_auth: gateway.custom_auth.user_api_key_auth
"""
import json
import os
import time
import urllib.request

from fastapi import Request

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
    except Exception:
        return None                                    # a JWT, but not one of ours (e.g. litellm ui jwt)
    app_id = claims.get("azp") or claims.get("appid")
    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    vkey = mapping.get(app_id)
    if not vkey:
        raise ValueError(f"app registration {app_id} has no virtual key mapping (roles={claims.get('roles')})")
    return vkey
