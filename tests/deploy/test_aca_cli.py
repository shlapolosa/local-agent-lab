"""deploy/aca.py commands against a RECORDING fake of Azure Resource Manager and Key Vault.

What each command must do, and what it must never do:
  * the target comes from the foundation deployment's outputs, not from constants;
  * `secrets sync` publishes exactly the referenced profile keys and never prints a value;
  * `substrate up` creates Redis first, then every role — and runs the quiet gate before touching them;
  * `release` changes ONLY the image of apps running this repo's image, keeping each app's env;
  * `images` reports a mismatch of this repo's image and ignores third-party ones.
"""
import copy
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_azure_cli", os.path.join(ROOT, "deploy", "aca.py"))
az = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(az)

SUB, RG = "sub-1", "rg-lab-prod"
BASE = f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}"
OURS = "ghcr.io/shlapolosa/local-agent-lab"
OUTPUTS = {"environmentId": {"value": "/env/cae"}, "appsIdentityId": {"value": "/id/apps"},
           "vaultUri": {"value": "https://kv.vault.azure.net/"},
           "environmentDomain": {"value": "icybay.uaenorth.azurecontainerapps.io"}}


class FakeArm:
    def __init__(self, apps=None):
        self.calls, self.apps, self.vault = [], dict(apps or {}), {}

    def request(self, method, url, body=None):
        self.calls.append((method, url, copy.deepcopy(body)))
        if url.startswith(f"{BASE}/providers/Microsoft.Resources/deployments/foundation"):
            return {"properties": {"outputs": OUTPUTS}}
        if url.startswith(f"{BASE}?"):
            return {"location": "uaenorth"}
        if "/secrets/" in url:
            name = url.split("/secrets/")[1].split("?")[0]
            if method == "GET":
                return {"value": self.vault.get(name, "")}
            self.vault[name] = body["value"]
            return {}
        if url.startswith(f"{BASE}/providers/Microsoft.App/containerApps?"):
            return {"value": [{"name": n, **a} for n, a in self.apps.items()]}
        if "/containerApps/" in url:
            name = url.split("/containerApps/")[1].split("?")[0]
            if method == "PUT":
                self.apps[name] = copy.deepcopy(body)
            elif method == "PATCH":
                self.apps[name]["properties"]["template"] = copy.deepcopy(body["properties"]["template"])
            app = self.apps[name]
            return {"name": name, **app, "properties": {**app["properties"], "provisioningState": "Succeeded",
                                                        "runningStatus": "Running"}}
        raise AssertionError(f"unexpected {method} {url}")


def _app(image, env=None):
    return {"properties": {"template": {"containers": [{"name": "c", "image": image, "env": env or []}]}}}


def _target(fake):
    return az.target(fake, SUB, RG, f"{OURS}:sha-abc1234")


def test_the_target_is_read_from_the_foundation_deployment():
    t = _target(FakeArm())
    assert (t.environment_id, t.identity_id, t.vault_uri, t.location) == ("/env/cae", "/id/apps",
                                                                       "https://kv.vault.azure.net/", "uaenorth")
    assert t.gateway_public == "https://gateway.icybay.uaenorth.azurecontainerapps.io"


def test_secrets_sync_publishes_the_referenced_keys_and_prints_no_value(capsys):
    fake = FakeArm()
    profile = {"MCP_SHARED_SECRET": "x" * 40, "DATABASE_URL": "postgresql://u:pw@h/litellm", "UNUSED_THING": "nope"}
    az.secrets_sync(fake, profile, _target(fake))
    assert fake.vault["mcp-shared-secret"] == "x" * 40 and "database-url" in fake.vault
    assert "unused-thing" not in fake.vault, "the vault holds what production reads, not the whole .env"
    out = capsys.readouterr().out
    assert "x" * 40 not in out and "pw@" not in out and "database-url" in out


def test_substrate_up_gates_then_creates_redis_before_every_role(monkeypatch):
    fake, order = FakeArm(), []
    monkeypatch.setattr(az, "_require_quiet", lambda profile: order.append("gate"))
    profile = {"MCP_SHARED_SECRET": "x" * 40}
    az.substrate_up(fake, profile, _target(fake))
    puts = [u.split("/containerApps/")[1].split("?")[0] for m, u, _ in fake.calls if m == "PUT" and "/containerApps/" in u]
    assert order == ["gate"]
    assert puts[0] == "redis" and "gateway" in puts and "semantic-mcp" in puts
    assert set(puts) >= set(az.topology.SUBSTRATE)


def test_release_changes_only_the_image_and_only_of_this_repos_apps(monkeypatch):
    monkeypatch.setattr(az, "_require_quiet", lambda profile: None)
    env = [{"name": "DATABASE_URL", "secretRef": "database-url"}]
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-old0000", env), "redis": _app("redis:7-alpine")})
    bad = az.release(fake, _target(fake), wait_s=0)
    assert not bad
    gw = fake.apps["gateway"]["properties"]["template"]["containers"][0]
    assert gw["image"] == f"{OURS}:sha-abc1234" and gw["env"] == env, "release must keep the app's env"
    assert fake.apps["redis"]["properties"]["template"]["containers"][0]["image"] == "redis:7-alpine"
    assert not [c for c in fake.calls if c[0] == "PUT"], "release creates nothing and writes no configuration"


def test_images_reports_a_mismatch_of_this_repos_image_only(capsys):
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-aaa"), "review": _app(f"{OURS}:sha-bbb"),
                    "redis": _app("redis:7-alpine")})
    assert az.image_report(fake, _target(fake)) is True
    assert "MISMATCH" in capsys.readouterr().out
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-aaa"), "redis": _app("redis:7-alpine")})
    assert az.image_report(fake, _target(fake)) is False


def test_release_asks_the_gate_with_the_master_key_read_from_the_vault(monkeypatch):
    """CD holds no production secret: the one key the quiet gate needs is read from Key Vault by the
    deploy identity, which may read that secret and no other."""
    seen = {}
    monkeypatch.delenv("LAB_GATE_KEY", raising=False)
    monkeypatch.setattr(az, "_require_quiet", lambda profile: seen.update(profile))
    fake = FakeArm()
    fake.vault["litellm-master-key"] = "sk-prod-master"
    orig = fake.request
    def request(method, url, body=None):
        if method == "GET" and "/secrets/litellm-master-key" in url:
            return {"value": fake.vault["litellm-master-key"]}
        return orig(method, url, body)
    fake.request = request
    az.release(fake, _target(fake), wait_s=0)
    assert seen == {"PUBLIC_GATEWAY_URL": "https://gateway.icybay.uaenorth.azurecontainerapps.io",
                    "LITELLM_MASTER_KEY": "sk-prod-master"}


def test_release_proceeds_unasked_when_the_vault_will_not_say(monkeypatch):
    seen = {}
    monkeypatch.delenv("LAB_GATE_KEY", raising=False)
    monkeypatch.setattr(az, "_require_quiet", lambda profile: seen.update(profile))
    fake = FakeArm()
    orig = fake.request
    def request(method, url, body=None):
        if method == "GET" and "/secrets/" in url:
            raise SystemExit("azure GET -> 403")
        return orig(method, url, body)
    fake.request = request
    az.release(fake, _target(fake), wait_s=0)
    assert seen["LITELLM_MASTER_KEY"] == "", "no key: the gate reports it cannot ask, and the release goes on"
