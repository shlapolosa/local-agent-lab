"""deploy/azure.py — the production target: the SAME topology rendered as Azure Container Apps.

Pure renderers are tested here directly; the ARM calls go through an injected transport.
The rules that matter most are the ones a wrong render would break SILENTLY:
  * a value that came from the operator's profile is a Key Vault REFERENCE, never a plain value —
    including a coordinate that merely copies one (PG_VECTOR_API_KEY = MCP_SHARED_SECRET);
  * a service is reachable only as the topology says (public / internal / not at all);
  * a workload can scale to zero, and wakes on the stream and group it actually consumes;
  * every app runs the ONE image.
"""
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_azure", os.path.join(ROOT, "deploy", "azure.py"))
az = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(az)
topology = az.topology

SECRET = "s" * 40
PROFILE = {"MCP_SHARED_SECRET": SECRET, "REDIS_URL": "redis://redis:6379/0",
           "DATABASE_URL": "postgresql://labadmin:pw@psql.example:5432/litellm", "LITELLM_MASTER_KEY": "sk-" + "m" * 30,
           "REVIEW_APP_PASSWORD": "p" * 20, "GATEWAY_URL": "http://ignored"}
TARGET = az.Target(subscription="sub-1", resource_group="rg-lab-prod", location="uaenorth",
                   environment_id="/subscriptions/sub-1/resourceGroups/rg-lab-prod/providers/Microsoft.App/managedEnvironments/cae",
                   identity_id="/subscriptions/sub-1/resourceGroups/rg-lab-prod/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id",
                   vault_uri="https://kv-lab-prod.vault.azure.net/", env_domain="icybay.uaenorth.azurecontainerapps.io",
                   image="ghcr.io/shlapolosa/local-agent-lab:sha-abc1234")


def _env(body):
    return {e["name"]: e for e in body["properties"]["template"]["containers"][0]["env"]}


def _secrets(body):
    return {s["name"]: s for s in body["properties"]["configuration"].get("secrets", [])}


# ------------------------------------------------------------------ secrets are references
def test_secret_names_are_the_keys_in_the_form_key_vault_and_container_apps_accept():
    assert az.secret_name("DATABASE_URL") == "database-url"
    assert az.secret_name("A_B2_C") == "a-b2-c"


def test_every_profile_value_is_a_key_vault_reference_and_every_coordinate_is_plain():
    body = az.substrate_app("gateway", topology.SUBSTRATE["gateway"], PROFILE, TARGET)
    env, secrets = _env(body), _secrets(body)
    assert env["DATABASE_URL"] == {"name": "DATABASE_URL", "secretRef": "database-url"}
    assert "value" not in env["LITELLM_MASTER_KEY"]
    assert env["SEMANTIC_MCP_URL"] == {"name": "SEMANTIC_MCP_URL", "value": "http://semantic-mcp/mcp"}
    assert secrets["database-url"] == {"name": "database-url", "identity": TARGET.identity_id,
                                       "keyVaultUrl": "https://kv-lab-prod.vault.azure.net/secrets/database-url"}
    rendered = json.dumps(body)
    for v in (SECRET, PROFILE["DATABASE_URL"], PROFILE["LITELLM_MASTER_KEY"]):
        assert v not in rendered, "a profile secret was rendered as a plain value"


def test_a_coordinate_that_copies_a_secret_references_that_secret_instead_of_repeating_it():
    env = _env(az.substrate_app("gateway", topology.SUBSTRATE["gateway"], PROFILE, TARGET))
    assert env["PG_VECTOR_API_KEY"] == {"name": "PG_VECTOR_API_KEY", "secretRef": "mcp-shared-secret"}


def test_the_secrets_to_publish_are_exactly_the_profile_keys_some_app_references():
    """`secrets sync` writes these to Key Vault. A key no app reads is not published: the vault holds
    what production needs, not a copy of the operator's whole .env."""
    wanted = az.referenced_secrets(PROFILE)
    assert {"MCP_SHARED_SECRET", "DATABASE_URL", "LITELLM_MASTER_KEY", "REVIEW_APP_PASSWORD"} <= set(wanted)
    assert "GATEWAY_URL" not in wanted, "a coordinate the topology computes is never taken from the profile"


# ------------------------------------------------------------------ ingress follows the topology
@pytest.mark.parametrize("name, external, port", [("gateway", True, 4000), ("review", True, 8501),
                                                  ("graph-mcp", True, 9500), ("semantic-mcp", False, 9200),
                                                  ("workflow-frontdoor", False, 9400)])
def test_servers_get_ingress_on_their_port_and_only_the_public_ones_are_external(name, external, port):
    ing = az.substrate_app(name, topology.SUBSTRATE[name], PROFILE, TARGET)["properties"]["configuration"]["ingress"]
    assert (ing["external"], ing["targetPort"]) == (external, port)
    assert ing["allowInsecure"] is (not external), "internal callers use http://<app>; public edge is https only"


def test_a_stream_consumer_has_no_ingress_at_all():
    body = az.substrate_app("continuations", topology.SUBSTRATE["continuations"], PROFILE, TARGET)
    assert "ingress" not in body["properties"]["configuration"]


def test_redis_is_reachable_only_inside_the_environment_over_tcp():
    body = az.redis_app(TARGET)
    ing = body["properties"]["configuration"]["ingress"]
    assert ing == {"external": False, "transport": "tcp", "targetPort": 6379, "exposedPort": 6379}
    assert body["properties"]["template"]["scale"] == {"minReplicas": 1, "maxReplicas": 1}


# ------------------------------------------------------------------ one image, one shape
def test_every_app_runs_the_one_image_through_a_shell():
    """A start command with `&&` or quotes needs a shell; the image's own CMD is never relied on."""
    for name, spec in topology.SUBSTRATE.items():
        c = az.substrate_app(name, spec, PROFILE, TARGET)["properties"]["template"]["containers"][0]
        assert c["image"] == TARGET.image and c["command"] == ["sh", "-c", spec["cmd"]], name


def test_every_app_is_single_revision_on_the_consumption_profile_with_the_apps_identity():
    body = az.substrate_app("semantic-mcp", topology.SUBSTRATE["semantic-mcp"], PROFILE, TARGET)
    p = body["properties"]
    assert p["configuration"]["activeRevisionsMode"] == "Single"
    assert p["workloadProfileName"] == "Consumption" and p["environmentId"] == TARGET.environment_id
    assert body["identity"] == {"type": "UserAssigned", "userAssignedIdentities": {TARGET.identity_id: {}}}


def test_servers_and_substrate_consumers_run_exactly_one_replica():
    for name in ("gateway", "semantic-mcp", "continuations", "fabric-projector"):
        scale = az.substrate_app(name, topology.SUBSTRATE[name], PROFILE, TARGET)["properties"]["template"]["scale"]
        assert scale == {"minReplicas": 1, "maxReplicas": 1}, name


# ------------------------------------------------------------------ workloads
def test_a_workload_reaches_the_substrate_only_through_the_gateway_and_holds_no_store_credential():
    body = az.workload_app("visio", topology.WORKLOADS["visio"], PROFILE, TARGET)
    env = _env(body)
    assert env["GATEWAY_URL"] == {"name": "GATEWAY_URL", "value": "http://gateway"}
    assert not {"DATABASE_URL", "LITELLM_MASTER_KEY", "MCP_SHARED_SECRET"} & set(env)
    assert "ingress" not in body["properties"]["configuration"]


def test_a_workload_scales_to_zero_and_wakes_on_its_own_group_of_the_request_stream():
    spec = topology.WORKLOADS["usecase-screening"]
    scale = az.workload_app("usecase-screening", spec, PROFILE, TARGET)["properties"]["template"]["scale"]
    assert scale["minReplicas"] == 0
    rules = [r["custom"] for r in scale["rules"]]
    assert rules and all(r["type"] == "redis-streams" for r in rules)
    for r in rules:
        assert r["metadata"]["stream"] == topology.REQUEST_STREAM
        assert r["metadata"]["consumerGroup"] == spec["service"]
        assert r["metadata"]["address"] == "redis:6379"
    keys = {k for r in rules for k in r["metadata"]}
    assert "lagCount" in keys, "without a lag rule a host at zero never sees NEW work"
    assert "pendingEntriesCount" in keys, "without a pending rule a host scales in under a run it is still doing"


def test_replicas_become_max_replicas_of_one_app_not_separate_apps():
    """Railway needs one SERVICE per replica; Container Apps scales one app. Every replica shares the
    consumer group — each entry still goes to exactly one of them."""
    scale = az.workload_app("meeting", topology.WORKLOADS["meeting"], PROFILE, TARGET)["properties"]["template"]["scale"]
    assert scale["maxReplicas"] >= topology.WORKLOADS["meeting"]["replicas"]


def test_every_long_lived_workload_and_every_substrate_role_renders():
    for name, spec in topology.WORKLOADS.items():
        if spec.get("restart") == "ALWAYS":
            assert az.workload_app(name, spec, PROFILE, TARGET)["properties"]["template"]["containers"]
    for name, spec in topology.SUBSTRATE.items():
        assert az.substrate_app(name, spec, PROFILE, TARGET)


def test_each_replica_consumes_under_its_own_name():
    """Two consumers sharing a name share a pending list, and XAUTOCLAIM can no longer tell whose
    in-flight work is whose. Railway gives each replica its own service and WF_CONSUMER; here the
    replicas of one app share an environment, so the name comes from the replica itself."""
    c = az.workload_app("meeting", topology.WORKLOADS["meeting"], PROFILE, TARGET)["properties"]["template"]["containers"][0]
    assert "WF_CONSUMER" not in {e["name"] for e in c["env"]}
    assert c["command"][:2] == ["sh", "-c"]
    assert c["command"][2].startswith('WF_CONSUMER="$CONTAINER_APP_REPLICA_NAME" exec ')
    assert c["command"][2].endswith(topology.WORKLOADS["meeting"]["cmd"])
