"""Deploy the lab to Azure Container Apps — the PRODUCTION target (Railway stays development).

It renders the SAME topology `deploy/railway.py` does (deploy/topology.py). What is its own, and each
is a rule a wrong render would break silently:

  * ADDRESSING — the target COMPUTES every coordinate it can (Redis, the trace sink, the public URLs),
    so no line of a hand-written profile can point production at dev; an internal server is
    `http://<app>` (ingress on 80 -> its port), a public one is reached at its own https edge.
  * SECRETS — a value taken from the operator's profile is a Key Vault REFERENCE read by the apps'
    managed identity; a coordinate is plain. GitHub holds no production secret: a person publishes
    them (`secrets sync`, also run by `substrate up`); CD only rolls the image (`release`).
  * SCALE — servers and substrate consumers run one replica; a workload host scales to ZERO and is
    woken by KEDA's redis-streams scaler on the stream and group it consumes.
  * VERSIONS — "released" means the NEW revision is the one serving, not that the ARM write landed.

Profile: `.env` (the `# CLOUD:` profile) overlaid by the git-ignored `.env.azure` (production values).
Target: the outputs of the `foundation` Bicep deployment (deploy/bicep/foundation.bicep).
"""
import hashlib
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

USAGE = """usage: python deploy/aca.py secrets sync
       python deploy/aca.py substrate up|status|images|versions|env
       python deploy/aca.py workload <name> up|env
       python deploy/aca.py release        (what CD runs: every existing app onto this commit's image)"""

API = "2026-01-01"
PROFILE_OVERLAY = ".env.azure"

REDIS_ADDRESS = "redis:6379"                  # internal TCP ingress: <app name>:<exposed port>
REDIS_URL = f"redis://{REDIS_ADDRESS}/0"
# RDB snapshots, not the append-only file: AOF's rewrite RENAMES a temp file, which fails on the SMB
# Azure Files share Container Apps mounts (bitnami/charts#2478). Until the persistence spike lands,
# /data is the replica's own disk — see the decision record.
REDIS_CMD = "redis-server --bind 0.0.0.0 --protected-mode no --appendonly no --save 60 1 --dir /data"

# Keys production must never hold: dev's vendor model keys (a gateway guardrail would otherwise send
# prompts to a non-Foundry, non-UAE endpoint), dev's bucket, Railway's management plane, and the
# embedder production does not run.
AZURE_DENY = ("OLLAMA_API_KEY", "ANTHROPIC_*", "OPENAI_UPSTREAM_*", "S3_*", "RAILWAY_*", "EMBED_URL")
# A rendered production value containing one of these points at dev or at a non-production provider.
FORBIDDEN = ("railway", "ollama.com")

# The gateway serves the ONE base config through the production model overlay: same names, Foundry
# deployments behind them. Composed from the topology's pieces, so a server flag reaches both targets.
AZURE_CMD = {
    "gateway": (f"python -m lab.substrate.gateway.models_overlay --config {topology.GATEWAY_CONFIG} "
                f"--overlay config/litellm-models.azure.yaml -- litellm {topology.GATEWAY_ARGS}"),
}

# Per-app compute, from MEASURED peaks (Railway metrics for the same roles, 24 Sep 2026): everything but
# the two below peaks at or under 0.26 GB, which the smallest Consumption size holds.
DEFAULT_RESOURCES = {"cpu": 0.25, "memory": "0.5Gi"}
RESOURCES = {
    # litellm + prisma + two redis pools. MEASURED: the dev gateway peaks at 2.52 GB (Railway metrics,
    # 24 Sep 2026), and at 2 GiB production's was killed 16 s into every boot. 3 GiB is the smallest
    # Consumption size above that peak.
    "gateway": {"cpu": 1.5, "memory": "3Gi"},
    "semantic-mcp": {"cpu": 0.5, "memory": "1Gi"},     # rdflib holds every vocabulary; measured peak 0.50 GB
}
# Measured peaks of every workload host on dev: 0.08-0.36 GB (use-case screening highest).
WORKLOAD_RESOURCES = {"cpu": 0.25, "memory": "0.5Gi"}
# A substrate consumer woken from zero is idle again within seconds of its entry; five minutes absorbs a burst.
CONSUMER_COOLDOWN_S = 300
# A chain (screening -> approval -> design) arrives in bursts minutes apart; ten idle minutes costs less
# than a second ~70 s cold start in the middle of one.
WORKLOAD_COOLDOWN_S = 600
WORKLOAD_POLL_S = 30
# The longest Container Apps allows: a replica being scaled in or replaced gets this long to finish.
WORKLOAD_GRACE_S = 600

PUBLIC = frozenset(n for n, s in topology.SUBSTRATE.items() if s.get("port"))


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
    logs_workspace: str = ""     # Log Analytics workspace (customer) id — where `versions` reads start lines

    def public(self, svc: str) -> str:
        return f"https://{svc}.{self.env_domain}"

    @property
    def gateway_public(self) -> str:
        return self.public("gateway")

    @property
    def review_public(self) -> str:
        return self.public("review")


def network(target: Target) -> Network:
    """Production's network: everything it can compute, and nothing it must not hold."""
    return Network(
        bind_host="0.0.0.0",
        address=lambda svc, port: target.public(svc) if svc in PUBLIC else f"http://{svc}",
        coords={"REDIS_URL": REDIS_URL,
                "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{COLLECTOR_NAME}",
                "OTEL_ENDPOINT": f"http://{COLLECTOR_NAME}/v1/traces",
                "REVIEW_APP_URL": target.review_public,
                "PUBLIC_GATEWAY_URL": target.gateway_public,
                "PROXY_BASE_URL": target.gateway_public},
        deny=AZURE_DENY)


def secret_name(key: str) -> str:
    """A profile key in the form Key Vault and Container Apps both accept (lowercase, dashes)."""
    return key.lower().replace("_", "-")


def _secret_for(key: str, value: str, profile: dict, net: Network) -> str | None:
    """The profile key whose Key Vault secret this value IS, or None for plain configuration. A
    coordinate is never a secret; a declared COPY references its source; a value taken unchanged from
    the profile references itself. Decided by where a value came from, never by what it looks like."""
    if key in topology.coordinate_keys(net):
        return None
    source = topology.COPIES.get(key)
    if source:
        return source if source in profile else None
    return key if profile.get(key) == value else None


def _digest(env: dict) -> str:
    """One hash of an app's whole configuration, secret values included. It is rendered as a plain
    variable so that a changed value changes the TEMPLATE — a Key Vault reference alone does not, and
    the app would keep running the old value with nothing saying so."""
    return hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()[:16]


def _env_and_secrets(env: dict, profile: dict, target: Target) -> tuple[list, list]:
    net = network(target)
    entries, secrets = [{"name": "LAB_CONFIG_DIGEST", "value": _digest(env)}], {}
    for k in sorted(env):
        src = _secret_for(k, env[k], profile, net)
        if src is None:
            entries.append({"name": k, "value": env[k]})
            continue
        n = secret_name(src)
        entries.append({"name": k, "secretRef": n})
        secrets[n] = {"name": n, "keyVaultUrl": f"{target.vault_uri}secrets/{n}", "identity": target.identity_id}
    return entries, list(secrets.values())


def _ingress(name: str) -> dict | None:
    """A server gets ingress on its port — external when the topology marks it public, internal
    otherwise. Internal callers use plain http://<app>; a public server is only ever reached at https."""
    if name not in topology.SERVICE_PORTS:
        return None
    external = name in PUBLIC
    return {"external": external, "targetPort": topology.SERVICE_PORTS[name], "transport": "auto",
            "allowInsecure": not external}


# How long a server may take to START listening before it is killed. With no probes declared,
# Container Apps probes the ingress port every second and killed the gateway (exit 137) 17 s into a
# boot that takes about a minute — a restart loop `status` reported as Running (measured 24 Sep 2026).
STARTUP_PERIOD_S, STARTUP_FAILURES = 10, 30          # up to 300 s to come up


def _probes(port: int) -> list[dict]:
    """TCP probes on the server's own port: a patient startup, then a liveness check that tolerates a
    busy minute (a long tool call must not get the gateway restarted under it)."""
    return [{"type": "Startup", "tcpSocket": {"port": port}, "initialDelaySeconds": 5,
             "periodSeconds": STARTUP_PERIOD_S, "failureThreshold": STARTUP_FAILURES},
            {"type": "Liveness", "tcpSocket": {"port": port}, "periodSeconds": 30, "failureThreshold": 4}]


def _app(target: Target, *, name: str, command: str | list, env_entries: list, secrets: list,
         ingress: dict | None, scale: dict, resources: dict, image: str | None = None,
         grace_s: int | None = None) -> dict:
    configuration = {"activeRevisionsMode": "Single", "secrets": secrets}
    if ingress:
        configuration["ingress"] = ingress
    container = {"name": name, "image": image or target.image,
                 "command": ["sh", "-c", command] if isinstance(command, str) else command,
                 "env": env_entries, "resources": resources}
    if ingress and ingress.get("targetPort"):
        container["probes"] = _probes(ingress["targetPort"])
    template = {"containers": [container], "scale": scale}
    if grace_s:
        template["terminationGracePeriodSeconds"] = grace_s
    return {
        "location": target.location,
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {target.identity_id: {}}},
        "properties": {"environmentId": target.environment_id, "workloadProfileName": "Consumption",
                       "configuration": configuration, "template": template},
    }


ONE = {"minReplicas": 1, "maxReplicas": 1}


def substrate_app(name: str, spec: dict, profile: dict, target: Target) -> dict:
    """One substrate role as a Container App: its allowlisted env (secrets by reference), its ingress.
    A pure stream consumer (`wakes_on`) scales from zero on what it reads; a server or a timer runs one."""
    env = topology.substrate_env(name, spec, profile, network(target))
    entries, secrets = _env_and_secrets(env, profile, target)
    scale = stream_scale(spec["wakes_on"], 1, CONSUMER_COOLDOWN_S) if spec.get("wakes_on") else dict(ONE)
    return _app(target, name=name, command=AZURE_CMD.get(name, spec["cmd"]), env_entries=entries,
                secrets=secrets, ingress=_ingress(name), scale=scale,
                resources=RESOURCES.get(name, DEFAULT_RESOURCES))


def stream_scale(reads, max_replicas: int, cooldown_s: int) -> dict:
    """From ZERO, woken by KEDA's redis-streams scaler on every (stream, group) the app reads: `lagCount`
    (undelivered entries) wakes it, `pendingEntriesCount` (delivered, not yet acked) keeps it up while
    it works — without the second, a cool-down can scale it in mid-run."""
    rules = []
    for i, (stream, group) in enumerate(reads):
        on = {"address": REDIS_ADDRESS, "stream": stream, "consumerGroup": group}
        # ONE undelivered entry wakes it: a higher threshold would leave a lone entry at zero.
        rules.append({"name": f"s{i}-waiting", "custom": {"type": "redis-streams",
                                                          "metadata": {**on, "lagCount": "1", "activationLagCount": "0"}}})
        rules.append({"name": f"s{i}-running", "custom": {"type": "redis-streams",
                                                          "metadata": {**on, "pendingEntriesCount": "1"}}})
    return {"minReplicas": 0, "maxReplicas": max_replicas, "cooldownPeriod": cooldown_s,
            "pollingInterval": WORKLOAD_POLL_S, "rules": rules}


def workload_scale(spec: dict) -> dict:
    """A workload host scales on its group of the request stream, with as many replicas as the topology
    declares — replica_services validates the count, so `replicas: 0` is an error, not one."""
    return stream_scale([(topology.REQUEST_STREAM, topology.workload_group(spec))],
                        len(topology.replica_services(spec)), WORKLOAD_COOLDOWN_S)


def _workload_env(name: str, spec: dict, profile: dict, target: Target) -> dict:
    return topology.workload_env(name, spec, profile, target.gateway_public, target.review_public,
                                 net=network(target))


def workload_app(name: str, spec: dict, profile: dict, target: Target) -> dict:
    """One workload host. It reaches the substrate only through the gateway, holds its own allowlist
    and nothing else, has no ingress, scales from zero on its group, and gets time to finish a run."""
    env = _workload_env(name, spec, profile, target)
    command = spec["cmd"]
    if "WF_CONSUMER" in env:
        # Replicas of one app share an environment; each must still consume under its OWN name, or they
        # share a pending list. Container Apps names every replica uniquely.
        env.pop("WF_CONSUMER")
        command = f'WF_CONSUMER="${{CONTAINER_APP_REPLICA_NAME:-$HOSTNAME}}" exec {command}'
    entries, secrets = _env_and_secrets(env, profile, target)
    return _app(target, name=spec["service"], command=command, env_entries=entries, secrets=secrets,
                ingress=None, scale=workload_scale(spec), resources=dict(WORKLOAD_RESOURCES),
                grace_s=WORKLOAD_GRACE_S)


def redis_app(target: Target) -> dict:
    """The substrate's Redis: reachable only inside the environment, over TCP, exactly one replica."""
    return _app(target, name="redis", command=REDIS_CMD, env_entries=[], secrets=[],
                ingress={"external": False, "transport": "tcp", "targetPort": 6379, "exposedPort": 6379},
                scale=dict(ONE), resources={"cpu": 0.25, "memory": "0.5Gi"}, image=topology.REDIS_IMAGE)


# --- the trace sink: an OpenTelemetry Collector forwarding OTLP/HTTP to Application Insights -------
# Every role exports OTLP over HTTP (lab.platform.otel); Container Apps' managed agent speaks only gRPC
# and is in preview, so production runs the standard collector: tracing stays "chosen by endpoint".
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


def _app_envs(profile: dict, target: Target) -> dict:
    """{app: env} for every app production runs, before secrets are split out."""
    net = network(target)
    envs = {n: topology.substrate_env(n, s, profile, net) for n, s in topology.substrate_services(profile).items()}
    envs.update({topology.WORKLOADS[n]["service"]: _workload_env(n, topology.WORKLOADS[n], profile, target)
                 for n in topology.long_lived_workloads()})
    return envs


def referenced_secrets(profile: dict, target: Target) -> list[str]:
    """The profile keys some production app references — exactly what `secrets sync` publishes."""
    net = network(target)
    return sorted({src for env in _app_envs(profile, target).values() for k, v in env.items()
                   if (src := _secret_for(k, v, profile, net))})


def assert_production(profile: dict, target: Target) -> None:
    """Refuse to render production while any app would receive a value that points at dev or at a
    non-production provider — named, so the fix is one line of `.env.azure`."""
    bad = sorted({k for env in _app_envs(profile, target).values() for k, v in env.items()
                  if any(f in (v or "").lower() for f in FORBIDDEN)})
    if bad:
        raise SystemExit(f"production would receive dev values for: {', '.join(bad)} — set them in {PROFILE_OVERLAY}")


# ================================================================== the Azure side (I/O)
ARM = "https://management.azure.com"
VAULT_API = "7.4"
ATTEMPTS, BACKOFF_S = 4, 2.0
RETRY_STATUS = {409, 429}          # an operation in progress / throttled: routine during a release


def _az_token(resource: str) -> str:
    """A bearer for `resource` from the signed-in Azure CLI — a person's `az login`, or CI's OIDC login."""
    out = subprocess.run(["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken",
                          "-o", "tsv"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"az cannot issue a token for {resource}: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


class Arm:
    """Azure Resource Manager, Key Vault and Log Analytics over HTTPS with the CLI's token. Retries a
    transport failure, a throttle or a conflict; never a rejection."""

    RESOURCES = ((".vault.azure.net", "https://vault.azure.net"), ("api.loganalytics.io", "https://api.loganalytics.io"))

    def __init__(self, token=_az_token):
        self._token, self._cache = token, {}

    def request(self, method, url, body=None, missing_ok=False):
        resource = next((r for host, r in self.RESOURCES if host in url), ARM)
        if resource not in self._cache:
            self._cache[resource] = self._token(resource)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(1, ATTEMPTS + 1):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self._cache[resource]}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 404 and missing_ok:
                    return None
                if e.code in RETRY_STATUS and attempt < ATTEMPTS:
                    time.sleep(float(e.headers.get("Retry-After") or BACKOFF_S * attempt))
                    continue
                raise SystemExit(f"azure {method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:400]}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == ATTEMPTS:
                    raise SystemExit(f"azure unreachable after {ATTEMPTS} attempts: {e}") from e
                time.sleep(BACKOFF_S * attempt)


def _rg(sub: str, rg: str) -> str:
    return f"{ARM}/subscriptions/{sub}/resourceGroups/{rg}"


def _apps_url(target: Target, name: str = "", sub: str = "") -> str:
    base = f"{_rg(target.subscription, target.resource_group)}/providers/Microsoft.App/containerApps"
    return f"{base}{'/' + name if name else ''}{sub}?api-version={API}"


REQUIRED_OUTPUTS = ("environmentId", "appsIdentityId", "vaultUri", "environmentDomain", "appInsightsConnectionString")


def target(arm, subscription: str, resource_group: str, image: str) -> Target:
    """The production environment, read from the `foundation` deployment's outputs — never constants.
    A missing output is refused: an empty connection string would drop every trace silently."""
    out = arm.request("GET", f"{_rg(subscription, resource_group)}/providers/Microsoft.Resources/deployments/"
                             f"foundation?api-version=2024-03-01")["properties"]["outputs"]
    missing = [k for k in REQUIRED_OUTPUTS if not out.get(k, {}).get("value")]
    if missing:
        raise SystemExit(f"the foundation deployment has no {', '.join(missing)} — redeploy deploy/bicep/foundation.bicep")
    loc = arm.request("GET", f"{_rg(subscription, resource_group)}?api-version=2024-03-01")["location"]
    val = lambda k: out.get(k, {}).get("value", "")  # noqa: E731
    return Target(subscription, resource_group, loc, val("environmentId"), val("appsIdentityId"), val("vaultUri"),
                  val("environmentDomain"), image, val("appInsightsConnectionString"), val("logsWorkspaceId"))


def secrets_sync(arm, profile: dict, target: Target) -> None:
    """Publish every referenced profile key to Key Vault. Names only are printed — never a value."""
    assert_production(profile, target)
    keys = referenced_secrets(profile, target)
    for k in keys:
        arm.request("PUT", f"{target.vault_uri}secrets/{secret_name(k)}?api-version={VAULT_API}", {"value": profile[k]})
        print(f"  {secret_name(k)}")
    print(f"published {len(keys)} secret(s) to {target.vault_uri}")


def image_exists(image: str) -> bool:
    """Whether the registry HAS this image — asked anonymously (the package is public). A new app is
    created on it, and the tag comes from the local checkout: measured 24 Sep 2026, nine workloads
    were created on the tag of a commit not yet pushed, so on an image that did not exist."""
    repo, _, tag = image.removeprefix("ghcr.io/").partition(":")
    try:
        with urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{repo}:pull", timeout=30) as r:
            token = json.load(r)["token"]
        req = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{tag}", method="HEAD", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError:
        return False


def _apply(arm, target: Target, name: str, body: dict) -> None:
    """Create or update one app. An EXISTING app keeps the image it runs: configuration is not a code
    release, and the operator's local HEAD is a commit no reviewer approved. A new app starts on
    `target.image` — refused if the registry does not have it."""
    current = arm.request("GET", _apps_url(target, name), missing_ok=True)
    for c in body["properties"]["template"]["containers"]:
        if not topology.is_ours(c["image"]):
            continue                                   # a pinned third-party image (redis, the collector)
        if current and topology.is_ours(_image(current)):
            c["image"] = _image(current)
        elif not image_exists(c["image"]):
            raise SystemExit(f"{name}: the registry has no {c['image'].split(':')[-1]} — push the commit and let CI "
                             f"build it, or set LAB_IMAGE_TAG to a built one")
    arm.request("PUT", _apps_url(target, name), body)
    print(f"  {name:24} {'updated' if current else 'created'}  {_image(body).split(':')[-1]}")


def substrate_up(arm, profile: dict, target: Target) -> None:
    """Publish the secrets, then apply every substrate app: Redis and the trace sink first (everything
    else depends on them), then each role and each configured channel. A person runs this, never CD."""
    secrets_sync(arm, profile, target)
    _require_quiet({**profile, "PUBLIC_GATEWAY_URL": target.gateway_public})
    print(f"applying substrate (new apps start on {target.image})")
    _apply(arm, target, "redis", redis_app(target))
    _apply(arm, target, COLLECTOR_NAME, collector_app(target))
    for name, spec in topology.substrate_services(profile).items():
        _apply(arm, target, name, substrate_app(name, spec, profile, target))
    print(f"\n  gateway  {target.gateway_public}\n  review   {target.review_public}")


def workload_up(arm, name: str, profile: dict, target: Target) -> None:
    assert_production(profile, target)
    spec = topology.WORKLOADS[name]
    _apply(arm, target, spec["service"], workload_app(name, spec, profile, target))


def _list(arm, target: Target) -> list[dict]:
    """Every app in the resource group — ALL pages. ARM returns 20 to a page; reading only the first
    once made `release` skip every workload and report success."""
    page = arm.request("GET", _apps_url(target))
    apps = list(page["value"])
    while page.get("nextLink"):
        page = arm.request("GET", page["nextLink"])
        apps += page["value"]
    return apps


def _image(app: dict) -> str:
    return app["properties"]["template"]["containers"][0]["image"]


def _serving_image(arm, target: Target, app: dict) -> str | None:
    """The image of the revision actually SERVING — the latest READY one, not the template."""
    rev = app["properties"].get("latestReadyRevisionName")
    if not rev:
        return None
    return _image(arm.request("GET", _apps_url(target, app["name"], f"/revisions/{rev}")))


def release(arm, target: Target, wait_s: int = 600, bearer: str = "") -> bool:
    """Roll every EXISTING app running this repo's image onto `target.image` — the image and nothing
    else. Done means each app's newest revision is the READY one. Returns True on any problem,
    including having nothing to roll (a wrong resource group must not go green)."""
    _require_quiet({"PUBLIC_GATEWAY_URL": target.gateway_public, "GATE_BEARER": bearer})
    rolled = []
    for app in _list(arm, target):
        if not topology.is_ours(_image(app)):
            continue
        template = app["properties"]["template"]
        template["containers"][0]["image"] = target.image
        arm.request("PATCH", _apps_url(target, app["name"]), {"properties": {"template": template}})
        rolled.append(app["name"])
        print(f"  {app['name']:24} rolling -> {target.image.split(':')[-1]}")
    if not rolled:
        print("  nothing to release — no app runs this repo's image here")
        return True
    deadline, pending, bad = time.time() + wait_s, list(rolled), False
    while True:
        for name in list(pending):
            p = arm.request("GET", _apps_url(target, name))["properties"]
            if p.get("provisioningState") == "Failed":
                pending.remove(name)
                bad = True
                print(f"  {name:24} FAILED on this image")
            elif p.get("latestRevisionName") and p.get("latestReadyRevisionName") == p.get("latestRevisionName"):
                pending.remove(name)
                print(f"  {name:24} serving {p['latestRevisionName']}")
        if not pending or time.time() >= deadline:
            break
        time.sleep(10)
    for name in pending:
        bad = True
        print(f"  {name:24} NOT SERVING the new revision after {wait_s}s (the old one still is)")
    print("\n  release " + ("INCOMPLETE" if bad else f"complete ({len(rolled)} app(s))"))
    return bad


def image_report(arm, target: Target) -> bool:
    """Print what every app SERVES; True when this repo's apps disagree or do not serve this release."""
    serving = {}
    for app in sorted(_list(arm, target), key=lambda a: a["name"]):
        serving[app["name"]] = _serving_image(arm, target, app) or _image(app)
        print(f"  {app['name']:24} {serving[app['name']]}")
    bad = False
    for img, names in topology.image_mismatches(serving).items():
        bad = True
        print(f"  MISMATCH  {img}  <- {', '.join(names)}")
    stale = [n for n, img in serving.items() if topology.is_ours(img) and img != target.image]
    if stale and not bad:
        bad = True
        print(f"\n  MISMATCH — not serving {target.image.split(':')[-1]}: {', '.join(stale)}")
    return bad


def version_report(rows: list[dict], tag: str) -> bool:
    """From each app's most recent start line (`build=<sha>`): True when an app says it runs a
    different build from `tag`. The half a template cannot fake — what the process says it is."""
    bad = False
    for row in sorted(rows, key=lambda r: r["ContainerAppName_s"]):
        found = topology.build_of(row.get("Log_s") or "")
        ok = bool(found) and tag.startswith("sha-") and found.startswith(tag[4:])
        bad |= not ok
        print(f"  {row['ContainerAppName_s']:24} {found or '(no build line)'}{'' if ok else '   MISMATCH'}")
    return bad


def versions(arm, target: Target) -> bool:
    if not target.logs_workspace:
        raise SystemExit("the foundation deployment has no logsWorkspaceId output — redeploy it")
    q = ("ContainerAppConsoleLogs_CL | where TimeGenerated > ago(7d) and Log_s has 'build=' "
         "| summarize arg_max(TimeGenerated, Log_s) by ContainerAppName_s")
    res = arm.request("POST", f"https://api.loganalytics.io/v1/workspaces/{target.logs_workspace}/query", {"query": q})
    cols = [c["name"] for c in res["tables"][0]["columns"]]
    rows = [dict(zip(cols, r)) for r in res["tables"][0]["rows"]]
    return version_report(rows, target.image.split(":")[-1])


def status(arm, target: Target) -> None:
    for app in sorted(_list(arm, target), key=lambda a: a["name"]):
        p = app["properties"]
        # Azure answers `"ingress": null` for an app without one, not a missing key.
        fqdn = ((p.get("configuration") or {}).get("ingress") or {}).get("fqdn") or "(no ingress)"
        print(f"  {app['name']:24} {p.get('provisioningState', '?'):10} {p.get('runningStatus', '?'):9} {fqdn}")


def env_report(profile: dict, target: Target, only: str | None = None) -> None:
    """OFFLINE audit: the key names each app receives and which are Key Vault references. No values."""
    net = network(target)
    for app, env in sorted(_app_envs(profile, target).items()):
        if only and app != only:
            continue
        refs = sorted(k for k, v in env.items() if _secret_for(k, v, profile, net))
        plain = sorted(k for k in env if k not in refs)
        print(f"  {app:24} secrets ({len(refs)}): {', '.join(refs)}\n  {'':24} config  ({len(plain)}): {', '.join(plain)}")


def profile() -> dict:
    """The production profile: `.env`'s cloud profile overlaid by the git-ignored `.env.azure`."""
    overlay = os.path.join(topology.ROOT, PROFILE_OVERLAY)
    if not os.path.exists(overlay):
        raise SystemExit(f"no {PROFILE_OVERLAY} — production values are never taken from the dev profile")
    return topology.load_env_for_cloud(overlay=overlay)


def _gate_bearer() -> str:
    """An Entra token for the deploy identity, which holds the Workflow.Submit role — the quiet gate's
    credential with no secret anywhere. Unavailable -> the gate says it cannot ask."""
    aud = os.environ.get("ENTRA_GATEWAY_AUDIENCE", "")
    try:
        return _az_token(aud) if aud else ""
    except SystemExit as e:
        print(f"  quiet gate: no token for {aud} ({str(e)[:80]})", file=sys.stderr)
        return ""


def main(argv: list[str]) -> int:
    a = argv + ["", "", ""]
    commands = {("secrets", "sync"), ("substrate", "up"), ("substrate", "status"), ("substrate", "images"),
                ("substrate", "versions"), ("substrate", "env"), ("release", "")}
    is_workload = a[0] == "workload" and a[1] in topology.long_lived_workloads() and a[2] in ("up", "env")
    if (a[0], a[1]) not in commands and not is_workload:
        print(USAGE, file=sys.stderr)
        return 2
    sub = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    if not sub:
        print("set AZURE_SUBSCRIPTION_ID (and AZURE_RESOURCE_GROUP)\n" + USAGE, file=sys.stderr)
        return 2
    arm = Arm()
    tgt = target(arm, sub, os.environ.get("AZURE_RESOURCE_GROUP", "rg-lab-prod"), topology.IMAGE)
    if a[0] == "release":
        return 1 if release(arm, tgt, bearer=_gate_bearer()) else 0
    if (a[0], a[1]) == ("secrets", "sync"):
        secrets_sync(arm, profile(), tgt)
    elif a[0] == "substrate":
        run = {"up": lambda: substrate_up(arm, profile(), tgt), "status": lambda: status(arm, tgt),
               "images": lambda: image_report(arm, tgt), "versions": lambda: versions(arm, tgt),
               "env": lambda: env_report(profile(), tgt)}[a[1]]()
        return 1 if run is True else 0
    elif a[2] == "up":
        workload_up(arm, a[1], profile(), tgt)
    else:
        env_report(profile(), tgt, only=topology.WORKLOADS[a[1]]["service"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
