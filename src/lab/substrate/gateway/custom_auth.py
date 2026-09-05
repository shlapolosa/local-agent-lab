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

SECOND JOB: PER-OPERATION AUTHORISATION FOR THE REST FRONT DOOR (`/api`).
The hook authenticates for every route, but the workflow front door's REST ingress additionally needs
to know WHICH operation a caller may invoke, and that check has to happen HERE — not at the front
door — for a reason worth stating, because it was found the hard way. LiteLLM's pass-through forwards
a STATIC `Authorization` to the backend, and its `forward_headers` drops any incoming header that
collides with a configured one; `x-pass-` headers are caller-controlled. Measured: the front door
receives only accept, authorization (the shared secret), connection, host and user-agent. **The
caller's identity does not survive the gateway hop.** So the front door has nothing to authorise on,
while this hook holds the validated claims already — enforcing where the identity exists needs no
identity forwarding at all.

The rule, applied only to paths `lab.substrate.apipolicy` governs:
  * an Entra client-credentials token -> the `roles` claim must contain the operation's role;
  * an unknown operation under the prefix -> DENIED (a route added without a policy entry fails closed);
  * a static virtual key -> DENIED, because a key carries no roles and every /api caller is an app
    registration by design. The MASTER key is excepted: it is the admin plane, the APIM equivalent of
    a full-rights subscription key, and operations need a way in.
  * a delegated USER token (`access_as_user`) -> DENIED on /api: it carries `scp`, not `roles`. A
    signed-in human decides at the review app, which calls the gate in-process. A browser client
    deciding through /api would need a delegated-scope branch here; there is no such caller today.
This is the APIM `<required-claims>` analogue and migrates as configuration: the table moves, the
enforcement moves to the edge policy, and nothing in the front door changes either way.
"""
import json
import logging
import os
import time
import urllib.request

from fastapi import Request

from lab.substrate import apipolicy

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
    path = getattr(getattr(request, "url", None), "path", "") or ""
    method = (getattr(request, "method", "") or "GET").upper()
    # Is this one of the front door's REST operations? If so the credential must additionally carry
    # the app role for it, and the ways of failing that are each refused with the reason attached.
    api = apipolicy.governs(path)

    token = (api_key or "").removeprefix("Bearer ").strip()
    if token.count(".") != 2 or not token.startswith("eyJ"):
        if api and not _is_master(token):
            raise ValueError(
                f"{method} {path} requires an Entra access token: a virtual key carries no app roles, "
                "so there is nothing to authorise this operation against. Acquire a token for "
                f"{AUDIENCE} with the caller's app registration (client credentials).")
        return None                                    # static keys / master key: normal auth
    try:
        claims = _validate(token)
    except Exception as e:                         # noqa: BLE001
        # a JWT, but not one of ours (e.g. the LiteLLM UI's own jwt) -> normal key auth; keep the
        # reason visible so JWKS / clock / audience failures are debuggable instead of silent
        log.debug("entra jwt rejected (%s: %s) — falling through to key auth", type(e).__name__, e)
        if api:
            # ... but never on /api: falling through would authorise an operation on a token this
            # tenant did not issue, which is the whole thing the check exists to stop.
            raise ValueError(f"{method} {path}: the bearer token is not a valid Entra token for this "
                             f"tenant ({type(e).__name__}: {e})") from e
        return None
    # --- interactive DEVELOPER tokens (delegated scope) -> JIT personal virtual key ---
    if "access_as_user" in (claims.get("scp") or ""):
        if api:
            raise ValueError(
                f"{method} {path} is authorised by APP ROLES, which a delegated user token does not "
                "carry. A signed-in person decides at the review app, which reaches the gate "
                "in-process; a relay calls this door with its own app registration and records the "
                "person as `actor`.")
        return await _developer_key(claims)
    # --- agent (client-credentials) tokens -> static app->key mapping ---
    app_id = claims.get("azp") or claims.get("appid")
    vkey = _client_mapping().get(app_id)
    if not vkey:
        raise ValueError(f"app registration {app_id} has no virtual key mapping (roles={claims.get('roles')})")
    if api:
        _authorise(method, path, claims, app_id)
    return vkey


def _is_master(token: str) -> bool:
    """The admin plane — the APIM full-rights subscription key. Compared explicitly rather than
    allowing every non-JWT credential, and false when no master key is configured, so an unset
    LITELLM_MASTER_KEY cannot make the empty string an admin."""
    master = os.environ.get("LITELLM_MASTER_KEY", "")
    return bool(master) and token == master


def _authorise(method: str, path: str, claims: dict, app_id: str) -> None:
    """The `<required-claims>` check. Raises with the role it wanted and the roles the caller holds —
    an app registration missing a role assignment is the likeliest cause and the error should say so
    rather than leave someone guessing at a bare 401."""
    op = apipolicy.operation(method, path)
    if op is None:
        raise ValueError(f"{method} {path} is not an operation of the workflow front door "
                         f"(known: {', '.join(o.name for o in apipolicy.OPERATIONS)})")
    roles = tuple(claims.get("roles") or ())
    if op.role not in roles:
        raise ValueError(f"{method} {path} ({op.name}: {op.description}) requires the {op.role!r} app "
                         f"role; app registration {app_id} holds {list(roles) or 'no roles'}")


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
