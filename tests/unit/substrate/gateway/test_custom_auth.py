"""Offline tests for src/lab/substrate/gateway/custom_auth.py — the LiteLLM custom-auth hook (APIM validate-jwt analogue).

Contract pinned here: `user_api_key_auth(request, api_key)` returns None (not a lab JWT -> LiteLLM's
normal key auth) or a virtual-key STRING (LiteLLM then runs its own key auth on it); an agent JWT
with no mapping raises; it NEVER calls LiteLLM's built-in `user_api_key_auth` (re-entrancy = 500s).
No network: the tenant JWKS fetch is faked with an RSA key pair minted in-process (PyJWT +
cryptography, the same libraries the module uses), Redis is an in-memory dict, and LiteLLM's
`generate_key_helper_fn` is a recording fake. Env is set here — never read from the real .env.

Run: `.venv/bin/python tests/unit/substrate/gateway/test_custom_auth.py`  (also pytest-compatible).
"""
import ast
import asyncio
import importlib
import importlib.util
import io
import json
import os
import sys
import time
import urllib.request

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

TENANT = "11111111-2222-3333-4444-555555555555"
AUD = "api://lab-gateway-fake"
AGENT_APP = "agent-app-client-id"
AGENT_KEY = "sk-agent-virtual-key"
ENV = {
    "ENTRA_TENANT_ID": TENANT,
    "ENTRA_GATEWAY_AUDIENCE": AUD,
    "ENTRA_CLIENT_TO_KEY": json.dumps({AGENT_APP: AGENT_KEY}),
    "REDIS_URL": "redis://127.0.0.1:1/0",           # never connected to: constructing a client is lazy
}

CA_PATH = os.path.join(ROOT, "src", "lab", "substrate", "gateway", "custom_auth.py")

ca = None                                            # the module under test; loaded by `_fake_tenant`


def _load_by_file_path():
    """Load the hook from its file path (as LiteLLM would for a config-relative module); its `lab.*`
    imports resolve through the installed package, not through any sys.path bootstrap."""
    spec = importlib.util.spec_from_file_location("lab_custom_auth", CA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module", autouse=True)
def _fake_tenant():
    """The hook reads ENTRA_* ONCE at import (TENANT/AUDIENCE/ISSUERS are module constants), so the
    fake tenant is pinned around the import — in a fixture, not at module import, where it would
    leak the fake Entra tenant into every other test module. Torn down with the module."""
    global ca
    mp = pytest.MonkeyPatch()
    for k, v in ENV.items():
        mp.setenv(k, v)
    mp.delenv("DEVELOPERS_TEAM_ID", raising=False)
    ca = _load_by_file_path()
    yield
    sys.modules.pop("lab.substrate.gateway.custom_auth", None)   # imported below with the fake tenant
    mp.undo()
    ca = None

# ---------------------------------------------------------------- key material + token minting
_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "lab-kid-1"


def _pem(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIV.public_key()))
JWK["kid"] = KID
JWKS_URL = f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"


def mint(claims=None, *, key=_PRIV, kid=KID):
    now = int(time.time())
    c = {"aud": AUD, "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
         "iat": now - 5, "nbf": now - 5, "exp": now + 600, "azp": AGENT_APP, "roles": ["EA.Model"]}
    c.update(claims or {})
    return jwt.encode(c, _pem(key), algorithm="RS256", headers={"kid": kid})


class FakeJwks:
    """Stands in for urllib.request.urlopen on the tenant's discovery endpoint."""
    def __init__(self, keys=None):
        self.keys, self.calls = keys if keys is not None else [JWK], []

    def __call__(self, url, timeout=None):
        self.calls.append((url, timeout))
        return io.BytesIO(json.dumps({"keys": self.keys}).encode())


class FakeRedis:
    def __init__(self):
        self.store, self.ops = {}, []

    def get(self, k):
        self.ops.append(("get", k))
        return self.store.get(k)

    def set(self, k, v):
        self.ops.append(("set", k, v))
        self.store[k] = v
        return True


class _Patch:
    """Minimal attribute monkeypatch with restore (no pytest fixture dependency)."""
    def __init__(self):
        self.saved = []

    def set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def env(self, name, value):
        self.saved.append((os.environ, name, os.environ.get(name)))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def undo(self):
        for obj, name, old in reversed(self.saved):
            if obj is os.environ:
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
            else:
                setattr(obj, name, old)
        self.saved.clear()


@pytest.fixture(autouse=True)
def _no_leaked_patches():
    """`_fresh()` patches the PROCESS-global `urllib.request.urlopen`; a test that forgets its
    `p.undo()` used to leave the fake JWKS endpoint installed for the rest of the session (it broke
    xmlschema's XSD loading three test packages later). Restore it whatever a test does."""
    saved = urllib.request.urlopen
    yield
    urllib.request.urlopen = saved


def _fresh(jwks=None):
    """Reset the module's caches and install a fake JWKS endpoint; returns (patch, fake)."""
    p = _Patch()
    fake = jwks or FakeJwks()
    ca._JWKS.update(keys=None, at=0.0)
    ca._MAPPING.update(raw=None, parsed={})
    ca._REDIS = None
    p.set(urllib.request, "urlopen", fake)
    return p, fake


def auth(token):
    return asyncio.run(ca.user_api_key_auth(None, token))


# ---------------------------------------------------------------- module loading (LiteLLM style)
def test_loads_by_file_path_and_as_the_dotted_module():
    assert callable(ca.user_api_key_auth) and ca.TENANT == TENANT and ca.AUDIENCE == AUD
    assert ca.ISSUERS == (f"https://login.microsoftonline.com/{TENANT}/v2.0",
                          f"https://sts.windows.net/{TENANT}/")
    # the dotted module LiteLLM resolves from config/litellm-config.yaml is the same code
    as_module = importlib.import_module("lab.substrate.gateway.custom_auth")
    assert as_module.__file__ == ca.__file__ and callable(as_module.user_api_key_auth)


def test_contract_never_calls_litellm_builtin_auth():
    """The hook must never import/call LiteLLM's own user_api_key_auth (re-entrancy -> 500s)."""
    tree = ast.parse(open(CA_PATH).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("litellm.proxy.auth"), ast.dump(node)
            assert "user_api_key_auth" not in [a.name for a in node.names], ast.dump(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "user_api_key_auth", "hook calls user_api_key_auth (recursion)"
    assert "generate_key_helper_fn" in open(CA_PATH).read()     # the internal generator, not HTTP


# ---------------------------------------------------------------- non-JWT credentials
def test_non_jwt_credentials_fall_through_to_normal_key_auth():
    p, fake = _fresh()
    try:
        for cred in ("sk-static-virtual-key", "Bearer sk-master", "", None, "eyJ.onlyonedot",
                     "notjwt.a.b", "Bearer "):
            assert auth(cred) is None, cred
        assert fake.calls == []                                 # no JWKS fetch for non-JWTs
    finally:
        p.undo()


# ---------------------------------------------------------------- agent (client-credentials) JWTs
def test_agent_jwt_maps_to_virtual_key_and_jwks_is_cached():
    p, fake = _fresh()
    try:
        tok = mint()
        assert auth(tok) == AGENT_KEY
        assert auth("Bearer " + tok) == AGENT_KEY                # bearer prefix stripped
        assert fake.calls == [(JWKS_URL, 30)]                    # fetched ONCE (hourly cache)
        # v1 tokens: sts.windows.net issuer + audience without the api:// scheme, appid claim
        v1 = mint({"iss": f"https://sts.windows.net/{TENANT}/", "aud": AUD.replace("api://", ""),
                   "azp": None, "appid": AGENT_APP})
        assert auth(v1) == AGENT_KEY
        assert len(fake.calls) == 1
        # cache expiry (> 1 h) -> refetch
        ca._JWKS["at"] = time.time() - 3601
        assert auth(tok) == AGENT_KEY
        assert len(fake.calls) == 2
    finally:
        p.undo()


def test_agent_jwt_negatives_fall_through_to_key_auth():
    p, fake = _fresh()
    try:
        now = int(time.time())
        bad = {
            "expired": mint({"exp": now - 60}),
            "wrong audience": mint({"aud": "api://someone-else"}),
            "bad signature": mint(key=_OTHER),
            "unknown kid": mint(kid="no-such-kid"),
            "untrusted issuer": mint({"iss": "https://login.microsoftonline.com/other-tenant/v2.0"}),
            "wrong tenant": mint({"tid": "other-tenant"}),
            "not yet valid": mint({"nbf": now + 600}),
            "garbage": "eyJhbGciOiJSUzI1NiJ9.notbase64!.sig",
        }
        for why, tok in bad.items():
            assert auth(tok) is None, why
        # a rejected JWT never raises and never returns a key string
        assert all(auth(t) in (None,) for t in bad.values())
    finally:
        p.undo()


def test_unmapped_app_registration_raises_not_none():
    p, _ = _fresh()
    try:
        tok = mint({"azp": "unknown-app-id", "roles": ["Tools.ADOIT"]})
        try:
            auth(tok)
        except ValueError as e:
            assert "unknown-app-id" in str(e) and "Tools.ADOIT" in str(e)
        else:
            raise AssertionError("unmapped app must raise, not silently fall through")
    finally:
        p.undo()


def test_client_mapping_reparses_only_when_env_value_changes():
    p, _ = _fresh()
    try:
        first = ca._client_mapping()
        assert first == {AGENT_APP: AGENT_KEY}
        assert ca._client_mapping() is first                     # same value -> no re-parse
        p.env("ENTRA_CLIENT_TO_KEY", json.dumps({"other-app": "sk-other"}))
        assert ca._client_mapping() == {"other-app": "sk-other"}
        assert auth(mint({"azp": "other-app"})) == "sk-other"    # live env change honoured
        p.env("ENTRA_CLIENT_TO_KEY", None)                       # unset -> empty mapping
        assert ca._client_mapping() == {}
    finally:
        p.undo()


# ---------------------------------------------------------------- developer (delegated) JWTs -> JIT key
class FakeKeyGen:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    async def __call__(self, **kw):
        self.calls.append(kw)
        return self.resp


def _dev_token(**extra):
    c = {"scp": "access_as_user", "oid": "oid-dev-1", "preferred_username": "dev@example.com",
         "azp": "az-cli-public-client"}
    c.update(extra)
    return mint(c)


def test_developer_jwt_provisions_key_once_then_hits_redis_cache():
    import litellm.proxy.management_endpoints.key_management_endpoints as km
    p, _ = _fresh()
    r, gen = FakeRedis(), FakeKeyGen({"token": "sk-dev-jit-1"})
    ca._REDIS = r
    p.set(km, "generate_key_helper_fn", gen)
    p.env("DEVELOPERS_TEAM_ID", "team-developers")
    try:
        assert auth(_dev_token()) == "sk-dev-jit-1"
        assert len(gen.calls) == 1
        kw = gen.calls[0]
        assert kw["team_id"] == "team-developers" and kw["key_alias"] == "dev-dev@example.com"
        assert kw["request_type"] == "key" and kw["table_name"] == "key"
        assert kw["max_budget"] == 10.0 and kw["budget_duration"] == "30d"
        assert kw["metadata"] == {"entra_oid": "oid-dev-1", "upn": "dev@example.com",
                                  "provisioned": "jit-entra-login"}
        assert r.store == {"devkey:oid-dev-1": "sk-dev-jit-1"}
        # second login: Redis hit, no second key
        assert auth(_dev_token()) == "sk-dev-jit-1"
        assert len(gen.calls) == 1
        assert r.ops[-1] == ("get", "devkey:oid-dev-1")
    finally:
        p.undo()


def test_developer_jwt_claim_fallbacks_and_key_field():
    import litellm.proxy.management_endpoints.key_management_endpoints as km
    p, _ = _fresh()
    r, gen = FakeRedis(), FakeKeyGen({"key": "sk-dev-jit-2"})     # generator may answer `key`
    ca._REDIS = r
    p.set(km, "generate_key_helper_fn", gen)
    p.env("DEVELOPERS_TEAM_ID", "team-developers")
    try:
        # no oid -> sub; no preferred_username -> upn; roles-less delegated token
        tok = _dev_token(oid=None, sub="sub-9", preferred_username=None, upn="u@example.com")
        assert auth(tok) == "sk-dev-jit-2"
        assert gen.calls[0]["key_alias"] == "dev-u@example.com"
        assert gen.calls[0]["metadata"]["entra_oid"] == "sub-9"
        assert r.store == {"devkey:sub-9": "sk-dev-jit-2"}
        # neither preferred_username nor upn -> the oid itself is the alias suffix
        tok = _dev_token(oid="oid-3", preferred_username=None)
        assert auth(tok) == "sk-dev-jit-2"
        assert gen.calls[1]["key_alias"] == "dev-oid-3"
    finally:
        p.undo()


def test_developer_jwt_without_developers_team_id_raises():
    import litellm.proxy.management_endpoints.key_management_endpoints as km
    p, _ = _fresh()
    r, gen = FakeRedis(), FakeKeyGen({"token": "never"})
    ca._REDIS = r
    p.set(km, "generate_key_helper_fn", gen)
    p.env("DEVELOPERS_TEAM_ID", None)
    try:
        try:
            auth(_dev_token())
        except ValueError as e:
            assert "DEVELOPERS_TEAM_ID" in str(e)
        else:
            raise AssertionError("missing DEVELOPERS_TEAM_ID must raise")
        assert gen.calls == [] and r.store == {}                # nothing provisioned
    finally:
        p.undo()


# ---------------------------------------------------------------- the Redis seam
def test_redis_uses_shared_pooled_client_and_caches_it():
    import lab.platform.redis_client as rc
    p, _ = _fresh()
    fake, calls = FakeRedis(), []

    def client(*a, **k):
        calls.append((a, k))
        return fake
    p.set(rc, "client", client)
    try:
        assert ca._redis() is fake and ca._redis() is fake
        assert calls == [((), {})]                               # ONE pooled client, built once
    finally:
        p.undo()


def test_redis_is_the_shared_pooled_client_when_loaded_by_file_path():
    """No inline fallback client (review F6): the file-path-loaded hook (LiteLLM's way) uses THE
    lab's pooled client — same object lab.platform.redis_client hands every other module."""
    import lab.platform.redis_client as rc
    _fresh()
    r = ca._redis()
    assert r is rc.client()                                      # constructed lazily, never connected
    assert r.connection_pool.connection_kwargs["decode_responses"] is True
    assert "redis.Redis.from_url" not in open(CA_PATH).read()    # one home for the client


def test_return_type_is_always_none_or_str():
    import litellm.proxy.management_endpoints.key_management_endpoints as km
    p, _ = _fresh()
    ca._REDIS = FakeRedis()
    p.set(km, "generate_key_helper_fn", FakeKeyGen({"token": "sk-x"}))
    p.env("DEVELOPERS_TEAM_ID", "t")
    try:
        for cred in ("sk-static", mint(), _dev_token(), mint({"exp": 1})):
            out = auth(cred)
            assert out is None or isinstance(out, str), (cred, out)
    finally:
        p.undo()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ============================================================ /api per-operation authorisation
# The front door's REST ingress is authorised HERE and not at the front door, because LiteLLM's
# pass-through replaces the caller's Authorization with a static one — measured: the backend receives
# only accept, authorization, connection, host, user-agent. The caller's identity does not survive
# the hop, so the check runs where the validated claims already are. These tests pin that rule.
from lab.platform.contracts import ApiRoles                                          # noqa: E402
from lab.substrate import apipolicy                                                  # noqa: E402

SUBMIT_PATH = "/api/processes/meeting_to_transcript/runs"
DECIDE_PATH = "/api/approvals/apr-1/decide"


class Req:
    """The slice of starlette's Request the hook reads: a method and a URL path."""
    def __init__(self, path, method="POST"):
        self.url = type("U", (), {"path": path})()
        self.method = method


def auth_req(token, request):
    return asyncio.run(ca.user_api_key_auth(request, token))


def _denied(token, request):
    """The ValueError the hook raises for a refused call, as a string."""
    with pytest.raises(ValueError) as e:
        auth_req(token, request)
    return str(e.value)


def test_api_call_with_the_required_role_is_authorised_and_maps_to_the_virtual_key():
    p, _ = _fresh()
    try:
        tok = mint({"roles": [ApiRoles.SUBMIT]})
        assert auth_req(tok, Req(SUBMIT_PATH)) == AGENT_KEY
        assert auth_req(tok, Req(SUBMIT_PATH.rsplit("/", 1)[0] + "/runs/wfr-1", "GET")) == AGENT_KEY
    finally:
        p.undo()


def test_api_call_without_the_required_role_is_refused_and_says_which_role_it_wanted():
    """The likeliest cause is a missing appRoleAssignment, so the error names the role and what the
    app registration actually holds — not a bare 401 someone has to guess at."""
    p, _ = _fresh()
    try:
        msg = _denied(mint({"roles": ["EA.Model"]}), Req(SUBMIT_PATH))
        assert ApiRoles.SUBMIT in msg and "EA.Model" in msg and AGENT_APP in msg
    finally:
        p.undo()


def test_reading_approvals_does_not_let_a_caller_decide_one():
    """The split that matters most: a relay granted only READ must not be able to answer for a human.
    Nothing else in the lab enforces this for REST — per-tool ACLs cannot see a path."""
    p, _ = _fresh()
    try:
        reader = mint({"roles": [ApiRoles.READ]})
        assert auth_req(reader, Req("/api/approvals", "GET")) == AGENT_KEY
        assert auth_req(reader, Req("/api/approvals/apr-1", "GET")) == AGENT_KEY
        assert ApiRoles.DECIDE in _denied(reader, Req(DECIDE_PATH))
        # and the converse: DECIDE alone does not confer listing
        assert ApiRoles.READ in _denied(mint({"roles": [ApiRoles.DECIDE]}), Req("/api/approvals", "GET"))
    finally:
        p.undo()


def test_a_virtual_key_cannot_call_api_because_it_carries_no_roles():
    """Every /api caller is an app registration by design. A static key authenticates but says
    nothing about what it may do, so it is refused with the acquisition instructions."""
    p, _ = _fresh()
    try:
        p.env("LITELLM_MASTER_KEY", "sk-the-master")
        msg = _denied("sk-some-agent-key", Req(SUBMIT_PATH))
        assert "Entra access token" in msg and AUD in msg
        # ... while the same key is untouched everywhere else
        assert auth_req("sk-some-agent-key", Req("/v1/chat/completions")) is None
    finally:
        p.undo()


def test_the_master_key_is_the_admin_plane_and_still_reaches_api():
    p, _ = _fresh()
    try:
        p.env("LITELLM_MASTER_KEY", "sk-the-master")
        assert auth_req("sk-the-master", Req(SUBMIT_PATH)) is None          # -> LiteLLM key auth
        assert auth_req("Bearer sk-the-master", Req(DECIDE_PATH)) is None
    finally:
        p.undo()


def test_an_unset_master_key_does_not_make_the_empty_credential_an_admin():
    """`"" == os.environ.get(..., "")` would have been true — the bug this guards."""
    p, _ = _fresh()
    try:
        p.env("LITELLM_MASTER_KEY", None)
        for cred in ("", None, "Bearer "):
            assert "Entra access token" in _denied(cred, Req(SUBMIT_PATH))
    finally:
        p.undo()


def test_an_unknown_api_path_is_denied_rather_than_allowed():
    """Default deny. A route added without a policy entry must fail closed, not become reachable by
    anyone holding any role."""
    p, _ = _fresh()
    try:
        msg = _denied(mint({"roles": list(ApiRoles.ALL)}), Req("/api/secret-new-route"))
        assert "not an operation of the workflow front door" in msg
        assert all(o.name in msg for o in apipolicy.OPERATIONS)
    finally:
        p.undo()


def test_a_token_this_tenant_did_not_issue_is_refused_on_api_instead_of_falling_through():
    """Off /api an unrecognised JWT falls through to key auth (it may be the LiteLLM UI's own).
    On /api that would authorise an operation on an unverified token, so it must refuse."""
    p, _ = _fresh()
    try:
        foreign = mint(key=_OTHER)                                  # signed by the wrong key
        assert auth_req(foreign, Req("/v1/chat/completions")) is None
        assert "not a valid Entra token" in _denied(foreign, Req(SUBMIT_PATH))
    finally:
        p.undo()


def test_a_delegated_user_token_is_refused_on_api_and_still_works_elsewhere():
    """A user token carries `scp`, not `roles`, so there is nothing to authorise the operation with.
    A signed-in human decides at the review app, which reaches the gate in-process."""
    p, fake = _fresh()
    try:
        p.env("DEVELOPERS_TEAM_ID", None)
        p.set(ca, "_REDIS", FakeRedis())          # the off-/api branch consults its key cache first
        user = mint({"scp": "access_as_user", "oid": "user-oid-1"})
        assert "APP ROLES" in _denied(user, Req(DECIDE_PATH))
        # off /api it takes the JIT developer-key path (which needs the team id — absent, so it
        # raises for a DIFFERENT, named reason, proving the branch was reached)
        assert "DEVELOPERS_TEAM_ID" in _denied(user, Req("/v1/models", "GET"))
    finally:
        p.undo()


def test_non_api_routes_are_completely_unaffected_by_the_policy():
    """The role check must not leak onto model calls or the MCP surface, which are governed by
    LiteLLM's key auth and per-tool ACLs."""
    p, _ = _fresh()
    try:
        roleless = mint({"roles": []})
        for path in ("/v1/chat/completions", "/mcp/", "/health", "/apifoo"):
            assert auth_req(roleless, Req(path, "GET")) == AGENT_KEY, path
        assert auth_req(roleless, None) == AGENT_KEY            # no request at all (LiteLLM internals)
    finally:
        p.undo()
