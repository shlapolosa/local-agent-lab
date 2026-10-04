"""deploy/apim.py — production's gateway rendered from what the lab already declares.

Nothing about APIM is written twice: the model aliases come from the production model overlay (the file
that already says which Foundry deployment serves each gateway name), the /api operations and their app
roles from lab.substrate.apipolicy. These tests pin the rules a wrong render would break silently:
  * every gateway name production serves resolves to a Foundry deployment, reasoning effort included;
  * every /api operation exists in APIM with exactly its role, and nothing else is reachable;
  * a caller is admitted by a valid token for the PROD audience, or by a subscription — never unchecked.
"""
import importlib.util
import os
import re
import xml.etree.ElementTree as ET


from lab.substrate import apipolicy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_apim", os.path.join(ROOT, "deploy", "apim.py"))
apim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apim)

TENANT, AUD = "b911f4d4-de30-405f-96e9-bb1c773fe2ff", "api://80baf376-3c49-49b9-a879-f8fd250d9594"


# ------------------------------------------------------------------ model aliases
def test_every_gateway_model_name_resolves_to_a_foundry_deployment():
    aliases = apim.model_aliases()
    assert aliases["kimi-k3"]["deployment"] == "gpt-5-mini" and "reasoning_effort" not in aliases["kimi-k3"]
    assert aliases["gpt-5.4-mini-think"]["deployment"] == "gpt-5-mini"
    assert aliases["gpt-5.4-mini-think"]["reasoning_effort"] == "medium"
    assert aliases["text-embedding-3-large"] == {"deployment": "text-embedding-3-large"}
    assert "nomic-embed-text" not in aliases, "a name the overlay drops is not served"


def test_the_model_policy_maps_names_in_the_request_body_and_calls_foundry_as_itself():
    xml = apim.models_policy(TENANT, AUD)
    ET.fromstring(xml)                                                   # well-formed
    assert "authentication-managed-identity" in xml and "cognitiveservices.azure.com" in xml
    code = "".join(ET.fromstring(xml).itertext())                        # the expressions, as APIM compiles them
    assert all(f'\\"{n}\\"' in code for n in apim.model_aliases()), "the alias map is rendered from the overlay"
    assert "input_type" in xml, "the non-OpenAI embedding field is removed before Foundry sees it"
    assert "llm-token-limit" in xml and "llm-emit-token-metric" in xml


def test_reasoning_effort_reaches_the_responses_api_in_its_own_shape():
    # Production, 25 Sep 2026: every screening run died at its first model call with Foundry's 400
    # "Unsupported parameter: 'reasoning_effort' … moved to 'reasoning.effort'". The alias
    # gpt-5.4-mini-think carries an effort; the policy chose the shape from `context.Request.Url`,
    # which by then named the BACKEND, so a Responses call got the Chat Completions field.
    code = _code(apim.models_policy(TENANT, AUD))
    assert 'context.Request.OriginalUrl.Path.EndsWith("/responses")' in code, \
        "the caller's URL decides the shape, not the backend the request was re-pointed at"
    assert "context.Request.Url.Path" not in code
    # a caller's own reasoning_effort is moved too — LiteLLM did that translation, so callers rely on it
    assert 'body.Remove("reasoning_effort")' in code


def test_a_parameter_the_model_refuses_is_dropped_as_litellm_did():
    # Production, 4 Oct 2026, the next failure after reasoning_effort: Foundry's gpt-5-mini refuses
    # `temperature` ("not supported with this model") and the Responses API has no `seed` — both sent
    # by the use-case agents for determinism. LiteLLM's drop_params removed them silently.
    aliases = apim.model_aliases()
    assert "temperature" in aliases["gpt-5.4-mini-think"]["drop"], \
        "a model's refusals are declared on the model, in the overlay (LiteLLM's additional_drop_params)"
    assert "temperature" in aliases["kimi-k3"]["drop"]
    assert "drop" not in aliases["text-embedding-3-large"], "an embedding deployment declares none"
    code = _code(apim.models_policy(TENANT, AUD))
    assert 'target["drop"]' in code
    assert 'if (responses) { body.Remove("seed"); }' in code, "the Responses API has no seed, on any model"


def test_max_tokens_is_renamed_to_what_each_api_calls_it():
    # Foundry refuses `max_tokens` on both APIs (measured 4 Oct 2026); the fabric's agents send
    # max_tokens=16000. LiteLLM translated it — the Responses API calls it max_output_tokens, Chat
    # Completions max_completion_tokens — and a caller's explicit new-style value is never overwritten.
    code = _code(apim.models_policy(TENANT, AUD))
    assert 'responses ? "max_output_tokens" : "max_completion_tokens"' in code
    assert 'body.Remove("max_tokens")' in code


def _code(xml):
    """Every policy expression, decoded as APIM compiles it: attribute values and element text."""
    root = ET.fromstring(xml)
    return " ".join([v for e in root.iter() for v in e.attrib.values()] + list(root.itertext()))


def test_pii_uses_the_guardrails_own_patterns_and_masks_before_the_model_sees_anything():
    """The same library pii_guardrail reads, not a copy: a pattern added there is masked here."""
    from lab.substrate.gateway import pii_guardrail
    code = _code(apim.models_policy(TENANT, AUD))
    for name, rx in pii_guardrail.load_patterns(pii_guardrail.DEFAULT_PATTERNS):
        assert f'"{name.upper()}"' in code and apim._cs_str(rx.pattern) in code, name
    for slot in ('"messages"', '"instructions"', '"input"', '"output"', '"text"'):
        assert slot in code, f"{slot}: every text slot walk_request_texts walks"
    xml = apim.models_policy(TENANT, AUD)
    assert xml.index("pii-mask") > xml.index("gateway does not serve"), "masking follows the alias rewrite"


def test_restoring_json_escapes_the_original_and_leaves_a_stream_alone():
    code = _code(apim.models_policy(TENANT, AUD))
    assert 'Replace("\\"", "\\\\\\"")' in code, "an original with a quote must not break the response JSON"
    assert "JsonConvert" not in code, "not an allowed member in an APIM expression (measured on apply)"
    assert '"stream"' in code


def test_a_caller_is_admitted_by_a_prod_token_or_a_subscription_never_unchecked():
    xml = apim.models_policy(TENANT, AUD)
    assert AUD in xml and TENANT in xml
    assert "context.Subscription" in xml, "a subscription (the virtual key's analogue) is the other way in"
    assert "Models.Use" in xml


# ------------------------------------------------------------------ the /api front door
def test_every_api_operation_is_rendered_with_its_own_role():
    ops = apim.frontdoor_operations()
    assert {(o["method"], o["role"]) for o in ops} == {(op.method, op.role) for op in apipolicy.OPERATIONS}
    assert len(ops) == len(apipolicy.OPERATIONS)


def test_an_operation_template_matches_exactly_what_the_role_table_matches():
    """A template looser than the table's pattern would let one operation carry another's role."""
    for o in apim.frontdoor_operations():
        concrete = re.sub(r"\{[^}]+\}", "x1", o["urlTemplate"])
        assert apipolicy.role_for(o["method"], "/api" + concrete) == o["role"], o["urlTemplate"]


def test_each_operation_policy_requires_its_role_on_the_prod_audience():
    for o in apim.frontdoor_operations():
        xml = apim.frontdoor_operation_policy(o["role"], TENANT, AUD)
        ET.fromstring(xml)
        assert f"<value>{o['role']}</value>" in xml and AUD in xml
        assert "{{mcp-shared-secret}}" in xml, "the front door sees the substrate's bearer, never the caller's"


def test_operation_ids_are_valid_apim_names():
    for o in apim.frontdoor_operations():
        assert re.fullmatch(r"[A-Za-z0-9-]+", o["name"]), o["name"]


# ------------------------------------------------------------------ MCP servers
def test_every_gateway_mcp_alias_has_a_service_behind_it():
    servers = apim.mcp_servers()
    assert servers["collab_mcp"] == "graph-mcp" and servers["ea_mcp"] == "adoit-mcp"
    assert set(servers.values()) <= set(apim.topology.SERVICE_PORTS)


def test_the_topologys_mcp_servers_are_exactly_the_dev_gateways():
    """PARITY, both directions: production's gateway and development's must front the same servers under
    the same aliases, read from the same URL variables — drift either way is the defect."""
    import yaml
    config = yaml.safe_load(open(apim.BASE_CONFIG))["mcp_servers"]
    dev = {alias: str(spec["url"]).removeprefix("os.environ/") for alias, spec in config.items()}
    assert dev == {alias: key for alias, (key, _svc) in apim.topology.MCP_SERVERS.items()}


def test_every_granted_server_is_one_the_gateway_serves():
    served = set(apim.mcp_servers())
    for team, tools in apim.grants.TEAMS.items():
        assert set(tools) <= served, team


def test_a_team_reaches_only_what_its_grant_names():
    g = apim.mcp_grants("workflow_mcp")
    assert "approvals_decide" in g["usecase-submitter"]
    assert "approvals_decide" not in g["usecase-intake"], "a workload's own agents never answer an approval"
    assert apim.mcp_grants("ea_mcp")["visio-conversion"] == "*", "a whole-server grant stays whole"
    assert "visio-conversion" not in apim.mcp_grants("workflow_mcp")


def test_the_mcp_policy_checks_the_tool_and_hands_the_backend_only_the_substrate_bearer():
    xml = apim.mcp_policy("workflow_mcp", TENANT, AUD)
    code = " ".join(v for e in ET.fromstring(xml).iter() for v in e.attrib.values())   # expressions, decoded
    assert "tools/call" in code and '\\"usecase-submitter\\"' in code
    assert "Grant." in code, "a token's teams are its Grant.<team> roles"
    assert "context.Product" in code, "a subscription's team is its product"
    assert "{{mcp-shared-secret}}" in xml and 'buffer-response="false"' in xml
    assert AUD in xml


def _expressions(xml: str) -> str:
    return " ".join(v for e in ET.fromstring(xml).iter() for v in e.attrib.values()) + \
        " ".join(e.text or "" for e in ET.fromstring(xml).iter())


def test_a_listing_shows_a_caller_only_the_tools_its_grant_names():
    # LiteLLM listed only granted tools; APIM forwards the server's own listing. A Copilot agent chooses
    # from the listing, so an ungranted tool in it is a 403 waiting to happen in front of a person.
    xml = apim.mcp_policy("workflow_mcp", TENANT, AUD)
    code = _expressions(xml)
    assert "tools/list" in code and "mcp-visible" in code
    assert '\\"approvals_decide\\"' in code, "the visible set is rendered from the same grants the call check reads"
    root = ET.fromstring(xml)
    # only a filtered listing is buffered: everything else keeps streaming
    forwards = root.findall(".//backend//forward-request")
    assert {f.get("buffer-response") for f in forwards} == {"true", "false"}
    buffered = root.find(".//backend/choose/when")
    assert "mcp-visible" in buffered.get("condition") and buffered.find("forward-request").get("buffer-response") == "true"
    rewrite = root.find(".//outbound/choose/when")
    assert "mcp-visible" in rewrite.get("condition") and rewrite.find("set-body") is not None


def test_a_whole_server_grant_is_never_filtered():
    root = ET.fromstring(apim.mcp_policy("ea_mcp", TENANT, AUD))
    visible = next(e.get("value") for e in root.iter("set-variable") if e.get("name") == "mcp-visible")
    assert '\\"visio-conversion\\": \\"*\\"' in visible
    assert 'if (g.Type == JTokenType.String) { return ""; }' in visible, \
        "a team holding the whole server sees the whole listing"


class Recorder:
    def __init__(self):
        self.puts = {}

    def put(self, path, body):
        self.puts[path] = body

    def policy(self, path, xml):
        self.puts[f"{path}/policies/policy"] = xml


def test_the_bearer_is_a_key_vault_reference_that_follows_rotation():
    svc = Recorder()
    apim.apply_bearer(svc, vault_uri="https://kv.vault.azure.net/")
    nv = svc.puts["namedValues/mcp-shared-secret"]["properties"]
    assert nv["secret"] is True and nv["keyVault"]["secretIdentifier"] == "https://kv.vault.azure.net/secrets/mcp-shared-secret"
    assert "value" not in nv, "the gateway holds a reference, never the secret itself"


def test_each_mcp_server_is_its_own_api_at_the_path_the_client_aggregates():
    svc = Recorder()
    apim.apply_mcp(svc, tenant=TENANT, audience=AUD, public=lambda s: f"https://{s}.env.example")
    api = svc.puts["apis/mcp-semantic-mcp"]["properties"]
    assert api["path"] == "mcp/semantic_mcp" and api["serviceUrl"] == "https://semantic-mcp.env.example"
    assert {svc.puts[f"apis/mcp-semantic-mcp/operations/{m.lower()}"]["properties"]["method"]
            for m in ("POST", "GET", "DELETE")} == {"POST", "GET", "DELETE"}
    assert all(f"apis/mcp-{a.replace('_', '-')}" in svc.puts for a in apim.mcp_servers())
    assert api["subscriptionKeyParameterNames"]["header"] == "api-key", "one key header on every API"


# ------------------------------------------------------------------ key callers: products + subscriptions
def test_a_key_team_product_holds_exactly_its_granted_servers_and_models_only_if_it_calls_them():
    # DERIVED from the gateway's own grant table, not pinned: a team's servers grow (the curator gained
    # workflow-mcp when it began asking a steward about the vocabulary), and a pinned set makes every such
    # change look like a defect while catching nothing. What must hold is that APIM and the gateway agree.
    for team in ("fabric-curator", "fabric-intake", "fabric-bot"):
        assert set(apim.product_apis(team, ())) == {apim._api_id(s) for s in apim.grants.TEAMS[team]}, team
    assert {"mcp-collab-mcp", "mcp-semantic-mcp"} <= set(apim.product_apis("fabric-curator", ()))
    assert "models" not in apim.product_apis("usecase-submitter", ()), "a submit-only identity calls no model"
    assert apim.product_apis("reference-corpus", ("text-embedding-3-large",)) == ["models"], "zero tools"


def test_every_key_caller_has_a_team_the_gateway_can_serve():
    for var, team in apim.grants.KEY_CALLERS.items():
        assert team in apim.grants.TEAMS or team in apim.grants.KEY_MODELS or team == "reference-corpus", var


def test_a_key_team_may_call_only_its_models_and_a_team_with_none_calls_nothing():
    """Enforced in the models API's OWN policy, keyed by the subscription's product. Measured 24 Sep 2026:
    with subscriptionRequired=false a valid key of a product WITHOUT the models API was still admitted,
    and a product policy did not refuse — so neither may be what holds the line."""
    keyed = apim.key_models("text-embedding-3-large")
    assert keyed["reference-corpus"] == ["text-embedding-3-large"]
    assert "fabric-curator" not in keyed, "a team that calls no model is absent, and absent is refused"
    xml = apim.models_policy(TENANT, AUD, keyed)
    code = " ".join(v for e in ET.fromstring(xml).iter() for v in e.attrib.values())
    assert "context.Product" in code and '\\"reference-corpus\\"' in code
    assert "this key may not call" in xml


def test_subscriptions_are_one_per_key_caller_scoped_to_its_team_product():
    svc = Recorder()
    apim.apply_products(svc, embed_model="text-embedding-3-large")
    sub = svc.puts["subscriptions/fabric-curator-key"]["properties"]
    assert sub["scope"] == "/products/fabric-curator" and sub["state"] == "active"
    assert svc.puts["products/reference-corpus"]["properties"]["subscriptionRequired"] is True
    assert "products/fabric-curator/apis/mcp-collab-mcp" in svc.puts


def test_keys_land_in_the_profile_replacing_a_line_or_appending_one(tmp_path):
    p = tmp_path / ".env.azure"
    p.write_text("A=1\nAPIM_X=old\n# keep\n")
    apim.write_profile_keys(p, {"APIM_X": "new", "APIM_Y": "y"})
    assert p.read_text() == "A=1\nAPIM_X=new\n# keep\nAPIM_Y=y\n"
