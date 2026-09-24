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

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_azure_cli", os.path.join(ROOT, "deploy", "aca.py"))
az = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(az)

SUB, RG = "sub-1", "rg-lab-prod"
BASE = f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}"
OURS = "ghcr.io/shlapolosa/local-agent-lab"
OUTPUTS = {"environmentId": {"value": "/env/cae"}, "appsIdentityId": {"value": "/id/apps"},
           "vaultUri": {"value": "https://kv.vault.azure.net/"},
           "environmentDomain": {"value": "icybay.uaenorth.azurecontainerapps.io"},
           "appInsightsConnectionString": {"value": "InstrumentationKey=00000000-0000-0000-0000-000000000000"},
           "logsWorkspaceId": {"value": "ws-1"}}


@pytest.fixture(autouse=True)
def _registry_has_every_image(monkeypatch):
    """Offline: the registry is asked for real only in production. A test that wants a MISSING image
    overrides this with its own monkeypatch."""
    monkeypatch.setattr(az, "image_exists", lambda image: True)


class FakeArm:
    def __init__(self, apps=None):
        self.calls, self.apps, self.vault = [], {}, {}
        self.revisions, self.unready = {}, set()
        for n, a in (apps or {}).items():
            self.apps[n] = copy.deepcopy(a)
            self._revise(n)

    revisions: dict = {}
    unready: set = set()                     # apps whose newest revision never becomes ready

    def _revise(self, name):
        n = len([r for r in self.revisions if r.startswith(name + "--")]) + 1
        rev = f"{name}--r{n}"
        self.revisions[rev] = copy.deepcopy(self.apps[name]["properties"]["template"])
        p = self.apps[name]["properties"]
        p["latestRevisionName"] = rev
        if name not in self.unready:
            p["latestReadyRevisionName"] = rev

    def _view(self, name):
        app = self.apps[name]
        return {"name": name, **app, "properties": {**app["properties"], "provisioningState": "Succeeded",
                                                    "runningStatus": "Running"}}

    def request(self, method, url, body=None, missing_ok=False):
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
            return {"value": [self._view(n) for n in self.apps]}
        if "/revisions/" in url:
            name, rev = url.split("/containerApps/")[1].split("/revisions/")
            return {"properties": {"template": copy.deepcopy(self.revisions[rev.split("?")[0]])}}
        if "/containerApps/" in url:
            name = url.split("/containerApps/")[1].split("?")[0]
            if method == "GET" and name not in self.apps:
                return None                                   # Arm.request(..., missing_ok=True)
            if method == "PUT":
                self.apps[name] = copy.deepcopy(body)
            elif method == "PATCH":
                self.apps[name]["properties"]["template"] = copy.deepcopy(body["properties"]["template"])
            if method in ("PUT", "PATCH"):
                self._revise(name)
            return self._view(name)
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
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-abc1234"), "redis": _app("redis:7-alpine")})
    assert az.image_report(fake, _target(fake)) is False, "third-party images are never a mismatch"


# ------------------------------------------------------------------ review fixes (F3, F7, F8, F9, F14)
def test_release_fails_when_a_new_revision_never_becomes_ready(monkeypatch):
    """provisioningState=Succeeded says the ARM write landed, not that the new build serves: in Single
    mode the old revision keeps serving and the template alone would say the release worked."""
    monkeypatch.setattr(az, "_require_quiet", lambda profile: None)
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-old0000")})
    fake.unready.add("gateway")
    assert az.release(fake, _target(fake), wait_s=0) is True


def test_release_waits_for_the_revision_its_update_created_not_the_one_before_it(monkeypatch):
    """Measured on production CD, 24 Sep 2026: read straight after the update, an app still names its
    OLD revision as both latest and ready, so `release` reported `serving <old revision>` — success
    before the new revision existed. Released means a revision NEWER than the pre-update one is ready."""
    monkeypatch.setattr(az, "_require_quiet", lambda profile: None)
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-old0000")})
    lagging = {"n": 0}
    orig_revise = fake._revise

    def slow_revise(name):                      # the new revision appears only on a LATER read
        lagging["pending"] = name
    fake._revise = slow_revise
    orig_request = fake.request

    def request(method, url, body=None, missing_ok=False):
        out = orig_request(method, url, body, missing_ok)
        if method == "GET" and "/containerApps/gateway?" in url and lagging.get("pending"):
            lagging["n"] += 1
            if lagging["n"] == 2:
                orig_revise(lagging.pop("pending"))
                out = orig_request(method, url, body, missing_ok)
        return out
    fake.request = request
    monkeypatch.setattr(az.time, "sleep", lambda s: None)
    assert az.release(fake, _target(fake), wait_s=60) is False
    assert lagging["n"] >= 2, "it read again instead of accepting the pre-update revision"


def test_release_with_nothing_to_roll_is_a_failure(monkeypatch):
    """A wrong resource group or a renamed image ships nothing — that must not go green."""
    monkeypatch.setattr(az, "_require_quiet", lambda profile: None)
    fake = FakeArm({"redis": _app("redis:7-alpine")})
    assert az.release(fake, _target(fake), wait_s=0) is True


def test_release_asks_the_gate_with_the_bearer_it_is_given(monkeypatch):
    seen = {}
    monkeypatch.setattr(az, "_require_quiet", lambda profile: seen.update(profile))
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-old0000")})
    az.release(fake, _target(fake), wait_s=0, bearer="eyJ.t.s")
    assert seen == {"PUBLIC_GATEWAY_URL": "https://gateway.icybay.uaenorth.azurecontainerapps.io",
                    "GATE_BEARER": "eyJ.t.s"}


def test_images_compares_what_each_app_SERVES_with_the_release(capsys):
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-abc1234"), "review": _app(f"{OURS}:sha-abc1234")})
    assert az.image_report(fake, _target(fake)) is False
    fake.unready.add("review")
    fake.apps["review"]["properties"]["template"]["containers"][0]["image"] = f"{OURS}:sha-new9999"
    fake._revise("review")
    assert az.image_report(fake, _target(fake)) is False, "the template moved but the old revision serves"
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-old0000")})
    assert az.image_report(fake, _target(fake)) is True, "serving an image that is not this release"


def test_substrate_up_publishes_secrets_first_and_keeps_an_existing_apps_image(monkeypatch):
    """Configuration is not a code release: `substrate up` must not roll an app onto the operator's
    local HEAD, which no reviewer approved."""
    monkeypatch.setattr(az, "_require_quiet", lambda profile: None)
    fake = FakeArm({"gateway": _app(f"{OURS}:sha-approved")})
    order = []
    orig = az.secrets_sync
    monkeypatch.setattr(az, "secrets_sync", lambda arm, prof, tgt: (order.append("sync"), orig(arm, prof, tgt)))
    az.substrate_up(fake, {"MCP_SHARED_SECRET": "x" * 40}, _target(fake))
    assert order == ["sync"] and fake.calls.index(next(c for c in fake.calls if c[0] == "PUT")) > 0
    assert fake.apps["gateway"]["properties"]["template"]["containers"][0]["image"] == f"{OURS}:sha-approved"
    assert fake.apps["semantic-mcp"]["properties"]["template"]["containers"][0]["image"] == f"{OURS}:sha-abc1234"


def test_the_cli_answers_an_unknown_command_with_its_usage():
    import subprocess, sys
    out = subprocess.run([sys.executable, os.path.join(ROOT, "deploy", "aca.py"), "substrate", "nonsense"],
                         capture_output=True, text=True, env={**os.environ, "AZURE_SUBSCRIPTION_ID": ""})
    assert out.returncode != 0 and "Traceback" not in out.stderr and "usage" in (out.stderr + out.stdout).lower()


def test_versions_reads_the_build_each_app_says_it_runs(capsys):
    rows = [{"ContainerAppName_s": "gateway", "Log_s": "consumer ready  build=abc1234def"},
            {"ContainerAppName_s": "review", "Log_s": "x build=0000000aaa"}]
    assert az.version_report(rows, "sha-abc1234") is True
    out = capsys.readouterr().out
    assert "review" in out and "MISMATCH" in out
    assert az.version_report(rows[:1], "sha-abc1234") is False


def test_a_server_gets_a_startup_probe_patient_enough_for_the_gateways_boot():
    """Measured 24 Sep 2026: with no probes declared, Container Apps probed the gateway's port every
    second and killed it (exit 137) 17 s in — LiteLLM takes about a minute to come up — so it
    restart-looped for ever while `status` said Running. Every app with ingress declares its own."""
    t = _target(FakeArm())
    for name in ("gateway", "semantic-mcp", "review"):
        c = az.substrate_app(name, az.topology.SUBSTRATE[name], {}, t)["properties"]["template"]["containers"][0]
        probes = {p["type"]: p for p in c["probes"]}
        port = az.topology.SERVICE_PORTS[name]
        assert probes["Startup"]["tcpSocket"]["port"] == port
        assert probes["Startup"]["periodSeconds"] * probes["Startup"]["failureThreshold"] >= 300
        assert probes["Liveness"]["tcpSocket"]["port"] == port
    consumer = az.substrate_app("continuations", az.topology.SUBSTRATE["continuations"], {}, t)
    assert "probes" not in consumer["properties"]["template"]["containers"][0], "nothing to probe without a port"


def test_the_gateway_has_room_for_its_measured_peak():
    """Measured 24 Sep 2026: the dev gateway peaks at 2.52 GB (Railway metrics, 1,442 samples), and the
    first production gateway at 2 GiB was killed 16 s into every boot (exit 137) — a restart loop."""
    res = az.RESOURCES["gateway"]
    gib = float(res["memory"].removesuffix("Gi"))
    assert gib * 1024**3 / 1e9 >= 2.52 * 1.2, "at least 20 % above the measured peak"
    assert res["cpu"] * 2 == gib, "Consumption sizes pair 0.5 vCPU with 1 GiB"


def test_a_new_app_is_never_created_on_an_image_the_registry_does_not_have(monkeypatch):
    """Measured 24 Sep 2026: nine workloads were created on the local HEAD's tag — a commit not yet
    pushed, so an image that did not exist. Refused before anything is written, naming the tag."""
    monkeypatch.setattr(az, "image_exists", lambda image: False)
    fake = FakeArm()
    with pytest.raises(SystemExit, match="sha-abc1234"):
        az.workload_up(fake, "visio", {"MCP_SHARED_SECRET": "x" * 40}, _target(fake))
    assert not [c for c in fake.calls if c[0] == "PUT"]


def test_an_existing_app_keeps_its_image_so_the_registry_is_not_asked(monkeypatch):
    asked = []
    monkeypatch.setattr(az, "image_exists", lambda image: asked.append(image) or False)
    fake = FakeArm({"wf-visio": _app(f"{OURS}:sha-approved")})
    az.workload_up(fake, "visio", {"MCP_SHARED_SECRET": "x" * 40}, _target(fake))
    assert asked == [] and _image_of(fake, "wf-visio") == f"{OURS}:sha-approved"


def _image_of(fake, name):
    return fake.apps[name]["properties"]["template"]["containers"][0]["image"]


def test_listing_follows_every_page():
    """Measured 24 Sep 2026: ARM returns container apps 20 to a page, and a `release` that read only
    the first page skipped all nine workloads — green, with a third of production on another image."""
    class Paged:
        def request(self, method, url, body=None, missing_ok=False):
            if "page=2" in url:
                return {"value": [{"name": "wf-visio"}]}
            return {"value": [{"name": f"app-{i}"} for i in range(20)], "nextLink": "https://management.azure.com/x?page=2"}
    names = [a["name"] for a in az._list(Paged(), _target(FakeArm()))]
    assert len(names) == 21 and names[-1] == "wf-visio"


def test_status_reads_an_app_whose_ingress_is_null(capsys):
    """Azure answers `"ingress": null` for an app with no ingress (a stream consumer), not a missing key."""
    app = _app(f"{OURS}:sha-abc1234")
    app["properties"]["configuration"] = {"ingress": None}
    fake = FakeArm({"continuations": app})
    az.status(fake, _target(fake))
    assert "(no ingress)" in capsys.readouterr().out
