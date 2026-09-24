"""Deploy the lab to Azure Container Apps — the PRODUCTION target (Railway stays development).

It renders the SAME topology `deploy/railway.py` does (deploy/topology.py); only three things are its
own, and each is a rule a wrong render would break silently:

  * ADDRESSING — a Container Apps ingress listens on 80 inside the environment and forwards to the
    server's port, so a server is `http://<app>`; public servers get an https edge.
  * SECRETS — every value that came from the operator's profile is a Key Vault REFERENCE, read by the
    apps' managed identity; only coordinates the topology computes are plain values. GitHub holds no
    production secret: a human publishes them (`secrets sync`), CD only rolls the image (`release`).
  * SCALE — servers and substrate consumers run one replica; a workload host scales to ZERO and is
    woken by KEDA's redis-streams scaler on the stream and group it consumes.

Profile: `.env` (the `# CLOUD:` profile) overlaid by the git-ignored `.env.azure` (production values).
Target: the outputs of the `foundation` Bicep deployment (deploy/azure/foundation.bicep).

Usage: python deploy/azure.py secrets sync
       python deploy/azure.py substrate up|status|images|env
       python deploy/azure.py workload <name> up|env
       python deploy/azure.py release                (what CD runs: roll every existing app onto this image)
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# deploy/ is scripts, loaded by path from tests and CI: its own directory goes on the import path once.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topology  # noqa: E402
from gate import _require_quiet  # noqa: E402
from topology import Network  # noqa: E402

API = "2026-01-01"
PROFILE_OVERLAY = ".env.azure"

# A Container Apps ingress listens on 80 and forwards to the target port, so the port is not in the URL.
AZURE_NET = Network(bind_host="0.0.0.0", address=lambda svc, port: f"http://{svc}")

REDIS_ADDRESS = "redis:6379"                  # internal TCP ingress: <app name>:<exposed port>
REDIS_IMAGE = "redis:7-alpine"
# RDB snapshots, not the append-only file: AOF's rewrite RENAMES a temp file, which fails on the SMB
# Azure Files share Container Apps mounts (verified report, bitnami/charts#2478). Until that is spiked,
# /data is the replica's own disk — see the decision record.
REDIS_CMD = "redis-server --bind 0.0.0.0 --protected-mode no --appendonly no --save 60 1 --dir /data"

# A copied value shorter than this is not treated as a secret it happens to equal ("1", "true", a port).
MIN_SECRET_LEN = 16

# Per-app compute. The default fits an MCP server or a stream consumer; the rest are measured hogs.
DEFAULT_RESOURCES = {"cpu": 0.25, "memory": "0.5Gi"}
RESOURCES = {
    "gateway": {"cpu": 1.0, "memory": "2Gi"},          # litellm + prisma + two redis pools
    "review": {"cpu": 0.5, "memory": "1Gi"},           # streamlit
    "semantic-mcp": {"cpu": 0.5, "memory": "1Gi"},     # rdflib holds every vocabulary in memory
    "storage-mcp": {"cpu": 0.5, "memory": "1Gi"},      # document parsing, figure extraction
    "speech-mcp": {"cpu": 0.5, "memory": "1Gi"},       # audio extraction
}
WORKLOAD_RESOURCES = {"cpu": 0.5, "memory": "1Gi"}     # agent_framework + litellm client ~250 MB floor
# A chain (screening -> approval -> design) arrives in bursts minutes apart; ten idle minutes costs less
# than a second ~70 s cold start in the middle of one.
WORKLOAD_COOLDOWN_S = 600
WORKLOAD_POLL_S = 30


@dataclass(frozen=True)
class Target:
    """The production environment an app is rendered INTO — the foundation deployment's outputs."""
    subscription: str
    resource_group: str
    location: str
    environment_id: str
    identity_id: str
    vault_uri: str
    env_domain: str
    image: str
    telemetry: str = ""          # App Insights connection string (an ingestion address, held as an app secret)

    @property
    def gateway_public(self) -> str:
        return f"https://gateway.{self.env_domain}"

    @property
    def review_public(self) -> str:
        return f"https://review.{self.env_domain}"


def secret_name(key: str) -> str:
    """A profile key in the form Key Vault and Container Apps both accept (lowercase, dashes)."""
    return key.lower().replace("_", "-")


def _secret_for(key: str, value: str, profile: dict) -> str | None:
    """The profile key whose secret this value IS, or None for a plain coordinate. A key taken
    straight from the profile references itself; a computed key that merely COPIES a profile secret
    (PG_VECTOR_API_KEY = MCP_SHARED_SECRET) references that one, instead of repeating it in plain."""
    if profile.get(key) == value:
        return key
    if len(value) >= MIN_SECRET_LEN:
        for k, v in profile.items():
            if v == value:
                return k
    return None


def _env_and_secrets(env: dict, profile: dict, target: Target) -> tuple[list, list]:
    entries, secrets = [], {}
    for k in sorted(env):
        src = _secret_for(k, env[k], profile)
        if src is None:
            entries.append({"name": k, "value": env[k]})
            continue
        n = secret_name(src)
        entries.append({"name": k, "secretRef": n})
        secrets[n] = {"name": n, "keyVaultUrl": f"{target.vault_uri}secrets/{n}", "identity": target.identity_id}
    return entries, list(secrets.values())


def _ingress(name: str, spec: dict) -> dict | None:
    """A server gets ingress on its port — external when the topology marks it public (a `port`),
    internal otherwise. Internal callers use plain http://<app>, so only the public edge refuses http."""
    if name not in topology.SERVICE_PORTS:
        return None
    external = bool(spec.get("port"))
    return {"external": external, "targetPort": topology.SERVICE_PORTS[name], "transport": "auto",
            "allowInsecure": not external}


def _app(target: Target, *, name: str, command: str | list, env_entries: list, secrets: list,
         ingress: dict | None, scale: dict, resources: dict, image: str | None = None) -> dict:
    configuration = {"activeRevisionsMode": "Single", "secrets": secrets}
    if ingress:
        configuration["ingress"] = ingress
    return {
        "location": target.location,
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {target.identity_id: {}}},
        "properties": {
            "environmentId": target.environment_id,
            "workloadProfileName": "Consumption",
            "configuration": configuration,
            "template": {
                "containers": [{"name": name, "image": image or target.image, "command": ["sh", "-c", command] if isinstance(command, str) else command,
                                "env": env_entries, "resources": resources}],
                "scale": scale,
            },
        },
    }


ONE = {"minReplicas": 1, "maxReplicas": 1}


def substrate_app(name: str, spec: dict, profile: dict, target: Target) -> dict:
    """One substrate role as a Container App: its allowlisted env (secrets by reference), its ingress,
    one replica."""
    env = topology.substrate_env(name, spec, profile, AZURE_NET)
    entries, secrets = _env_and_secrets(env, profile, target)
    return _app(target, name=name, command=spec["cmd"], env_entries=entries, secrets=secrets,
                ingress=_ingress(name, spec), scale=dict(ONE),
                resources=RESOURCES.get(name, DEFAULT_RESOURCES))


def workload_scale(spec: dict) -> dict:
    """How a workload host scales: from ZERO, woken by KEDA's redis-streams scaler on the group it
    consumes (topology.workload_group) of topology.REQUEST_STREAM, at REDIS_ADDRESS.

    Returns {"minReplicas", "maxReplicas", "rules": [{"name", "custom": {"type": "redis-streams",
    "metadata": {...}}}], ...}. Two metadata keys decide whether it works at all:
      lagCount            — entries not yet delivered to the group: what wakes a host at zero
      pendingEntriesCount — delivered but not yet acked: what keeps it up while a 10-20 min run is
                            still in progress (without it, the cool-down can scale it in mid-run)
    `spec.get("replicas")` is how many runs may overlap (Railway's per-service replicas).
    """
    on = {"address": REDIS_ADDRESS, "stream": topology.REQUEST_STREAM, "consumerGroup": topology.workload_group(spec)}
    return {
        "minReplicas": 0,
        "maxReplicas": int(spec.get("replicas") or 1),     # overlapping runs, as Railway's replicas allowed
        "cooldownPeriod": WORKLOAD_COOLDOWN_S,
        "pollingInterval": WORKLOAD_POLL_S,
        "rules": [
            # ONE undelivered request wakes a host: a higher threshold would leave a lone request at zero.
            {"name": "requests-waiting", "custom": {"type": "redis-streams",
                                                    "metadata": {**on, "lagCount": "1", "activationLagCount": "0"}}},
            # ...and a run in progress keeps it up, however long the run takes.
            {"name": "requests-running", "custom": {"type": "redis-streams",
                                                    "metadata": {**on, "pendingEntriesCount": "1"}}},
        ],
    }


def workload_app(name: str, spec: dict, profile: dict, target: Target) -> dict:
    """One workload host. It reaches the substrate only through the gateway (internal http://gateway),
    holds its own allowlist and nothing else, has no ingress, and scales from zero on its group."""
    env = topology.workload_env(name, spec, profile, AZURE_NET.address("gateway", 0), target.review_public)
    command = spec["cmd"]
    if "WF_CONSUMER" in env:
        # Replicas of one app share an environment; each must still consume under its OWN name, or they
        # share a pending list. Container Apps names every replica uniquely.
        env.pop("WF_CONSUMER")
        command = f'WF_CONSUMER="$CONTAINER_APP_REPLICA_NAME" exec {command}'
    entries, secrets = _env_and_secrets(env, profile, target)
    return _app(target, name=spec["service"], command=command, env_entries=entries, secrets=secrets,
                ingress=None, scale=workload_scale(spec), resources=dict(WORKLOAD_RESOURCES))


def redis_app(target: Target) -> dict:
    """The substrate's Redis: reachable only inside the environment, over TCP, exactly one replica."""
    return _app(target, name="redis", command=REDIS_CMD, env_entries=[], secrets=[],
                ingress={"external": False, "transport": "tcp", "targetPort": 6379, "exposedPort": 6379},
                scale=dict(ONE), resources={"cpu": 0.25, "memory": "0.5Gi"}, image=REDIS_IMAGE)


def _app_envs(profile: dict, review_public: str) -> list[dict]:
    """The environment of every app production runs — substrate roles (with the configured channels)
    and long-lived workloads — before secrets are split out."""
    gateway = AZURE_NET.address("gateway", 0)
    envs = [topology.substrate_env(n, s, profile, AZURE_NET) for n, s in topology.substrate_services(profile).items()]
    envs += [topology.workload_env(n, s, profile, gateway, review_public)
             for n, s in topology.WORKLOADS.items() if s.get("restart") == "ALWAYS"]
    return envs


def referenced_secrets(profile: dict) -> list[str]:
    """The profile keys some production app references — exactly what `secrets sync` publishes."""
    return sorted({src for env in _app_envs(profile, "") for k, v in env.items()
                   if (src := _secret_for(k, v, profile))})


# --- the trace sink: an OpenTelemetry Collector forwarding OTLP/HTTP to Application Insights -------
# Every role exports OTLP over HTTP (lab.platform.otel); Container Apps' managed agent speaks only
# gRPC and is in preview, so production runs the standard collector instead — tracing stays "chosen by
# endpoint": OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector in the production profile.
COLLECTOR_NAME = "otel-collector"
COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.135.0"
COLLECTOR_CONFIG = """receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
processors:
  batch: {}
exporters:
  azuremonitor:
    connection_string: ${env:APPLICATIONINSIGHTS_CONNECTION_STRING}
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [azuremonitor]
"""


def collector_app(target: Target) -> dict:
    """The trace sink: internal http on 4318, one replica, the connection string as an app secret."""
    return _app(target, name=COLLECTOR_NAME, image=COLLECTOR_IMAGE,
                command=["/otelcol-contrib", "--config=env:OTEL_CONFIG"],
                env_entries=[{"name": "OTEL_CONFIG", "value": COLLECTOR_CONFIG},
                             {"name": "APPLICATIONINSIGHTS_CONNECTION_STRING", "secretRef": "appinsights"}],
                secrets=[{"name": "appinsights", "value": target.telemetry}],
                ingress={"external": False, "targetPort": 4318, "transport": "auto", "allowInsecure": True},
                scale=dict(ONE), resources={"cpu": 0.25, "memory": "0.5Gi"})


# ================================================================== the Azure side (I/O)
ARM = "https://management.azure.com"
VAULT_API = "7.4"
ATTEMPTS, BACKOFF_S = 3, 2.0


def _az_token(resource: str) -> str:
    """A bearer for `resource` from the signed-in Azure CLI — a person's `az login`, or CI's OIDC login."""
    out = subprocess.run(["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken",
                          "-o", "tsv"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"az cannot issue a token for {resource}: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


class Arm:
    """Azure Resource Manager and Key Vault over HTTPS with the CLI's token. Retries a TRANSPORT failure,
    never a rejection — the same rule as railway.gql, for the same reason."""

    def __init__(self, token=_az_token):
        self._token, self._cache = token, {}

    def request(self, method, url, body=None):
        resource = "https://vault.azure.net" if ".vault.azure.net" in url else ARM
        if resource not in self._cache:
            self._cache[resource] = self._token(resource)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._cache[resource]}", "Content-Type": "application/json"})
        for attempt in range(1, ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                raise SystemExit(f"azure {method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:400]}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == ATTEMPTS:
                    raise SystemExit(f"azure unreachable after {ATTEMPTS} attempts: {e}") from e
                time.sleep(BACKOFF_S * attempt)


def _rg(target_or_sub, rg=None) -> str:
    sub, group = (target_or_sub.subscription, target_or_sub.resource_group) if rg is None else (target_or_sub, rg)
    return f"{ARM}/subscriptions/{sub}/resourceGroups/{group}"


def _apps_url(target: Target, name: str = "") -> str:
    return f"{_rg(target)}/providers/Microsoft.App/containerApps{'/' + name if name else ''}?api-version={API}"


def target(arm, subscription: str, resource_group: str, image: str) -> Target:
    """The production environment, read from the `foundation` deployment's outputs — never constants."""
    out = arm.request("GET", f"{_rg(subscription, resource_group)}/providers/Microsoft.Resources/deployments/"
                             f"foundation?api-version=2024-03-01")["properties"]["outputs"]
    loc = arm.request("GET", f"{_rg(subscription, resource_group)}?api-version=2024-03-01")["location"]
    val = lambda k: out.get(k, {}).get("value", "")  # noqa: E731
    return Target(subscription, resource_group, loc, val("environmentId"), val("appsIdentityId"),
                  val("vaultUri"), val("environmentDomain"), image, val("appInsightsConnectionString"))


def secrets_sync(arm, profile: dict, target: Target) -> None:
    """Publish every referenced profile key to Key Vault. Names only are printed — never a value."""
    keys = referenced_secrets(profile)
    for k in keys:
        arm.request("PUT", f"{target.vault_uri}secrets/{secret_name(k)}?api-version={VAULT_API}", {"value": profile[k]})
        print(f"  {secret_name(k)}")
    print(f"published {len(keys)} secret(s) to {target.vault_uri}")


def _put(arm, target: Target, name: str, body: dict) -> None:
    arm.request("PUT", _apps_url(target, name), body)
    print(f"  {name:22} applied")


def substrate_up(arm, profile: dict, target: Target) -> None:
    """Apply every substrate app: Redis and the trace sink first (everything else depends on them), then
    each role and each configured channel. Configuration AND code — a human runs this, never CD."""
    _require_quiet({**profile, "PUBLIC_GATEWAY_URL": target.gateway_public})
    print(f"applying substrate from {target.image}")
    _put(arm, target, "redis", redis_app(target))
    _put(arm, target, COLLECTOR_NAME, collector_app(target))
    for name, spec in topology.substrate_services(profile).items():
        _put(arm, target, name, substrate_app(name, spec, profile, target))
    print(f"\n  gateway  {target.gateway_public}\n  review   {target.review_public}")


def workload_up(arm, name: str, profile: dict, target: Target) -> None:
    spec = topology.WORKLOADS[name]
    _put(arm, target, spec["service"], workload_app(name, spec, profile, target))


def _list(arm, target: Target) -> list[dict]:
    return arm.request("GET", _apps_url(target))["value"]


def _image(app: dict) -> str:
    return app["properties"]["template"]["containers"][0]["image"]


def _ours(image: str) -> bool:
    return image.startswith(f"ghcr.io/{topology.REPO}:")


def release(arm, target: Target, wait_s: int = 600) -> bool:
    """Roll every EXISTING app that runs this repo's image onto `target.image`. Changes the image and
    nothing else — env, secrets, scale and ingress are configuration, shipped by `substrate up`.
    Returns True on any problem."""
    _require_quiet({"PUBLIC_GATEWAY_URL": target.gateway_public,
                    "LITELLM_MASTER_KEY": os.environ.get("LAB_GATE_KEY", "")})
    rolled = []
    for app in _list(arm, target):
        if not _ours(_image(app)):
            continue
        template = app["properties"]["template"]
        template["containers"][0]["image"] = target.image
        arm.request("PATCH", _apps_url(target, app["name"]), {"properties": {"template": template}})
        rolled.append(app["name"])
        print(f"  {app['name']:22} rolling -> {target.image.split(':')[-1]}")
    deadline, pending, bad = time.time() + wait_s, list(rolled), False
    while True:
        for name in list(pending):
            p = arm.request("GET", _apps_url(target, name))["properties"]
            if p.get("provisioningState") in ("Succeeded", "Failed"):
                pending.remove(name)
                if p["provisioningState"] == "Failed":
                    bad = True
                    print(f"  {name:22} FAILED on this image")
        if not pending or time.time() >= deadline:
            break
        time.sleep(10)
    for name in pending:
        bad = True
        print(f"  {name:22} STILL PROVISIONING after {wait_s}s")
    print("\n  release " + ("INCOMPLETE" if bad else f"complete ({len(rolled)} app(s))"))
    return bad


def image_report(arm, target: Target) -> bool:
    """Print every app's image; True when apps running this repo's image disagree."""
    seen = {}
    for app in sorted(_list(arm, target), key=lambda a: a["name"]):
        img = _image(app)
        print(f"  {app['name']:22} {img}")
        if _ours(img):
            seen.setdefault(img, []).append(app["name"])
    if len(seen) > 1:
        print("\n  MISMATCH — these apps run different builds of THIS repo:")
        for img, names in sorted(seen.items()):
            print(f"    {img}  <- {', '.join(names)}")
        return True
    return False


def status(arm, target: Target) -> None:
    for app in sorted(_list(arm, target), key=lambda a: a["name"]):
        p = app["properties"]
        fqdn = (p.get("configuration") or {}).get("ingress", {}).get("fqdn") or "(no ingress)"
        print(f"  {app['name']:22} {p.get('provisioningState', '?'):10} {p.get('runningStatus', '?'):9} {fqdn}")


def profile() -> dict:
    """The production profile: `.env`'s cloud profile overlaid by the git-ignored `.env.azure`."""
    overlay = os.path.join(topology.ROOT, PROFILE_OVERLAY)
    if not os.path.exists(overlay):
        raise SystemExit(f"no {PROFILE_OVERLAY} — production values are never taken from the dev profile")
    return topology.load_env_for_cloud(overlay=overlay)


if __name__ == "__main__":
    args = sys.argv[1:] + ["", "", ""]
    sub, rg = os.environ.get("AZURE_SUBSCRIPTION_ID", ""), os.environ.get("AZURE_RESOURCE_GROUP", "rg-lab-prod")
    if not sub:
        raise SystemExit("set AZURE_SUBSCRIPTION_ID (and AZURE_RESOURCE_GROUP) — CI reads them from the production environment")
    arm = Arm()
    tgt = target(arm, sub, rg, topology.IMAGE)
    tier, cmd = args[0], args[1]
    if tier == "release":
        sys.exit(1 if release(arm, tgt) else 0)
    elif (tier, cmd) == ("secrets", "sync"):
        secrets_sync(arm, profile(), tgt)
    elif tier == "substrate":
        {"up": lambda: substrate_up(arm, profile(), tgt), "status": lambda: status(arm, tgt),
         "images": lambda: sys.exit(1 if image_report(arm, tgt) else 0)}[cmd]()
    elif tier == "workload" and cmd in topology.WORKLOADS and args[2] == "up":
        workload_up(arm, cmd, profile(), tgt)
    else:
        raise SystemExit(__doc__)
