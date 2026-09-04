"""Deploy the lab to Railway as two independent tiers (see deploy/README.md):

  substrate  — the shared plane: redis (internal), gateway (public), semantic-mcp + adoit-mcp +
               storage-mcp + workflow-mcp (internal), review (public), plus every approval CHANNEL
               that is configured (telegram, teams — internal, no ingress). Lives in the project
               alongside Jaeger, so the gateway reaches the MCP servers over Railway private DNS
               (*.railway.internal).
  workload   — a business process (e.g. visio) as its OWN service, referencing the substrate
               ONLY via the gateway's PUBLIC domain + the shared managed backends — never the
               MCP servers (internal to the substrate) or another workload. Run-to-completion
               jobs deploy with restartPolicyType=NEVER (re-run = redeploy); event/A2A-driven
               hosts stay long-lived. Each workload is deployed/torn down independently.

Builds `deploy/Dockerfile` from the PUBLIC GitHub repo (no local Docker, no GitHub app needed).
Config/secrets come from `.env`: active `KEY=value` lines, with `# CLOUD: KEY=value` comment
values overriding the machine-local ones (Redis Cloud, Railway Jaeger). Secrets stay only in
`.env`, never in this script. Idempotent: services are found by name and updated in place.
LEAST PRIVILEGE: each service receives ONLY the keys its role reads — `ROLE_ENV` below is the
per-role allowlist (the Container Apps secret-scope table); `substrate env` / `workload <n> env`
print exactly what each service gets, offline, for review.

Usage: set -a && source .env && set +a && python deploy/railway.py substrate up|down|status|env
       set -a && source .env && set +a && python deploy/railway.py workload visio up|down|status|env
"""
import fnmatch
import json
import os
import re
import sys
import urllib.request

REPO = "shlapolosa/local-agent-lab"
BRANCH = "main"

# --- how the image gets built -------------------------------------------------------------------
# "image" (default): ONE image is built in CI (.github/workflows/image.yml) and pushed to GHCR;
#   every service — the substrate roles + each workload — is an IMAGE service pulling that same
#   immutable tag and differing only in start command + env. Railway builds nothing, so a deploy is
#   N pulls instead of N identical Dockerfile builds, and every role provably runs the same bits.
# "repo" (LAB_BUILD=repo): the original path — each service builds deploy/Dockerfile from GitHub.
#   Kept as the no-registry fallback; note Railway REQUIRES cache-mount ids of the form
#   `s/<serviceId>-<name>`, which one shared Dockerfile cannot satisfy, so repo builds are slower.
# The image must be readable by Railway: make the GHCR package public (it mirrors this public repo),
# or set a registry credential on the services.
BUILD_MODE = os.environ.get("LAB_BUILD", "image")           # image | repo
IMAGE_TAG = os.environ.get("LAB_IMAGE_TAG", BRANCH)         # a git sha pins a rollback
IMAGE = os.environ.get("LAB_IMAGE") or f"ghcr.io/{REPO}:{IMAGE_TAG}"


def _source():
    """The service `source` for repo-built roles: a registry image, or this GitHub repo."""
    return {"image": IMAGE} if BUILD_MODE == "image" else {"repo": REPO}


def _build_input(cmd):
    """Service-instance fields that select WHAT runs: a prebuilt image, or a Dockerfile build."""
    return {"source": {"image": IMAGE}} if BUILD_MODE == "image" else {"dockerfilePath": "deploy/Dockerfile"}
API = "https://backboard.railway.com/graphql/v2"
# Railway credentials are read lazily (`.get`) so the module imports WITHOUT them — the env parser
# + ROLE_ENV are reused offline by scripts/e2e_smoke.py and tests/deploy/test_railway_env.py. Every network
# command checks them first (`_require_railway()`).
H = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
     "Content-Type": "application/json", "Accept": "application/json",
     "Project-Access-Token": os.environ.get("RAILWAY_TOKEN", "")}
PROJECT = os.environ.get("RAILWAY_PROJECT_ID", "")
ENV = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _require_railway():
    missing = [k for k in ("RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing {', '.join(missing)} — set -a && source .env && set +a first")

# --- substrate services: name -> role command, ingress, health ---
SUBSTRATE = {
    "semantic-mcp": {"cmd": "python -m lab.substrate.mcp.semantic.server", "port": None},
    "adoit-mcp":    {"cmd": "python -m lab.substrate.mcp.adoit.server", "port": None},
    # READ-ONLY governed object store. "s3": True = this service (and only such services) receives the
    # bucket credentials (S3_* + UPLOADS_URL); every other service — and every workload — gets none.
    "storage-mcp":  {"cmd": "python -m lab.substrate.mcp.storage.server", "port": None, "s3": True},
    # the front door to every business process (submit/status/result) AND the human-in-the-loop
    # approval gate a run pauses at (approvals_list/get/decide). Redis ONLY: it publishes
    # workflow:requests events, reads their status and appends approval decisions — no store, no
    # bucket, no ADOIT credential.
    "workflow-mcp": {"cmd": "python -m lab.substrate.mcp.workflow.server", "port": None},
    "gateway":      {"cmd": "litellm --config config/litellm-config.yaml --host 0.0.0.0 --port 4000 --num_workers 1",
                     "port": 4000,   # NOTE: deliberately NO "health" key — see below.
                     # --host 0.0.0.0 + NO healthcheck: the verified working combo (health 200, 7 models).
                     # Railway uses TWO different network paths to a container: the PUBLIC edge reaches it
                     # over IPv4, but the HEALTHCHECK probes over IPv6. uvicorn binds a single stack, so
                     # neither single choice satisfies both: `--host ::` is IPv6-only (healthcheck could
                     # pass, but the IPv4 public edge 502s — every request did), and `--host 0.0.0.0` is
                     # IPv4-only (public edge works, but the IPv6 healthcheck can't connect and Railway
                     # kills the deploy). Fix = bind 0.0.0.0 for the public edge AND set no healthcheckPath
                     # so the IPv6 probe never runs. Nothing internal calls the gateway (workloads use its
                     # public URL), so IPv4-only inbound is fine; its OUTBOUND calls to the MCP servers over
                     # private IPv6 DNS are unaffected by its own bind. (streamlit's :: happens to dual-stack,
                     # which is why review works on :: — uvicorn does not.) Do NOT set a manual PORT var
                     # either: forcing PORT=4000 also broke edge routing (verified). DISABLE_SCHEMA_UPDATE:
                     # Neon is already migrated by the native bootstrap; skip the ~152-migration cold-start
                     # replay a fresh container otherwise runs against remote Neon.
                     "env": {"OTEL_SERVICE_NAME": "litellm-gateway", "DISABLE_SCHEMA_UPDATE": "true"}},
    "review":       {"cmd": "streamlit run src/lab/substrate/review/app.py --server.port 8501 "
                            "--server.address :: --server.headless true", "port": 8501,
                     "s3": True},   # the Submit page writes uploads DIRECT to the bucket (trusted substrate component)
}
S3_KEYS = ("S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE", "UPLOADS_URL")

# --- approval CHANNELS: substrate services deployed ONLY when they are configured ----------------
# A channel is another consumer group on `approvals:requests` (same contract as the review app): it
# notifies a human where they already are and records the decision. It is deployed only when its
# settings are in the deploy profile, because an unconfigured channel exits immediately by design —
# `lab.sh` skips it for exactly the same reason. Long-lived loop -> restartPolicyType ALWAYS; no
# port -> no public domain, nothing calls it. A channel holds NO store, bucket or gateway credential
# (ROLE_ENV below): its own webhook/token, Redis, and the link(s) it puts in front of the human.
CHANNELS = {
    "telegram": {"cmd": "python -m lab.substrate.channels.telegram", "port": None, "restart": "ALWAYS",
                 "requires": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")},
    "teams":    {"cmd": "python -m lab.substrate.channels.teams", "port": None, "restart": "ALWAYS",
                 "requires": ("TEAMS_WEBHOOK_URL",)},
}


def substrate_services(base_env: dict) -> dict:
    """The substrate table for THIS deploy: the fixed roles plus every channel whose settings are in
    `base_env`. Pure — `up`, `status` and `env` all read it, so a configured channel is deployed,
    audited and torn down like any other service, and an unconfigured one is never created."""
    return {**SUBSTRATE, **{n: s for n, s in CHANNELS.items()
                            if all(base_env.get(k) for k in s["requires"])}}


def deploy_profile() -> dict:
    """The deploy profile when there is a `.env` to read, else {}. `down`/`status` never needed `.env`
    before channels made the service list depend on it — with {} a channel is still covered whenever
    it is deployed, so a box that only exports the Railway credentials can still inspect and tear
    down the substrate."""
    return load_env_for_cloud() if os.path.exists(os.path.join(ROOT, ".env")) else {}


def substrate_names(base_env: dict, ids: dict | None = None) -> list[str]:
    """Service names the substrate owns, in deploy order (redis first, jaeger last). A channel is
    included when it is configured OR already deployed — so `down`/`status` still see a channel
    whose settings have since been removed from `.env`, instead of orphaning it."""
    table = substrate_services(base_env)
    chans = [n for n in CHANNELS if n in table or n in (ids or {})]
    return [REDIS_NAME] + list(SUBSTRATE) + chans + [JAEGER_NAME]

# --- per-role environment ALLOWLIST (least privilege; review B-H2) ---
# A service receives ONLY the `.env` keys (after `# CLOUD:` override + $VAR expansion, plus the
# coordinates configure() layers on) that match its role's glob patterns — nothing is popped from
# a full copy any more. Derived from the code that READS env in each role (cited per line); when a
# role starts reading a new variable, add it here in the same change, or the container won't see
# it. This table is also the Azure Container Apps secret-scope map (which Key Vault refs each app
# gets). The bucket credentials (S3_KEYS) are NOT listed anywhere here on purpose: they are granted
# solely by a service's `"s3": True` flag (review + storage-mcp), which env_for_role() adds.
_OTLP = "OTEL_EXPORTER_OTLP_*"                     # every Python role: lab.platform.otel.tracer reads OTEL_EXPORTER_OTLP_ENDPOINT
ROLE_ENV = {
    "gateway": [                                   # litellm + gateway/{custom_auth,auto_router,pii_guardrail}.py
        "LITELLM_*",                               # master key, LITELLM_MCP_CLIENT_TIMEOUT / TOOL_LISTING_TIMEOUT (litellm env)
        "DATABASE_URL",                            # key/team/spend store (litellm)
        "OLLAMA_API_KEY", "ANTHROPIC_UPSTREAM_API_KEY",   # litellm-config.yaml os.environ/ refs; auto_router.py
        "MCP_SHARED_SECRET",                       # litellm-config.yaml mcp_servers authentication_token
        "ADOIT_MCP_URL", "SEMANTIC_MCP_URL", "STORAGE_MCP_URL", "WORKFLOW_MCP_URL",   # mcp_servers url (set by configure(), private DNS)
        "REDIS_URL",                               # custom_auth.py; litellm falls back to it when REDIS_HOST/PORT/
                                                   # PASSWORD are absent (verified) — those three stay OUT (unchanged
                                                   # from the old drop-set; the cloud Redis has no password)
        "OTEL_*",                                  # OTEL_EXPORTER / OTEL_ENDPOINT / OTEL_SERVICE_NAME (litellm otel callback)
        "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE", "ENTRA_CLIENT_TO_KEY", "DEVELOPERS_TEAM_ID",   # custom_auth.py
        "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_TENANT", "PROXY_BASE_URL",     # litellm UI SSO
        "DISABLE_SCHEMA_UPDATE",                   # spec env (see SUBSTRATE["gateway"])
    ],
    "adoit-mcp": [                                 # src/lab/substrate/mcp/adoit/{server,adoit_rest}.py + lab.substrate.{approvals,artifacts,mcpauth} + lab.platform.config
        "ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID",   # ADOIT REST credentials (this role ONLY)
        "ADOIT_REST_WRITE",                        # config.ADOIT_REST_WRITE write-path toggle
        "MCP_SHARED_SECRET", "BIND_HOST", "ADOIT_MCP_PORT",   # mcpauth bearer; uvicorn bind
        "REDIS_URL",                               # approvals.request() (adoit_request_import)
        "ARTIFACTS_URL", "DATABASE_URL",           # artifacts.store() (renders -> art:// refs; DATABASE_URL is config's fallback)
        "REVIEW_APP_URL",                          # tool results link the reviewer to the review app
        _OTLP, "REFERENCE_MODELS_DIR",             # tracing; src/lab/core/semantic/reference/baguild.py workbook dir (optional)
    ],
    "semantic-mcp": [                              # src/lab/substrate/mcp/semantic/server.py — credential-free, read-only
        "MCP_SHARED_SECRET", "BIND_HOST", "SEMANTIC_MCP_PORT",
        "ARTIFACTS_URL", "DATABASE_URL",           # semantic_store_spec / semantic_export_archimate write spec refs
        _OTLP, "REFERENCE_MODELS_DIR",
    ],
    "storage-mcp": [                               # src/lab/substrate/mcp/storage/server.py + lab.substrate.artifacts + lab.platform.docparse — READ-ONLY upload store
        "MCP_SHARED_SECRET", "BIND_HOST", "STORAGE_MCP_PORT",
        "ARTIFACTS_URL", "DATABASE_URL",           # config.UPLOADS_URL falls back to ARTIFACTS_URL when no bucket is configured
        "BA_MAX_*",                                # docparse.py size limits (BA_MAX_DOC_CHARS, BA_MAX_EMBEDDED_IMAGES)
        _OTLP,
    ],                                             # + S3_KEYS via the "s3" flag (the only writer/reader pair of the bucket)
    "workflow-mcp": [                              # src/lab/substrate/mcp/workflow/{server,approval_tools}.py + lab.substrate.approvals + lab.platform.{workflows,contracts} — Redis ONLY
        "MCP_SHARED_SECRET", "BIND_HOST", "WORKFLOW_MCP_PORT",
        "REDIS_URL",                               # workflows.request/status + approvals streams — the ONLY backend it holds
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # approval_tools.py: the two LINKS a reviewer follows
        _OTLP,                                     # (addresses, not credentials). Deliberately NO
    ],                                             # ARTIFACTS_URL/DATABASE_URL/UPLOADS_URL/S3_*: refs are never dereferenced here
    "review": [                                    # src/lab/substrate/review/app.py + lab.substrate.{approvals,artifacts} + lab.platform.{workflows,runlog,config}
        "REVIEW_APP_PASSWORD",                     # config.REVIEW_APP_PASSWORD gate
        "REDIS_URL",                               # approvals / workflows / runlog streams
        "ARTIFACTS_URL", "DATABASE_URL",           # reads xml/svg refs of a request
        "JAEGER_UI_URL",                           # trace links
    ],                                             # + S3_KEYS via the "s3" flag (Submit page uploads straight to the bucket)
    "telegram": [                                  # src/lab/substrate/channels/telegram.py + lab.substrate.approvals + lab.platform.config
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",  # the Bot API credential + target chat (unset = not deployed)
        "REDIS_URL",                               # approvals:requests consumer group "telegram" + decisions
        "REVIEW_APP_URL",                          # the link the message sends the human to for the diagrams
        _OTLP,                                     # tracing sink: an ADDRESS, not a credential. A channel builds no
                                                   # tracer today (nothing in its import graph does) — it is granted so
                                                   # that emitting spans from a channel is a code change, not a deploy one
    ],                                             # NOTHING else: no store, no bucket, no gateway/ADOIT secret
    "teams": [                                     # src/lab/substrate/channels/teams.py + lab.substrate.approvals + lab.platform.config
        "TEAMS_WEBHOOK_URL",                       # outbound Adaptive Card webhook (unset = not deployed)
        "REDIS_URL",                               # approvals:requests consumer group "teams" + decisions
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # the card's two Action.OpenUrl buttons
        _OTLP,
    ],
    "workload": [                                  # src/lab/workloads/visio_to_archimate/{host,consumer,agents,workflow}.py + lab.workloads.identity + lab.platform.{workflows,runlog,docparse}
        "GATEWAY_URL",                             # the ONLY substrate coordinate (LLM + MCP via the gateway)
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # reported to the human (host.py prints; consumer writes back)
        "REDIS_URL",                               # workflows.py (consume requests) + runlog.py (live node status)
        _OTLP,                                     # lab.platform.otel.tracer; service name is set in code, not from env
        "BA_*", "ARCHITECT_*",                     # identity.agent_headers(): <PREFIX>_CLIENT_ID/SECRET/KEY; BA_MODE, BA_RUN_TIMEOUT,
                                                   # BA_MAX_* (docparse), ARCHITECT_MODE (workflow.py)
        "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE",   # identity.py MSAL authority + scope
        "AGENT_*",                                 # agents.py: AGENT_RESPONSES_STORE / REQUEST_TIMEOUT / MAX_RETRIES / MAX_OUTPUT_TOKENS
        "VISIO_AGENT_MODEL", "VISIO_DIAGRAM", "VISIO_REQUIREMENTS",   # agents.py model; host.py cloud-job inputs (NOT VISIO_TEAM_ID etc.)
        "WF_CONSUMER",                             # consumer.py replica name (spec env)
    ],
    # image services built from nothing in this repo: they get NO .env keys at all
    "redis": [],
    "jaeger": [],
}


def env_for_role(role: str, base: dict, s3: bool = False) -> dict:
    """Select from `base` (parsed .env + layered coordinates) exactly the keys ROLE_ENV[role]
    allows, plus S3_KEYS iff the service is flagged `s3`. Unknown role -> KeyError (never ship a
    full env by accident). Empty values are dropped (Railway would store them as empty strings)."""
    pats = list(ROLE_ENV[role]) + (list(S3_KEYS) if s3 else [])
    return {k: v for k, v in base.items()
            if v != "" and any(fnmatch.fnmatchcase(k, p) for p in pats)}


def _print_env_keys(label: str, env: dict):
    """Audit line: the exact key names (never values) a service receives."""
    print(f"  {label:13} env ({len(env)}): {', '.join(sorted(env))}")


JAEGER_NAME = "local-agent-lab"   # pre-existing Jaeger service (Docker image; NOT built from our repo)


def gql(query, variables=None):
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables or {}}).encode(), headers=H)
    r = json.load(urllib.request.urlopen(req, timeout=90))
    if r.get("errors"):
        raise SystemExit(f"railway error: {[e.get('message') for e in r['errors']]}")
    return r["data"]


def _value(v: str) -> str:
    """One .env value the way the shell sees it: a quoted value keeps everything inside the quotes
    (a `#` in JSON is data); an unquoted one loses a trailing inline note ("value   # note") — a
    URL once shipped WITH its note because Railway passes values verbatim."""
    v = v.strip()
    if v[:1] in ("'", '"'):
        return v.strip("'\"")
    return re.sub(r"\s+#.*$", "", v).strip()


def parse_env(path: str | None = None, cloud: bool = True) -> dict:
    """KEY=value from .env. `cloud=True` (the deploy profile) lets `# CLOUD: KEY=value` comment
    lines WIN over the active machine-local ones; `cloud=False` reads the active lines only (what
    `source .env` gives a local process). Either way `$VAR` / `${VAR}` refs are expanded against
    the parsed values — the shell does this on `source .env`, but Railway passes values verbatim,
    so e.g. ARTIFACTS_URL=$DATABASE_URL would otherwise reach the container as the literal
    "$DATABASE_URL" (psycopg: missing "=" ...). Two passes resolve one level of chaining; unknown
    refs are left untouched. Selection per service is NOT done here — see env_for_role()."""
    active, overrides = {}, {}
    for raw in open(path or os.path.join(ROOT, ".env")):
        line = raw.rstrip("\n")
        m = re.match(r"# CLOUD:\s*([A-Z0-9_]+)=(.*)$", line)
        if m:
            # drop a trailing inline comment first, then quotes (unchanged CLOUD-line semantics)
            overrides[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"")
            continue
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if re.match(r"^[A-Z0-9_]+$", k):
            active[k] = _value(v)
    if cloud:
        active.update(overrides)                           # cloud values override local

    def expand(v):
        return re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", lambda m: active.get(m.group(1), m.group(0)), v)
    for _ in range(2):
        active = {k: expand(v) for k, v in active.items()}
    return active


def load_env_for_cloud(path: str | None = None) -> dict:
    """The deploy profile of .env (`# CLOUD:` wins, $VAR expanded, empty values dropped). This is
    the POOL a service is selected from — env_for_role() decides what each one actually gets, so
    management keys (RAILWAY_*, NEON_*, OCI_*, provisioning ids) never ship without a drop-list."""
    return {k: v for k, v in parse_env(path, cloud=True).items() if v != ""}


def services():
    d = gql('query($p:String!){ project(id:$p){ services{ edges{ node{ id name } } } } }', {"p": PROJECT})
    return {e["node"]["name"]: e["node"]["id"] for e in d["project"]["services"]["edges"]}


def ensure_service(name):
    existing = services()
    if name in existing:
        return existing[name], False
    create = {"projectId": PROJECT, "name": name, "source": _source()}
    if BUILD_MODE != "image":
        create["branch"] = BRANCH                      # a repo service tracks a branch; an image has a tag
    d = gql('mutation($in:ServiceCreateInput!){ serviceCreate(input:$in){ id } }', {"in": create})
    return d["serviceCreate"]["id"], True


# --- the substrate's own Redis: an IMAGE service (like Jaeger), not built from the repo ---
# Replaces Redis Cloud for the cloud tier (Sep 2026): LiteLLM opens two 50-connection pools
# (cache + router, redis-py BlockingConnectionPool default) plus pub/sub subscribers per gateway,
# which blew Redis Cloud's 30-client free-tier cap ("max number of clients reached"), and
# co-locating it removes the ~180 ms cross-region RTT (+3.8 s per gateway request measured).
# `.env` points the cloud tier at it via `# CLOUD: REDIS_URL=redis://redis.railway.internal:6379/0`
# (litellm falls back to REDIS_URL when REDIS_HOST/PORT are absent — verified); local lab.sh keeps
# brew Redis. Limiter/budget state + the approval streams live here, so it deploys FIRST.
REDIS_NAME = "redis"
REDIS_IMAGE = "redis:7-alpine"
# --bind 0.0.0.0 :: is REQUIRED: Railway private DNS (*.railway.internal) is IPv6-only and Redis's
# default v4-only bind would be unreachable from the gateway (the same bug class as the gateway's
# own IPv4-edge / IPv6-healthcheck split). No password on the private network -> --protected-mode
# no. appendonly + the /data volume let the approval streams survive a restart.
REDIS_CMD = "redis-server --bind 0.0.0.0 :: --protected-mode no --appendonly yes --dir /data"


def ensure_image_service(name, image):
    existing = services()
    if name in existing:
        return existing[name], False
    d = gql('mutation($in:ServiceCreateInput!){ serviceCreate(input:$in){ id } }',
            {"in": {"projectId": PROJECT, "name": name, "source": {"image": image}}})
    return d["serviceCreate"]["id"], True


def ensure_volume(sid, mount_path):
    """Attach a persistent volume at mount_path — idempotent (never creates a second one)."""
    try:
        d = gql('query($p:String!){ project(id:$p){ volumes{ edges{ node{ id volumeInstances{ '
                'edges{ node{ serviceId mountPath } } } } } } } }', {"p": PROJECT})
        for e in d["project"]["volumes"]["edges"]:
            for vi in e["node"]["volumeInstances"]["edges"]:
                if vi["node"]["serviceId"] == sid and vi["node"]["mountPath"] == mount_path:
                    return False                                   # already attached
    except SystemExit as e:
        print(f"  (volume lookup unavailable: {str(e)[:60]} — attempting create)")
    gql('mutation($in:VolumeCreateInput!){ volumeCreate(input:$in){ id } }',
        {"in": {"projectId": PROJECT, "environmentId": ENV, "serviceId": sid, "mountPath": mount_path}})
    return True


def ensure_redis():
    sid, created = ensure_image_service(REDIS_NAME, REDIS_IMAGE)
    print(f"  {REDIS_NAME:13} {'created' if created else 'exists '} {sid[:8]}  ({REDIS_IMAGE})")
    gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
        {"s": sid, "e": ENV, "in": {"source": {"image": REDIS_IMAGE}, "startCommand": REDIS_CMD,
                                    "healthcheckPath": "", "restartPolicyType": "ALWAYS"}})
    if ensure_volume(sid, "/data"):
        print(f"  {REDIS_NAME:13} volume attached at /data")
    deploy(sid, latest=False)                                  # image service: no repo commit to fetch
    print(f"  {REDIS_NAME:13} deploying ({REDIS_CMD.split()[0]} dual-stack bind, appendonly)")
    return sid


# --- the upload store: a Railway Bucket (S3-compatible; Azure Blob on the target) ---
BUCKET_NAME = "lab-uploads"


def _patch_env_cloud(pairs):
    """Write/replace `# CLOUD: KEY=value` lines in .env (the loader honours them for every service;
    configure() then hands S3_* only to services flagged "s3")."""
    p = os.path.join(ROOT, ".env")
    s = open(p).read()
    for k, v in pairs:
        line = f"# CLOUD: {k}={v}"
        if re.search(rf"^# CLOUD: {k}=", s, re.M):
            s = re.sub(rf"^# CLOUD: {k}=.*$", line, s, flags=re.M)
        else:
            s = s.rstrip("\n") + "\n" + line + "\n"
    open(p, "w").write(s)


def ensure_bucket():
    """Create the project's upload bucket once and record its S3 credentials as # CLOUD: lines.
    Railway API (verified by introspection): bucketCreate(projectId, environmentId, name) and
    query bucketS3Credentials(bucketId) -> endpoint/region/bucketName/accessKeyId/secretAccessKey/
    urlStyle. Manual fallback: dashboard -> Bucket -> copy the credentials into the same lines."""
    d = gql('query($p:String!){ project(id:$p){ buckets{ edges{ node{ id name } } } } }', {"p": PROJECT})
    have = {e["node"]["name"]: e["node"]["id"] for e in d["project"]["buckets"]["edges"]}
    bid = have.get(BUCKET_NAME)
    if not bid:
        bid = gql('mutation($in:BucketCreateInput!){ bucketCreate(input:$in){ id } }',
                  {"in": {"projectId": PROJECT, "environmentId": ENV, "name": BUCKET_NAME}})["bucketCreate"]["id"]
        print(f"  bucket {BUCKET_NAME} created {bid[:8]}")
    else:
        print(f"  bucket {BUCKET_NAME} exists  {bid[:8]}")
    c = gql('query($b:String!){ bucketS3Credentials(bucketId:$b){ endpoint region bucketName accessKeyId secretAccessKey urlStyle } }',
            {"b": bid})["bucketS3Credentials"]
    _patch_env_cloud([("RAILWAY_BUCKET_ID", bid),
                      ("S3_ENDPOINT", c["endpoint"]), ("S3_REGION", c.get("region") or ""),
                      ("S3_ACCESS_KEY_ID", c["accessKeyId"]), ("S3_SECRET_ACCESS_KEY", c["secretAccessKey"]),
                      ("S3_URL_STYLE", (c.get("urlStyle") or "path").lower()),
                      ("UPLOADS_URL", f"s3://{c['bucketName']}/uploads")])
    print(f"  .env: # CLOUD: S3_* + UPLOADS_URL=s3://{c['bucketName']}/uploads written "
          f"(endpoint {c['endpoint']}); applies to review + storage-mcp on the next `substrate up`")
    return bid


def bucket_status():
    d = gql('query($p:String!){ project(id:$p){ buckets{ edges{ node{ id name } } } } }', {"p": PROJECT})
    for e in d["project"]["buckets"]["edges"]:
        n = e["node"]
        try:
            i = gql('query($b:String!){ bucketInstanceDetails(bucketId:$b){ objectCount sizeBytes } }',
                    {"b": n["id"]})["bucketInstanceDetails"]
            print(f"  {n['name']:13} {n['id'][:8]}  objects={i.get('objectCount')} bytes={i.get('sizeBytes')}")
        except SystemExit as ex:
            print(f"  {n['name']:13} {n['id'][:8]}  ({ex})")
    if not d["project"]["buckets"]["edges"]:
        print("  (no buckets — run: railway.py bucket up)")


def substrate_env(name, spec, base_env) -> dict:
    """The exact variables substrate service `name` receives: the substrate coordinates layered on
    the .env pool, then the role allowlist (S3_KEYS only for services flagged "s3"), then the
    service's own fixed overrides. Pure — used by `up` (to upsert) and `env` (to audit offline)."""
    env = dict(base_env)
    env["BIND_HOST"] = "::"                                 # IPv6 for Railway private networking
    env["ADOIT_MCP_URL"] = "http://adoit-mcp.railway.internal:9100/mcp"
    env["SEMANTIC_MCP_URL"] = "http://semantic-mcp.railway.internal:9200/mcp"
    env["STORAGE_MCP_URL"] = "http://storage-mcp.railway.internal:9300/mcp"
    env["WORKFLOW_MCP_URL"] = "http://workflow-mcp.railway.internal:9400/mcp"
    env["GATEWAY_URL"] = "http://gateway.railway.internal:4000"
    env = env_for_role(name, env, s3=bool(spec.get("s3")))  # bucket credentials: review + storage-mcp ONLY
    env.update(spec.get("env", {}))
    return env


def configure(sid, name, spec, base_env):
    env = substrate_env(name, spec, base_env)
    _print_env_keys(name, env)
    gql('mutation($in:VariableCollectionUpsertInput!){ variableCollectionUpsert(input:$in) }',
        {"in": {"projectId": PROJECT, "environmentId": ENV, "serviceId": sid,
                "variables": env, "replace": True, "skipDeploys": True}})
    # Always send healthcheckPath — empty string CLEARS any stale probe. The gateway must have NO
    # healthcheck (its IPv6 probe fights the IPv4 0.0.0.0 bind and kills the deploy); see SUBSTRATE.
    # restartPolicyType is sent for the same reason as healthcheckPath: the table must fully DESCRIBE
    # the service instance, so a spec that loses its "restart" resets the service instead of keeping a
    # stale policy. ON_FAILURE is Railway's default -> no change for the roles that declare none; the
    # approval channels are long-lived loops and declare ALWAYS.
    upd = {**_build_input(spec["cmd"]), "startCommand": spec["cmd"],
           "healthcheckPath": spec.get("health", ""),
           "restartPolicyType": spec.get("restart", "ON_FAILURE")}
    gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
        {"s": sid, "e": ENV, "in": upd})
    if spec.get("port"):
        try:
            gql('mutation($in:ServiceDomainCreateInput!){ serviceDomainCreate(input:$in){ domain } }',
                {"in": {"environmentId": ENV, "serviceId": sid, "targetPort": spec["port"]}})
        except SystemExit as e:
            if "already" not in str(e).lower():
                print(f"  domain note ({e})")


def domain_of(sid):
    d = gql('query($s:String!){ service(id:$s){ serviceInstances{ edges{ node{ '
            'domains{ serviceDomains{ domain } } } } } } }', {"s": sid})
    for e in d["service"]["serviceInstances"]["edges"]:
        for sd in e["node"]["domains"]["serviceDomains"]:
            return sd["domain"]
    return None


def deploy(sid, latest=True):
    latest = latest and BUILD_MODE != "image"          # image services have no commit to fetch
    # latestCommit:true makes Railway FETCH the newest commit of the tracked branch (without a
    # GitHub webhook it otherwise rebuilds the snapshot from service-creation time). Image services
    # (Jaeger) have no repo — plain redeploy.
    q = ('mutation($s:String!,$e:String!){ serviceInstanceDeploy(serviceId:$s, environmentId:$e, latestCommit:true) }'
         if latest else
         'mutation($s:String!,$e:String!){ serviceInstanceDeploy(serviceId:$s, environmentId:$e) }')
    gql(q, {"s": sid, "e": ENV})


def latest(sid):
    d = gql('query($s:String!,$e:String!){ deployments(first:1, input:{serviceId:$s, environmentId:$e}){ '
            'edges{ node{ id status } } } }', {"s": sid, "e": ENV})["deployments"]["edges"]
    return d[0]["node"] if d else {"id": None, "status": "NONE"}


def ensure_jaeger(ids):
    """Observability is part of the substrate: make sure the pre-existing Jaeger service (an image
    service, so redeploy-only — never reconfigured) is up so the substrate's OTEL has a sink."""
    sid = ids.get(JAEGER_NAME)
    if not sid:
        print(f"  {'jaeger':13} not in project — deploy it via lab.sh (remote tracing)")
        return
    if latest(sid)["status"] != "SUCCESS":
        deploy(sid, latest=False)                          # image service — no repo commit to fetch
        print(f"  {'jaeger':13} redeploying (observability sink for the substrate)")
    else:
        print(f"  {'jaeger':13} already up")


def substrate_up():
    base = load_env_for_cloud()
    table = substrate_services(base)                       # + the approval channels that are configured
    print(f"deploying substrate ({len(table)} services + redis + jaeger) from "
          f"{IMAGE if BUILD_MODE == 'image' else f'{REPO}@{BRANCH} (repo build)'}")
    for name in CHANNELS:
        if name not in table:
            print(f"  {name:13} skipped  (not configured: {', '.join(CHANNELS[name]['requires'])})")
    ensure_redis()                                         # first: gateway/MCP/review depend on it
    for name, spec in table.items():
        sid, created = ensure_service(name)
        print(f"  {name:13} {'created' if created else 'exists '} {sid[:8]}")
        configure(sid, name, spec, base)
        deploy(sid)
    ensure_jaeger(services())                              # observability is part of the substrate
    print("\ntriggered builds. Public URLs (once healthy):")
    ids = services()
    for name in ("gateway", "review"):
        print(f"  {name:8} https://{domain_of(ids[name]) or '(pending)'}")
    print(f"  jaeger   {os.environ.get('JAEGER_UI_URL', '(see .env)')}")
    print("Watch builds: railway dashboard, or `python deploy/railway.py substrate status`.")


def substrate_env_report():
    """OFFLINE audit: the exact key names each substrate service receives from the current .env
    (what the next `substrate up` upserts). Values are never printed. No `.env` -> an empty pool
    (the read-side commands work on a box that only exports the Railway credentials; `up`, which
    must actually configure the services, still reads it strictly)."""
    base = deploy_profile()
    print(f"substrate env allowlist (from .env, `# CLOUD:` profile; {len(base)} keys in the pool)")
    for name in (REDIS_NAME, JAEGER_NAME):
        _print_env_keys("jaeger" if name == JAEGER_NAME else name, {})
    for name, spec in substrate_services(base).items():
        _print_env_keys(name, substrate_env(name, spec, base))


def substrate_status():
    ids = services()
    for name in substrate_names(deploy_profile(), ids):
        sid = ids.get(name)
        label = "jaeger" if name == JAEGER_NAME else name
        if not sid:
            print(f"  {label:13} (not created)")
            continue
        st = latest(sid)["status"]
        dom = domain_of(sid)
        print(f"  {label:13} {st.lower():10} {('https://'+dom) if dom else '(internal)'}")
    print()
    substrate_env_report()


def substrate_down():
    ids = services()
    # include Redis + Jaeger: tearing the substrate down stops its state + observability too
    # (metered). The Redis volume persists, so approval streams survive an up/down cycle.
    for name in substrate_names(deploy_profile(), ids):
        sid = ids.get(name)
        label = "jaeger" if name == JAEGER_NAME else name
        if not sid:
            continue
        d = latest(sid)
        if d["status"] == "SUCCESS":
            gql('mutation($id:String!){ deploymentRemove(id:$id) }', {"id": d["id"]})
            print(f"  {label:13} stopped (config/variables/domain kept)")
        else:
            print(f"  {label:13} already {d['status'].lower()}")


# --- workloads: each business process is its OWN service, deployed independently ON the substrate ---
# The two-tier contract: a workload reaches the substrate ONLY through the gateway's PUBLIC domain
# plus the shared Redis (streams) and the tracing sink from .env — see ROLE_ENV["workload"]; never
# Neon, the bucket, the MCP servers (internal to the substrate) or another workload; cross-workflow coupling goes via events
# (Redis Streams) or A2A through the gateway. The public URL is the door by design (and the gateway
# binds IPv4 — see SUBSTRATE — so its *.railway.internal name would not be reachable anyway).
WORKLOADS = {
    # The normal cloud shape: a LONG-LIVED host that consumes `workflow:requests` (published by the
    # review app's Submit page) and runs the workflow per event. Inputs arrive as art:// refs and are
    # read through the gateway's storage-mcp; this container holds no store credentials.
    "visio": {
        "service": "wf-visio",
        "cmd": "python -m lab.workloads.visio_to_archimate.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),   # what workload_status reads from the logs
    },
    # The one-shot job (demo / smoke): run to completion on the generated fixture, or on real
    # uploaded refs via `# CLOUD: VISIO_DIAGRAM=` / `VISIO_REQUIREMENTS=` in .env.
    # Railway has no volume mounts and both fixture inputs are git-ignored GENERATED files
    # (var/out/architecture/lab_model.json, then the .vsdx built from it): generate both at start.
    # `sh -c` is REQUIRED: Railway execs a Dockerfile start command without a shell, so a bare
    # `a && b && c` runs only `a` (the rest arrives as ignored argv) and exits 0 — verified twice.
    "visio-job": {
        "service": "wf-visio-job",
        "cmd": "sh -c 'python scripts/lab_model.py && "
               "python -m lab.workloads.visio_to_archimate.make_sample_vsdx && "
               "python -m lab.workloads.visio_to_archimate.host'",
        "restart": "NEVER",   # exit 0 means done, not crashed; re-run = redeploy
        "env": {"AGENT_RESPONSES_STORE": "false"},
    },
}


def _public(ids, name):
    d = domain_of(ids[name]) if ids.get(name) else None
    return f"https://{d}" if d else None


def workload_env(spec, base_env, gw, review=None) -> dict:
    """The exact variables a workload receives. The two-tier isolation invariant is the ALLOWLIST
    itself (ROLE_ENV["workload"]): no MCP server addresses (it reaches tools only via the gateway),
    no store credentials (inputs are art:// refs read through storage-mcp, its spec goes to
    semantic-mcp), no gateway/ADOIT/bucket secrets. Pure — used by `up` and `env`."""
    env = dict(base_env)
    env["GATEWAY_URL"] = gw                                     # the ONLY substrate coordinate
    env["REVIEW_APP_URL"] = review or env.get("REVIEW_APP_URL", "")
    env = env_for_role("workload", env)
    env.update(spec.get("env", {}))
    return env


def configure_workload(sid, spec, base_env, ids):
    gw = _public(ids, "gateway")
    if not gw:
        raise SystemExit("substrate gateway has no public domain — deploy the substrate first")
    env = workload_env(spec, base_env, gw, _public(ids, "review"))
    _print_env_keys(spec["service"], env)
    gql('mutation($in:VariableCollectionUpsertInput!){ variableCollectionUpsert(input:$in) }',
        {"in": {"projectId": PROJECT, "environmentId": ENV, "serviceId": sid,
                "variables": env, "replace": True, "skipDeploys": True}})
    gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
        {"s": sid, "e": ENV, "in": {**_build_input(spec["cmd"]), "startCommand": spec["cmd"],
                                    "healthcheckPath": "",        # a job serves nothing to probe
                                    "restartPolicyType": spec.get("restart", "ON_FAILURE")}})
    return gw


def workload_up(name):
    spec = WORKLOADS[name]
    ids = services()
    base = load_env_for_cloud()
    sid, created = ensure_service(spec["service"])
    print(f"deploying workload '{name}' as service {spec['service']} "
          f"({'created' if created else 'exists '} {sid[:8]}) from "
          f"{IMAGE if BUILD_MODE == 'image' else f'{REPO}@{BRANCH} (repo build)'}")
    gw = configure_workload(sid, spec, base, ids)
    deploy(sid)
    print(f"  references substrate gateway {gw}; restart={spec.get('restart')}; no ingress (job)")
    print(f"  watch: python deploy/railway.py workload {name} status   (logs: Railway dashboard)")


def workload_env_report(name):
    """OFFLINE audit: the exact key names workload `name` receives (gateway/review URLs shown as
    placeholders — the real public domains are resolved at `up`)."""
    spec = WORKLOADS[name]
    env = workload_env(spec, load_env_for_cloud(), "https://<gateway public domain>", "https://<review public domain>")
    print(f"workload '{name}' env allowlist (from .env, `# CLOUD:` profile)")
    _print_env_keys(spec["service"], env)


def workload_status(name):
    spec = WORKLOADS[name]
    sid = services().get(spec["service"])
    if not sid:
        print(f"  {spec['service']:13} (not created)")
        return
    d = latest(sid)
    # Railway reports a NEVER-restart job as SUCCESS whether it exited 0 or crashed (verified), so
    # the deployment status is NOT the result — the run's own log markers are authoritative. A
    # long-lived consumer is judged the same way: "consumer ready" + its last "request … done|failed".
    verdict = "no logs yet"
    try:
        lg = gql('query($d:String!){ deploymentLogs(deploymentId:$d, limit:300){ message } }', {"d": d["id"]})
        msgs = [l["message"] for l in lg["deploymentLogs"]]
        blob = "\n".join(msgs)
        if spec.get("restart") == "ALWAYS":
            last = next((m for m in reversed(msgs) if m.startswith("request ") and
                         (" done" in m or " failed" in m)), None)
            verdict = ("READY — " if "consumer ready" in blob else "starting — ") + (last.strip() if last else "no runs yet")
        elif "approval requested:" in blob:
            verdict = "RAN TO COMPLETION — " + next(m for m in msgs if "approval requested:" in m).strip()
        elif "Traceback" in blob:
            err = next((m for m in reversed(msgs) if m.strip() and not m.startswith(" ")), "see logs")
            verdict = "FAILED — " + err.strip()[:140]
        elif msgs:
            verdict = "running / in progress"
    except (Exception, SystemExit):       # gql() aborts with SystemExit: a failed log fetch is not a failed run
        pass
    print(f"  {spec['service']:13} {d['status'].lower():10} {verdict}")
    print()
    workload_env_report(name)


def workload_down(name):
    spec = WORKLOADS[name]
    sid = services().get(spec["service"])
    if not sid:
        return
    d = latest(sid)
    if d["status"] in ("SUCCESS", "DEPLOYING", "BUILDING"):
        gql('mutation($id:String!){ deploymentRemove(id:$id) }', {"id": d["id"]})
        print(f"  {spec['service']:13} stopped (config/variables kept)")
    else:
        print(f"  {spec['service']:13} already {d['status'].lower()}")


if __name__ == "__main__":
    usage = ("usage: railway.py substrate up|down|status|env\n"
             "       railway.py workload <" + "|".join(WORKLOADS) + "> up|down|status|env\n"
             "       railway.py bucket up|status      (upload store: create once, credentials -> .env # CLOUD:)\n"
             "       (`env` = offline audit of the exact key names each service receives; no Railway call)")
    tier = sys.argv[1] if len(sys.argv) > 1 else ""
    cmd = (sys.argv[3] if tier == "workload" else sys.argv[2]) if len(sys.argv) > (3 if tier == "workload" else 2) else "status"
    if cmd != "env":
        _require_railway()                                 # every other command talks to Railway
    if tier == "substrate":
        {"up": substrate_up, "down": substrate_down, "status": substrate_status, "env": substrate_env_report}[cmd]()
    elif tier == "bucket":
        {"up": ensure_bucket, "status": bucket_status}[cmd]()
    elif tier == "workload" and len(sys.argv) > 2 and sys.argv[2] in WORKLOADS:
        {"up": workload_up, "down": workload_down, "status": workload_status,
         "env": workload_env_report}[cmd](sys.argv[2])
    else:
        raise SystemExit(usage)
