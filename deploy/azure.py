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
import os
import sys
from dataclasses import dataclass

# deploy/ is scripts, loaded by path from tests and CI: its own directory goes on the import path once.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topology  # noqa: E402
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


def _app(target: Target, *, name: str, command: str, env_entries: list, secrets: list,
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
                "containers": [{"name": name, "image": image or target.image, "command": ["sh", "-c", command],
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
