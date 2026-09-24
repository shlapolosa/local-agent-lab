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
    python deploy/apim.py apply             # PUT the APIs, operations and policies (idempotent)

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


def models_policy(tenant: str, audience: str) -> str:
    """The API-level policy of the OpenAI-shaped models API."""
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
    return (
        '<policies><inbound><base />'
        # a caller without a subscription must present a production token carrying Models.Use
        '<choose><when condition="' + escape('@(context.Subscription == null)') + '">'
        + _validate_jwt(tenant, audience, MODELS_ROLE, "jwt") +
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


# ------------------------------------------------------------------ apply
def _params(template: str) -> list[dict]:
    return [{"name": p, "type": "string", "required": True} for p in re.findall(r"\{([^}]+)\}", template)]


def apply(arm, service_url: str, *, tenant: str, audience: str, foundry: str, frontdoor: str) -> None:
    """PUT everything. Idempotent: a re-run converges on what this module renders."""
    def put(path, body):
        arm.request("PUT", f"{service_url}/{path}?api-version={APIM_API}", body)

    def policy(path, xml):
        put(f"{path}/policies/policy", {"properties": {"format": "xml", "value": xml}})

    put("backends/foundry", {"properties": {"protocol": "http", "url": foundry.rstrip("/") + "/openai/v1"}})
    put(f"apis/{MODELS_API}", {"properties": {
        "displayName": "Models", "path": "v1", "protocols": ["https"], "subscriptionRequired": False,
        "subscriptionKeyParameterNames": {"header": "api-key", "query": "subscription-key"}}})
    for name, method, url in MODEL_OPERATIONS:
        put(f"apis/{MODELS_API}/operations/{name}",
            {"properties": {"displayName": name, "method": method, "urlTemplate": url}})
    policy(f"apis/{MODELS_API}", models_policy(tenant, audience))
    policy(f"apis/{MODELS_API}/operations/models", models_list_policy())

    put(f"apis/{FRONTDOOR_API}", {"properties": {
        "displayName": "Front door", "path": "api", "protocols": ["https"], "subscriptionRequired": False,
        "serviceUrl": frontdoor}})
    for o in frontdoor_operations():
        put(f"apis/{FRONTDOOR_API}/operations/{o['name']}", {"properties": {
            "displayName": o["name"], "method": o["method"], "urlTemplate": o["urlTemplate"],
            "description": o["description"], "templateParameters": _params(o["urlTemplate"])}})
        policy(f"apis/{FRONTDOOR_API}/operations/{o['name']}",
               frontdoor_operation_policy(o["role"], tenant, audience, stream=o["name"].endswith("-events")))


def main(argv: list[str]) -> int:  # pragma: no cover — composition: reads the profile, calls Azure
    tenant, audience = os.environ.get("ENTRA_TENANT_ID", "<tenant>"), os.environ.get("ENTRA_GATEWAY_AUDIENCE", "<audience>")
    if argv[:1] == ["render"]:
        print(models_policy(tenant, audience))
        for o in frontdoor_operations():
            print(o["method"], o["urlTemplate"], o["role"])
        return 0
    if argv[:1] == ["apply"]:
        sys.path.insert(0, str(Path(__file__).parent))
        import aca
        profile = aca.profile()
        arm = aca.Arm()
        service = (f"{aca.ARM}/subscriptions/{profile['AZURE_SUBSCRIPTION_ID']}/resourceGroups/"
                   f"{profile['AZURE_RESOURCE_GROUP']}/providers/Microsoft.ApiManagement/service/{profile['APIM_NAME']}")
        apply(arm, service, tenant=profile["ENTRA_TENANT_ID"], audience=profile["ENTRA_GATEWAY_AUDIENCE"],
              foundry=profile["AZURE_FOUNDRY_API_BASE"], frontdoor=profile["APIM_FRONTDOOR_URL"])
        print("apim: models + front door applied")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
