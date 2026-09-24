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
    assert aliases["kimi-k3"] == {"deployment": "gpt-5-mini"}
    assert aliases["gpt-5.4-mini-think"] == {"deployment": "gpt-5-mini", "reasoning_effort": "medium"}
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
