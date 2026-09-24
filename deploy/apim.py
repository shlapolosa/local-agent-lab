"""Production's gateway — Azure API Management — rendered from what the lab already declares.

APIM is production's ONLY gateway; LiteLLM is development's, and the two never meet (decision record
2026-09-24, Phase 2). Nothing here is a second copy of a rule:
  * the MODEL names and what serves each come from the production model overlay
    (config/litellm-models.azure.yaml) — the same file the LiteLLM gateway was started with;
  * the /api OPERATIONS and the app role each requires come from `lab.substrate.apipolicy` — the table
    CLAUDE.md already calls "the APIM validate-jwt + <required-claims> analogue".

A caller is admitted by a token for the PRODUCTION audience carrying the operation's role, or — the
virtual key's analogue, for callers that cannot hold an Entra identity — by an APIM subscription.
There is no third way in. APIM answers an unmatched path with 404 by construction, which is the
table's default DENY without a rule to write.

    python deploy/apim.py render            # print every policy (no Azure call)
    python deploy/apim.py apply models      # PUT the models API and its policies (idempotent)
    python deploy/apim.py apply frontdoor   # PUT the /api operations
    python deploy/apim.py apply mcp         # PUT one API per MCP server (and the bearer both use)
    python deploy/apim.py apply products    # PUT a product per key team + a subscription per key caller

Policies are sent in APIM's `xml` format, so every expression is XML-escaped here and the tests can
parse what is deployed; APIM decodes the entities before it compiles the expression.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape as _xml

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grants  # noqa: E402
import topology  # noqa: E402
from lab.substrate import apipolicy  # noqa: E402

BASE_CONFIG = ROOT / "config" / "litellm-config.yaml"
OVERLAY = ROOT / "config" / "litellm-models.azure.yaml"

APIM_API = "2024-05-01"
MODELS_API, FRONTDOOR_API = "models", "frontdoor"
MODELS_ROLE = "Models.Use"
#: Tokens a minute per CALLER (a subscription, or an Entra app's azp) — the per-key tpm LiteLLM enforced.
TOKENS_PER_MINUTE = 60000
#: What the OpenAI surface offers. Foundry's v1 API takes the DEPLOYMENT as `model`, with no api-version.
MODEL_OPERATIONS = (("chat-completions", "POST", "/chat/completions"),
                    ("responses", "POST", "/responses"),
                    ("embeddings", "POST", "/embeddings"),
                    ("models", "GET", "/models"))
#: Fields a client may send that Foundry refuses: `input_type` is an embedding hint LiteLLM dropped.
STRIPPED = ("input_type",)


# ------------------------------------------------------------------ models
def model_aliases(config_path: Path = BASE_CONFIG, overlay_path: Path = OVERLAY) -> dict[str, dict]:
    """Gateway name -> {deployment, reasoning_effort?}: what the overlay says serves each served name."""
    served = [m["model_name"] for m in yaml.safe_load(open(config_path)).get("model_list", [])]
    overlay = yaml.safe_load(open(overlay_path))
    out = {}
    for name in served:
        params = overlay.get(name)
        if params is None:
            continue
        provider, _, deployment = params["model"].partition("/")
        if provider != "azure":
            raise ValueError(f"{name}: production serves Foundry deployments only, not {params['model']}")
        out[name] = {"deployment": deployment,
                     **({"reasoning_effort": params["reasoning_effort"]} if "reasoning_effort" in params else {})}
    return out


def escape(text: str) -> str:
    """XML-escaped for an element OR an attribute (policy expressions are full of double quotes)."""
    return _xml(text, {'"': "&quot;"})


def _cs(value) -> str:
    """A C# string literal carrying `value` as JSON (APIM expressions are C#)."""
    return '"' + json.dumps(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _validate_jwt(tenant: str, audience: str, role: str, variable: str = "") -> str:
    out = f' output-token-variable-name="{variable}"' if variable else ""
    return (f'<validate-jwt header-name="Authorization" failed-validation-httpcode="401" '
            f'failed-validation-error-message="a token for this gateway carrying {role} is required"{out}>'
            f'<openid-config url="https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration" />'
            f'<audiences><audience>{escape(audience)}</audience></audiences>'
            f'<issuers><issuer>https://sts.windows.net/{tenant}/</issuer>'
            f'<issuer>https://login.microsoftonline.com/{tenant}/v2.0</issuer></issuers>'
            f'<required-claims><claim name="roles" match="any"><value>{role}</value></claim></required-claims>'
            f'</validate-jwt>')


def _expr(code: str) -> str:
    return escape("@{" + code + "}")


def key_models(embed_model: str) -> dict[str, list[str]]:
    """Key-holding team -> the models it may call. A team absent here calls none."""
    out = {team: list(models) for team, models in grants.KEY_MODELS.items()}
    if embed_model:
        out["reference-corpus"] = [embed_model]
    return out


def models_policy(tenant: str, audience: str, keyed: dict[str, list[str]] | None = None) -> str:
    """The API-level policy of the OpenAI-shaped models API. `keyed`: key-holding team -> its models."""
    aliases = model_aliases()
    caller = ('context.Subscription != null ? context.Subscription.Id : '
              '((Jwt)context.Variables["jwt"]).Claims.GetValueOrDefault("azp", "unknown")')
    rewrite = (
        f'var aliases = JObject.Parse({_cs(aliases)}); '
        'var body = context.Request.Body.As<JObject>(preserveContent: true); '
        'var name = (string)body["model"]; '
        'var target = name == null ? null : aliases[name]; '
        'if (target == null) { return body.ToString(); } '
        'body["model"] = target["deployment"]; '
        + "".join(f'body.Remove("{f}"); ' for f in STRIPPED) +
        'var effort = target["reasoning_effort"]; '
        'if (effort != null) { '
        '  if (context.Request.Url.Path.EndsWith("/responses")) { body["reasoning"] = new JObject(new JProperty("effort", effort)); } '
        '  else { body["reasoning_effort"] = effort; } } '
        'return body.ToString();')
    known = 'JObject.Parse(' + _cs(aliases) + ')'
    unknown = (f'var body = context.Request.Body.As<JObject>(preserveContent: true); '
               f'var name = (string)body["model"]; '
               f'return name != null && {known}[name] == null;')
    key_refused = (
        'if (context.Subscription == null) { return false; } '
        f'var keyed = JObject.Parse({_cs(keyed or {})}); '
        'var allowed = keyed[context.Product != null ? context.Product.Id : ""]; '
        'if (allowed == null) { return true; } '
        'if (context.Request.Method != "POST") { return false; } '
        'var model = (string)context.Request.Body.As<JObject>(preserveContent: true)["model"]; '
        'return !allowed.Any(m => (string)m == model);')
    return (
        '<policies><inbound><base />'
        # a caller without a subscription must present a production token carrying Models.Use
        '<choose><when condition="' + escape('@(context.Subscription == null)') + '">'
        + _validate_jwt(tenant, audience, MODELS_ROLE, "jwt") +
        '</when></choose>'
        # ...and one WITH a subscription calls only the models its team declares (none = refused)
        f'<choose><when condition="{_expr(key_refused)}">'
        '<return-response><set-status code="403" reason="Forbidden" />'
        '<set-body>{"error":{"message":"this key may not call that model"}}</set-body></return-response>'
        '</when></choose>'
        f'<llm-token-limit counter-key="{escape("@(" + caller + ")")}" tokens-per-minute="{TOKENS_PER_MINUTE}" '
        'estimate-prompt-tokens="false" remaining-tokens-variable-name="remainingTokens" />'
        '<llm-emit-token-metric namespace="lab-gateway">'
        f'<dimension name="Caller" value="{escape("@(" + caller + ")")}" />'
        '<dimension name="API ID" /><dimension name="Operation ID" /></llm-emit-token-metric>'
        # the caller's credential never reaches Foundry: APIM calls it as ITSELF
        '<set-header name="Authorization" exists-action="delete" />'
        '<set-header name="api-key" exists-action="delete" />'
        '<authentication-managed-identity resource="https://cognitiveservices.azure.com" />'
        '<set-backend-service backend-id="foundry" />'
        '<choose><when condition="' + escape('@(context.Request.Method == "POST")') + '">'
        '<choose><when condition="' + _expr(unknown) + '">'
        '<return-response><set-status code="404" reason="Not Found" />'
        '<set-body>{"error":{"message":"this gateway does not serve that model"}}</set-body></return-response>'
        '</when></choose>'
        '<set-body>' + _expr(rewrite) + '</set-body>'
        '</when></choose>'
        '</inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>')


def models_list_policy() -> str:
    """GET /models answers with the gateway's NAMES — Foundry's own list names base models, not ours."""
    listing = json.dumps({"object": "list", "data": [{"id": n, "object": "model", "owned_by": "lab"}
                                                     for n in model_aliases()]})
    return ('<policies><inbound><base /><return-response><set-status code="200" reason="OK" />'
            '<set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>'
            f'<set-body>{escape(listing)}</set-body></return-response></inbound>'
            '<backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>')


# ------------------------------------------------------------------ the /api front door
def _template(op: apipolicy.Operation) -> str:
    """`/processes/[^/]+/runs` -> `/processes/{process}/runs`: a parameter per segment, named after the
    collection it indexes, matching exactly what the pattern matches."""
    path = op.pattern.pattern[len(re.escape(apipolicy.API_PREFIX)):]
    return re.sub(r"/([^/]+)/" + re.escape(apipolicy._SEG),
                  lambda m: f"/{m.group(1)}/{{{_singular(m.group(1))}}}", path)


def _singular(word: str) -> str:
    return word[:-2] if word.endswith("sses") else word[:-1] if word.endswith("s") else word


def frontdoor_operations() -> list[dict]:
    return [{"name": op.name.replace(".", "-"), "method": op.method, "urlTemplate": _template(op),
             "role": op.role, "description": op.description} for op in apipolicy.OPERATIONS]


def frontdoor_operation_policy(role: str, tenant: str, audience: str, *, stream: bool = False) -> str:
    """One operation: a production token carrying `role`; the front door then sees only the substrate's
    shared bearer, exactly as it did behind LiteLLM."""
    backend = '<forward-request buffer-response="false" />' if stream else "<base />"
    return ('<policies><inbound><base />' + _validate_jwt(tenant, audience, role) +
            '<set-header name="Authorization" exists-action="override">'
            '<value>Bearer {{mcp-shared-secret}}</value></set-header></inbound>'
            f'<backend>{backend}</backend><outbound><base /></outbound><on-error><base /></on-error></policies>')


# ------------------------------------------------------------------ MCP servers
#: How long APIM waits for an MCP backend's response headers. Above the lab's own bound on a whole
#: exchange (config.TOOL_CALL_TIMEOUT_S) would be pointless; the stream itself is not buffered.
MCP_TIMEOUT_S = 1000
#: The team a SUBSCRIPTION caller belongs to is its APIM product's id (one product per team).
ROLE_PREFIX = grants.role("")


def mcp_servers(config_path: Path = BASE_CONFIG) -> dict[str, str]:
    """Gateway alias -> the Container App serving it: the alias and its URL variable are the gateway
    config's, the service behind the variable is the topology's."""
    servers = yaml.safe_load(open(config_path))["mcp_servers"]
    out = {}
    for alias, spec in servers.items():
        key = str(spec["url"]).removeprefix("os.environ/")
        out[alias] = topology.MCP_URL_ENV[key]
    return out


def mcp_grants(server: str) -> dict[str, list[str] | str]:
    """team -> tools it may call on `server`, "*" for the whole server — the shape the policy reads."""
    return {team: "*" if tools is None else sorted(tools) for team, tools in grants.for_server(server).items()}


def mcp_policy(server: str, tenant: str, audience: str) -> str:
    """One MCP server's API. A caller is a TEAM — by the `Grant.<team>` roles on its production token, or
    by its subscription's product — and a team may reach this server only if it holds a grant on it, and
    call a tool only if that grant names it. The backend sees the substrate's bearer, never the caller's."""
    teams = (
        'if (context.Subscription != null) { return context.Product != null ? context.Product.Id : ""; } '
        'var jwt = (Jwt)context.Variables["jwt"]; '
        'var roles = jwt.Claims.ContainsKey("roles") ? jwt.Claims["roles"] : new string[0]; '
        f'return string.Join(",", roles.Where(r => r.StartsWith("{ROLE_PREFIX}"))'
        f'.Select(r => r.Substring({len(ROLE_PREFIX)})));')
    decide = (
        f'var grants = JObject.Parse({_cs(mcp_grants(server))}); '
        'var teams = ((string)context.Variables["mcp-teams"]).Split(\',\').Where(t => grants[t] != null).ToArray(); '
        'if (teams.Length == 0) { return "no-grant"; } '
        'if (context.Request.Method != "POST") { return "ok"; } '
        'var token = JToken.Parse(context.Request.Body.As<string>(preserveContent: true)); '
        'if (token.Type != JTokenType.Object) { return "batch"; } '
        'if ((string)token["method"] != "tools/call") { return "ok"; } '
        'var tool = (string)token["params"]["name"]; '
        'foreach (var t in teams) { var g = grants[t]; '
        '  if (g.Type == JTokenType.String || g.Any(x => (string)x == tool)) { return "ok"; } } '
        'return "denied";')
    refuse = lambda code, reason, msg: (  # noqa: E731
        f'<return-response><set-status code="{code}" reason="{reason}" />'
        '<set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>'
        f'<set-body>{escape(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": msg}}))}'
        '</set-body></return-response>')
    return (
        '<policies><inbound><base />'
        '<choose><when condition="' + escape('@(context.Subscription == null)') + '">'
        '<validate-jwt header-name="Authorization" failed-validation-httpcode="401" '
        'failed-validation-error-message="a token for this gateway is required" output-token-variable-name="jwt">'
        f'<openid-config url="https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration" />'
        f'<audiences><audience>{escape(audience)}</audience></audiences>'
        f'<issuers><issuer>https://sts.windows.net/{tenant}/</issuer>'
        f'<issuer>https://login.microsoftonline.com/{tenant}/v2.0</issuer></issuers>'
        '</validate-jwt></when></choose>'
        f'<set-variable name="mcp-teams" value="{_expr(teams)}" />'
        f'<set-variable name="mcp-decision" value="{_expr(decide)}" />'
        '<choose>'
        '<when condition="' + escape('@((string)context.Variables["mcp-decision"] == "no-grant")') + '">'
        + refuse(403, "Forbidden", f"no grant on {server}") + '</when>'
        '<when condition="' + escape('@((string)context.Variables["mcp-decision"] == "batch")') + '">'
        + refuse(400, "Bad Request", "JSON-RPC batches are not accepted") + '</when>'
        '<when condition="' + escape('@((string)context.Variables["mcp-decision"] == "denied")') + '">'
        + refuse(403, "Forbidden", f"that tool is not granted on {server}") + '</when>'
        '</choose>'
        '<set-header name="Authorization" exists-action="override">'
        '<value>Bearer {{mcp-shared-secret}}</value></set-header>'
        '<set-header name="api-key" exists-action="delete" />'
        '</inbound>'
        f'<backend><forward-request timeout="{MCP_TIMEOUT_S}" buffer-response="false" /></backend>'
        '<outbound><base /></outbound><on-error><base /></on-error></policies>')


# ------------------------------------------------------------------ apply
def _params(template: str) -> list[dict]:
    return [{"name": p, "type": "string", "required": True} for p in re.findall(r"\{([^}]+)\}", template)]


class Service:
    """PUTs against one APIM instance. Idempotent: a re-run converges on what this module renders."""

    def __init__(self, arm, url: str):
        self.arm, self.url = arm, url

    def put(self, path: str, body: dict) -> None:
        self.arm.request("PUT", f"{self.url}/{path}?api-version={APIM_API}", body)

    def post(self, path: str) -> dict:
        return self.arm.request("POST", f"{self.url}/{path}?api-version={APIM_API}", {})

    def policy(self, path: str, xml: str) -> None:
        self.put(f"{path}/policies/policy", {"properties": {"format": "xml", "value": xml}})


def apply_models(svc: Service, *, tenant: str, audience: str, foundry: str, embed_model: str) -> None:
    svc.put("backends/foundry", {"properties": {"protocol": "http", "url": foundry.rstrip("/") + "/openai/v1"}})
    svc.put(f"apis/{MODELS_API}", {"properties": {
        "displayName": "Models", "path": "v1", "protocols": ["https"], "subscriptionRequired": False,
        "subscriptionKeyParameterNames": KEY_HEADER}})
    for name, method, url in MODEL_OPERATIONS:
        svc.put(f"apis/{MODELS_API}/operations/{name}",
                {"properties": {"displayName": name, "method": method, "urlTemplate": url}})
    svc.policy(f"apis/{MODELS_API}", models_policy(tenant, audience, key_models(embed_model)))
    svc.policy(f"apis/{MODELS_API}/operations/models", models_list_policy())


def apply_frontdoor(svc: Service, *, tenant: str, audience: str, frontdoor: str) -> None:
    svc.put(f"apis/{FRONTDOOR_API}", {"properties": {
        "displayName": "Front door", "path": "api", "protocols": ["https"], "subscriptionRequired": False,
        "serviceUrl": frontdoor}})
    for o in frontdoor_operations():
        svc.put(f"apis/{FRONTDOOR_API}/operations/{o['name']}", {"properties": {
            "displayName": o["name"], "method": o["method"], "urlTemplate": o["urlTemplate"],
            "description": o["description"], "templateParameters": _params(o["urlTemplate"])}})
        svc.policy(f"apis/{FRONTDOOR_API}/operations/{o['name']}",
                   frontdoor_operation_policy(o["role"], tenant, audience, stream=o["name"].endswith("-events")))


BEARER = "mcp-shared-secret"


def apply_bearer(svc: Service, *, vault_uri: str) -> None:
    """The substrate bearer APIM presents to the MCP servers and the front door: a VERSIONLESS Key Vault
    reference, so a rotated secret reaches the gateway without a redeploy, and no copy lives in APIM."""
    svc.put(f"namedValues/{BEARER}", {"properties": {
        "displayName": BEARER, "secret": True,
        "keyVault": {"secretIdentifier": f"{vault_uri.rstrip('/')}/secrets/{BEARER}"}}})


def apply_mcp(svc: Service, *, tenant: str, audience: str, public) -> None:
    """One API per MCP server at `/mcp/<alias>`, so `<alias>/mcp` is where the aggregating client connects
    (lab.platform.mcp_client.gateway_session). Streamable HTTP uses POST, GET (the stream) and DELETE."""
    for alias, service in mcp_servers().items():
        name = _api_id(alias)
        svc.put(f"apis/{name}", {"properties": {
            "displayName": f"MCP {alias}", "path": f"mcp/{alias}", "protocols": ["https"],
            "subscriptionRequired": False, "subscriptionKeyParameterNames": KEY_HEADER,
            "serviceUrl": public(service)}})
        for method in ("POST", "GET", "DELETE"):
            svc.put(f"apis/{name}/operations/{method.lower()}",
                    {"properties": {"displayName": method, "method": method, "urlTemplate": "/mcp"}})
        svc.policy(f"apis/{name}", mcp_policy(alias, tenant, audience))


#: The header a subscription key travels in, on every API. A key caller sends it ALONGSIDE the
#: `Authorization: Bearer` the dev gateway reads (LiteLLM accepts `api-key` on /v1 but not on /mcp —
#: measured 24 Sep 2026), so one client works against both gateways.
KEY_HEADER = {"header": "api-key", "query": "subscription-key"}


def _api_id(alias: str) -> str:
    return "mcp-" + alias.replace("_", "-")


def product_apis(team: str, models: tuple[str, ...]) -> list[str]:
    """What a key-holding team's product contains: the MCP servers its grant names, and the models API
    only when it calls a model."""
    return ([MODELS_API] if models else []) + sorted(_api_id(s) for s in grants.TEAMS.get(team, {}))


def _subscription_id(var: str) -> str:
    return var.lower().replace("_", "-")


def apply_products(svc: Service, *, embed_model: str) -> None:
    """One product per key-holding team (product id = team: the MCP policy reads it) and one subscription
    per key caller, scoped to it. Keys are read back separately (`subscription_keys`)."""
    keyed = key_models(embed_model)
    for team in sorted(set(grants.KEY_CALLERS.values())):
        svc.put(f"products/{team}", {"properties": {
            "displayName": team, "subscriptionRequired": True, "approvalRequired": False, "state": "published",
            "description": f"The {team} team's key callers (deploy/grants.py KEY_CALLERS)"}})
        for api in product_apis(team, tuple(keyed.get(team, ()))):
            svc.put(f"products/{team}/apis/{api}", {})
    for var, team in grants.KEY_CALLERS.items():
        svc.put(f"subscriptions/{_subscription_id(var)}", {"properties": {
            "displayName": var, "scope": f"/products/{team}", "state": "active"}})


def subscription_keys(svc: Service) -> dict[str, str]:
    """KEY_CALLERS variable -> its subscription's primary key."""
    return {var: svc.post(f"subscriptions/{_subscription_id(var)}/listSecrets")["primaryKey"]
            for var in grants.KEY_CALLERS}


def write_profile_keys(path: Path, values: dict[str, str]) -> None:
    """Set each KEY=value in a profile file: an existing line is replaced in place, a new one appended.
    Values are credentials: this never prints them."""
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:  # pragma: no cover — composition: reads the profile, calls Azure
    if argv[:1] == ["render"]:
        tenant, audience = os.environ.get("ENTRA_TENANT_ID", "<tenant>"), os.environ.get("ENTRA_GATEWAY_AUDIENCE", "<audience>")
        print(models_policy(tenant, audience))
        for o in frontdoor_operations():
            print(o["method"], o["urlTemplate"], o["role"])
        return 0
    if argv[:1] == ["apply"] and argv[1:2] in (["models"], ["frontdoor"], ["mcp"], ["products"]):
        import aca
        sub = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
        if not sub:
            print("set AZURE_SUBSCRIPTION_ID (and AZURE_RESOURCE_GROUP)", file=sys.stderr)
            return 2
        profile, arm = aca.profile(), aca.Arm()
        group = os.environ.get("AZURE_RESOURCE_GROUP", "rg-lab-prod")
        rg = aca._rg(sub, group)
        outputs = arm.request("GET", f"{rg}/providers/Microsoft.Resources/deployments/apim"
                                     "?api-version=2024-03-01")["properties"]["outputs"]
        svc = Service(arm, f"{rg}/providers/Microsoft.ApiManagement/service/{outputs['apimName']['value']}")
        who = dict(tenant=profile["ENTRA_TENANT_ID"], audience=profile["ENTRA_GATEWAY_AUDIENCE"])
        if argv[1] == "models":
            apply_models(svc, foundry=profile["AZURE_FOUNDRY_API_BASE"], embed_model=profile["REFERENCE_EMBED_MODEL"], **who)
        elif argv[1] == "products":
            apply_products(svc, embed_model=profile["REFERENCE_EMBED_MODEL"])
            keys = subscription_keys(svc)
            write_profile_keys(Path(topology.ROOT) / aca.PROFILE_OVERLAY, {f"APIM_{v}": k for v, k in keys.items()})
            print(f"subscription keys written to {aca.PROFILE_OVERLAY}: {', '.join(f'APIM_{v}' for v in keys)}")
        else:
            tgt = aca.target(arm, sub, group, topology.IMAGE)
            apply_bearer(svc, vault_uri=tgt.vault_uri)
            if argv[1] == "mcp":
                apply_mcp(svc, public=tgt.public, **who)
            else:
                apply_frontdoor(svc, frontdoor=tgt.public("workflow-frontdoor") + "/api", **who)
        print(f"apim: {argv[1]} applied to {outputs['gatewayUrl']['value']}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
