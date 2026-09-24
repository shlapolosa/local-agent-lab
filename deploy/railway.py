"""Deploy the lab to Railway as two independent tiers (see deploy/README.md):

  substrate  — the shared plane: redis (internal), gateway (public), semantic-mcp + adoit-mcp +
               storage-mcp + workflow-frontdoor + graph-mcp (internal), review (public), plus every approval CHANNEL
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
import json
import os
import re
import sys
import time
import urllib.request

# The shared topology and deploy gate live beside this file (deploy/ is scripts, not a package, and
# is loaded by path from tests and scripts), so its own directory is put on the import path once, here.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topology  # noqa: E402 — ROOT is read through the module at call time, so a test can repoint it
from gate import _require_quiet  # noqa: E402
from topology import (  # noqa: E402,F401 — re-exported: tests and scripts address these as railway.<name>
    BRANCH, CHANNELS, EMBED_MODEL, EMBED_NAME, IMAGE, IMAGE_TAG, JAEGER_NAME, MAX_REPLICAS, REDIS_NAME,
    REPO, ROLE_ENV, S3_KEYS, SUBSTRATE, WORKLOAD_ENV, WORKLOADS, _OTLP, _head_tag, _print_env_keys,
    _value, deploy_profile, embedder_enabled, env_for_role, load_env_for_cloud, parse_env,
    replica_services, substrate_names, substrate_services, workload_env,
)


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


def _require_railway():
    missing = [k for k in ("RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing {', '.join(missing)} — set -a && source .env && set +a first")



GQL_ATTEMPTS = 3           # a deploy is many calls; one blip must not leave the cluster half-done
GQL_BACKOFF_S = 2.0


def gql(query, variables=None):
    """One Railway API call, RETRIED on a transport failure but never on a rejection.

    A deploy is dozens of these, and a single dropped read used to fail the whole job: CD marked the
    release red after the substrate had rolled and before the workloads had, leaving the cluster
    running two commits — the exact skew `substrate versions` exists to catch, caused by the tool
    meant to prevent it. Measured: `TimeoutError: The read operation timed out`, mid-deploy, with
    nothing wrong on either side.

    Only TRANSPORT failures are retried. A GraphQL `errors` reply is Railway saying no — repeating it
    would just say no again, more slowly, and could repeat a mutation that actually landed.
    """
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(1, GQL_ATTEMPTS + 1):
        try:
            r = json.load(urllib.request.urlopen(
                urllib.request.Request(API, data=body, headers=H), timeout=90))
            break
        except (TimeoutError, urllib.error.URLError, ConnectionError, json.JSONDecodeError) as e:
            if attempt == GQL_ATTEMPTS:
                raise SystemExit(f"railway unreachable after {GQL_ATTEMPTS} attempts: "
                                 f"{type(e).__name__}: {e}") from e
            print(f"  railway {type(e).__name__} — retrying ({attempt}/{GQL_ATTEMPTS - 1})",
                  file=sys.stderr, flush=True)
            time.sleep(GQL_BACKOFF_S * attempt)
    if r.get("errors"):
        raise SystemExit(f"railway error: {[e.get('message') for e in r['errors']]}")
    return r["data"]


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
REDIS_IMAGE = "redis:7-alpine"
# --bind 0.0.0.0 :: is REQUIRED: Railway private DNS (*.railway.internal) is IPv6-only and Redis's
# default v4-only bind would be unreachable from the gateway (the same bug class as the gateway's
# own IPv4-edge / IPv6-healthcheck split). No password on the private network -> --protected-mode
# no. appendonly + the /data volume let the approval streams survive a restart.
REDIS_CMD = "redis-server --bind 0.0.0.0 :: --protected-mode no --appendonly yes --dir /data"

# --- the corpus's embedding model: the substrate's OWN, beside Redis (10 Sep 2026) ---
# Ollama Cloud, OpenRouter and Anthropic serve no embedding model and the OpenAI account had no
# credit, so the model the reference corpus indexes and searches with runs HERE: an Ollama image,
# internal only (no domain, no credential — the private network is the trust boundary, as for
# Redis), ~300 MB resident, the pulled weights on a volume so a restart does not re-download. The
# gateway's model_list points at it through EMBED_URL, so switching to a vendor later is that one
# entry and this service, never a workload. `[::]`: Railway private DNS is IPv6-only. The pull runs
# at every start and is a no-op against the volume; `sh -c` because a start command is exec'd
# without a shell (gotcha (1) in CLAUDE.md).
EMBED_IMAGE = "ollama/ollama:0.34.0"
# `|| exit 1`: a pull that fails must take the service down (ALWAYS restarts it, loudly in its
# logs) rather than leave a healthy-looking server that refuses every search at query time.
EMBED_CMD = (f"sh -c 'OLLAMA_HOST=[::]:11434 OLLAMA_KEEP_ALIVE=-1 OLLAMA_NUM_PARALLEL=4 ollama serve & sleep 5; "
             f"ollama pull {EMBED_MODEL} || exit 1; wait'")


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


def ensure_embedder():
    sid, created = ensure_image_service(EMBED_NAME, EMBED_IMAGE)
    print(f"  {EMBED_NAME:13} {'created' if created else 'exists '} {sid[:8]}  ({EMBED_IMAGE})")
    gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
        {"s": sid, "e": ENV, "in": {"source": {"image": EMBED_IMAGE}, "startCommand": EMBED_CMD,
                                    "healthcheckPath": "", "restartPolicyType": "ALWAYS"}})
    if ensure_volume(sid, "/root/.ollama"):
        print(f"  {EMBED_NAME:13} volume attached at /root/.ollama")
    deploy(sid, latest=False)
    print(f"  {EMBED_NAME:13} deploying ({EMBED_MODEL}, dual-stack bind, weights on the volume)")
    return sid


# --- the upload store: a Railway Bucket (S3-compatible; Azure Blob on the target) ---
BUCKET_NAME = "lab-uploads"


def _patch_env_cloud(pairs):
    """Write/replace `# CLOUD: KEY=value` lines in .env (the loader honours them for every service;
    configure() then hands S3_* only to services flagged "s3")."""
    p = os.path.join(topology.ROOT, ".env")
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
    env["WORKFLOW_MCP_URL"] = "http://workflow-frontdoor.railway.internal:9400/mcp"
    env["GRAPH_MCP_URL"] = "http://graph-mcp.railway.internal:9500/mcp"
    env["SPEECH_MCP_URL"] = "http://speech-mcp.railway.internal:9600/mcp"
    env["REFERENCE_MCP_URL"] = "http://reference-mcp.railway.internal:9700/mcp"
    env["DECISION_MCP_URL"] = "http://decision-mcp.railway.internal:9800/mcp"
    env["VALUATION_MCP_URL"] = "http://valuation-mcp.railway.internal:9900/mcp"
    env["WORKFLOW_API_URL"] = "http://workflow-frontdoor.railway.internal:9400/api"
    env["GATEWAY_URL"] = "http://gateway.railway.internal:4000"
    # The relevance stores' provider (litellm-config.yaml vector_store_registry): an ORIGIN — the
    # client appends /v1/vector_stores/<id>/search — and the bearer reference-mcp expects.
    env["PG_VECTOR_API_BASE"] = "http://reference-mcp.railway.internal:9700"
    env["PG_VECTOR_API_KEY"] = env.get("MCP_SHARED_SECRET", "")
    env["EMBED_URL"] = f"http://{EMBED_NAME}.railway.internal:11434"   # the gateway's embedding model
    env = env_for_role(name, env, s3=bool(spec.get("s3")))  # bucket credentials: only services flagged "s3"
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


def image_of(sid):
    """The image the service instance is actually configured to run (None for a repo-built service)."""
    d = gql('query($s:String!){ service(id:$s){ serviceInstances{ edges{ node{ source{ image } } } } } }',
            {"s": sid})
    for e in d["service"]["serviceInstances"]["edges"]:
        src = e["node"].get("source") or {}
        if src.get("image"):
            return src["image"]
    return None


# A service with no live deployment runs nothing, so it has no build to disagree about. Reporting one
# as a version mismatch is a false alarm, and a check that cries wolf is a check people stop reading.
STOPPED = {"REMOVED", "CRASHED", "FAILED", "NONE"}

BUILD_RE = re.compile(r"build=([0-9a-f]{7,40}|dev)")


def running_build(sid):
    """The commit a service's RUNNING container reports, from its own startup line, or None.

    The complement to `image_of`, and the half that cannot be faked. `image_of` reports what Railway
    was ASKED to run; this reports what the process that is actually serving says it is. They agree
    only when the tag is immutable and the service has restarted onto it — and the whole reason this
    exists is that they can silently disagree, which is how a workload came to call a tool the
    gateway had renamed while every tag read `:main`.
    """
    d = latest(sid)
    if not d.get("id"):
        return None
    try:
        lg = gql('query($d:String!){ deploymentLogs(deploymentId:$d, limit:300){ message } }',
                 {"d": d["id"]})
    except SystemExit:
        return None
    for m in lg["deploymentLogs"]:
        found = BUILD_RE.search(m.get("message") or "")
        if found:
            return found.group(1)
    return None


def version_report():
    """Print, per service, the image it was ASKED to run and the build it SAYS it is running.

    Returns True on any disagreement. Two different failures show up here and neither is visible
    from a tag alone: services deployed from different commits, and a service whose tag moved under
    it but which never restarted, so it is still serving the previous build.
    """
    ids = services()
    ours = f"ghcr.io/{REPO}:"
    builds, stale = {}, []
    print(f"  {'service':22} {'asked to run':28} running")
    for name, sid in sorted(ids.items()):
        img = image_of(sid)
        if img is None or not img.startswith(ours):
            continue                                   # repo-built, or a third-party image
        if latest(sid).get("status") in STOPPED:
            continue                                   # runs nothing: no build to disagree about
        tag = img.split(":", 1)[1]
        build = running_build(sid)
        print(f"  {name:22} {tag:28} {build or '(no build line in its logs)'}")
        if build and build != "dev":
            builds.setdefault(build[:7], []).append(name)
            if tag.startswith("sha-") and not build.startswith(tag[4:]):
                stale.append((name, tag, build[:7]))
    bad = False
    if len(builds) > 1:
        bad = True
        print("\n  MISMATCH — these services are RUNNING different commits:")
        for b, names in sorted(builds.items()):
            print(f"    {b}  <- {', '.join(names)}")
    for name, tag, build in stale:
        bad = True
        print(f"\n  STALE — {name} is configured for {tag} but is still serving {build}: "
              "it has not restarted onto the image it was given.")
    if not bad:
        print("\n  every service runs the same build" if builds else
              "\n  no service reported a build — an image built before LAB_BUILD_SHA existed")
    return bad


def release(wait_s: int = 600):
    """Roll every EXISTING service onto THIS commit's image. Returns True on any problem.

    What CD runs, and deliberately the smaller half of `substrate up`: it sets the image and
    redeploys. It does NOT create services and does NOT write environment variables.

    That split is the point. `configure()` pushes credentials out of `.env` — Neon, Entra, Graph,
    the LiteLLM master key — and a CD job that did the same would need all of them in GitHub
    Actions, which is a much larger blast radius than shipping code deserves. So **CD ships CODE and
    a human ships CONFIGURATION**: a new service, a new secret or a changed grant is a deliberate
    `substrate up` from a machine that has `.env`. A service that does not exist yet is skipped with
    a line saying so, because creating it without its env would produce a container that starts and
    then fails on its first call.
    """
    _require_quiet(deploy_profile())
    ids = services()
    names = [n for n in substrate_names(deploy_profile(), ids)
             if n not in (REDIS_NAME, EMBED_NAME, JAEGER_NAME)]
    names += [w["service"] for w in WORKLOADS.values()]
    print(f"releasing {IMAGE}")
    rolled, missing = [], []
    for name in names:
        sid = ids.get(name)
        if not sid:
            missing.append(name)
            # NOT a failure. A one-shot job service (`wf-visio-job`) exists only while a job is
            # running, and a substrate service that has never been created needs env this job
            # deliberately does not hold. Failing on either would make CD red on every green push,
            # and a check that is always red is a check nobody reads.
            print(f"  {name:22} skipped — not created (needs `substrate up` from a machine with .env)")
            continue
        gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
            'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
            {"s": sid, "e": ENV, "in": {"source": {"image": IMAGE}}})
        deploy(sid, latest=False)
        rolled.append((name, sid))
        print(f"  {name:22} rolling")
    if not rolled:
        print("\n  nothing to release")
        return True
    print(f"\n  waiting up to {wait_s}s for {len(rolled)} service(s) to come up")
    pending, deadline = list(rolled), time.time() + wait_s
    while pending and time.time() < deadline:
        time.sleep(10)
        for name, sid in list(pending):
            st = latest(sid).get("status")
            if st in ("SUCCESS", "CRASHED", "FAILED"):
                print(f"  {name:22} {st}")
                pending.remove((name, sid))
    for name, _sid in pending:
        print(f"  {name:22} STILL DEPLOYING after {wait_s}s")
    # A release FAILS only on something that is actually wrong with THIS release: a service that
    # crashed on the new image, or one still deploying when the wait ran out. `missing` is reported
    # above and is not a failure — see the note there.
    bad = bool(pending)
    for name, sid in rolled:
        if latest(sid).get("status") in ("CRASHED", "FAILED"):
            print(f"  {name:22} FAILED on this image")
            bad = True
    if missing:
        print(f"\n  not released (never created): {', '.join(missing)}")
    print("\n  release " + ("INCOMPLETE" if bad else "complete"))
    return bad


def image_report():
    """Print the image every service runs and return True if they DISAGREE.

    The version skew that broke a cloud run was invisible: `substrate up` and `workload … up` are
    separate commands, both pulled a mutable tag, and nothing showed that one had moved on. This is
    the missing instrument — run it after any deploy, and before believing a bug is a code bug.
    """
    ids = services()
    ours = f"ghcr.io/{REPO}:"
    seen = {}
    for name, sid in sorted(ids.items()):
        img = image_of(sid)
        if img is None:
            continue                                   # repo-built service: no image to compare
        if latest(sid).get("status") in STOPPED:
            print(f"  {name:15} {img}  (not running)")
            continue                                   # a stopped service runs no build at all
        print(f"  {name:15} {img}")
        if img.startswith(ours):                       # third-party images (redis, jaeger) run their
            seen.setdefault(img, []).append(name)      # OWN versions on purpose — never a mismatch
    if len(seen) > 1:
        print("\n  MISMATCH — these services run different builds of THIS repo:")
        for img, names in sorted(seen.items()):
            print(f"    {img}  <- {', '.join(names)}")
        print("  Redeploy the stragglers (substrate up / workload <name> up) so every service "
              "runs one image.")
        return True
    return False


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
    _require_quiet(base)
    table = substrate_services(base)                       # + the approval channels that are configured
    print(f"deploying substrate ({len(table)} services + redis + jaeger) from "
          f"{IMAGE if BUILD_MODE == 'image' else f'{REPO}@{BRANCH} (repo build)'}")
    for name in CHANNELS:
        if name not in table:
            print(f"  {name:13} skipped  (not configured: {', '.join(CHANNELS[name]['requires'])})")
    ensure_redis()                                         # first: gateway/MCP/review depend on it
    if embedder_enabled(base):
        ensure_embedder()                                  # the substrate's own embedding model
    else:
        print(f"  {EMBED_NAME:13} skipped  (REFERENCE_EMBED_MODEL={base.get('REFERENCE_EMBED_MODEL')!r} "
              f"is served by a vendor through the gateway; an existing service is left to `down`)")
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
    for name in (REDIS_NAME, EMBED_NAME, JAEGER_NAME):
        _print_env_keys("jaeger" if name == JAEGER_NAME else name, {})
    for name, spec in substrate_services(base).items():
        _print_env_keys(name, substrate_env(name, spec, base))


def substrate_status():
    ids = services()
    print("images (every service should run ONE):")
    image_report()
    print()
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


def _public(ids, name):
    d = domain_of(ids[name]) if ids.get(name) else None
    return f"https://{d}" if d else None


def configure_workload(name, sid, spec, base_env, ids, service=None, consumer=None):
    gw = _public(ids, "gateway")
    if not gw:
        raise SystemExit("substrate gateway has no public domain — deploy the substrate first")
    env = workload_env(name, spec, base_env, gw, _public(ids, "review"), consumer=consumer)
    _print_env_keys(service or spec["service"], env)
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
    _require_quiet(deploy_profile())
    spec = WORKLOADS[name]
    ids = services()
    base = load_env_for_cloud()
    replicas = replica_services(spec)
    for service, consumer in replicas:
        sid, created = ensure_service(service)
        print(f"deploying workload '{name}' as service {service} "
              f"({'created' if created else 'exists '} {sid[:8]}) consumer={consumer} from "
              f"{IMAGE if BUILD_MODE == 'image' else f'{REPO}@{BRANCH} (repo build)'}")
        gw = configure_workload(name, sid, spec, base, ids, service=service, consumer=consumer)
        deploy(sid)
        print(f"  references substrate gateway {gw}; restart={spec.get('restart')}; no ingress (job)")
    if len(replicas) > 1:
        print(f"  {len(replicas)} replicas share the consumer GROUP, so each stream entry goes to "
              f"exactly one of them — lanes run in parallel, nothing is processed twice")
    print(f"  image {IMAGE} — run `railway.py substrate images` to confirm every service agrees")
    print(f"  watch: python deploy/railway.py workload {name} status   (logs: Railway dashboard)")


def workload_env_report(name):
    """OFFLINE audit: the exact key names workload `name` receives (gateway/review URLs shown as
    placeholders — the real public domains are resolved at `up`)."""
    spec = WORKLOADS[name]
    env = workload_env(name, spec, load_env_for_cloud(), "https://<gateway public domain>", "https://<review public domain>")
    print(f"workload '{name}' env allowlist (from .env, `# CLOUD:` profile)")
    _print_env_keys(spec["service"], env)


def workload_status(name):
    spec = WORKLOADS[name]
    for service, _consumer in replica_services(spec):
        _workload_status_one(name, spec, service)
    print()
    workload_env_report(name)          # the ALLOWLIST is the workload's, identical for every replica


def _workload_status_one(name, spec, service):
    sid = services().get(service)
    if not sid:
        print(f"  {service:13} (not created)")
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
    print(f"  {service:13} {d['status'].lower():10} {verdict}")


def workload_down(name):
    """Every replica. Stopping only the first would leave the others consuming the stream — which
    looks like "I stopped the workload" and is not."""
    spec = WORKLOADS[name]
    for service, _consumer in replica_services(spec):
        sid = services().get(service)
        if not sid:
            continue
        d = latest(sid)
        if d["status"] in ("SUCCESS", "DEPLOYING", "BUILDING"):
            gql('mutation($id:String!){ deploymentRemove(id:$id) }', {"id": d["id"]})
            print(f"  {service:13} stopped (config/variables kept)")
        else:
            print(f"  {service:13} already {d['status'].lower()}")


if __name__ == "__main__":
    usage = ("usage: railway.py substrate up|down|status|env\n"
             "       railway.py workload <" + "|".join(WORKLOADS) + "> up|down|status|env\n"
             "       railway.py bucket up|status      (upload store: create once, credentials -> .env # CLOUD:)\n"
             "       railway.py substrate images        (what image each service runs; exit 1 on a MISMATCH)\n"
             "       railway.py release                 (roll every EXISTING service onto this commit's\n"
             "                                           image; sets NO env vars — what CI/CD runs)\n"
             "       railway.py substrate versions      (what each service is ASKED to run vs what it SAYS\n"
             "                                           it is running — catches a tag that moved under a\n"
             "                                           service that never restarted; exit 1 on a mismatch)\n"
             "       (`env` = offline audit of the exact key names each service receives; no Railway call)")
    tier = sys.argv[1] if len(sys.argv) > 1 else ""
    cmd = (sys.argv[3] if tier == "workload" else sys.argv[2]) if len(sys.argv) > (3 if tier == "workload" else 2) else "status"
    # `env` and `workload list` are OFFLINE audits of this file's own tables — requiring Railway
    # credentials for them would make CD unable to ask what it should deploy without first holding
    # the token that deploys it.
    offline = cmd == "env" or (tier == "workload" and len(sys.argv) > 2 and sys.argv[2] == "list")
    if not offline:
        _require_railway()                                 # every other command talks to Railway
    if tier == "release":                                  # what CD runs: code, never configuration
        sys.exit(1 if release() else 0)
    if tier == "substrate":
        {"up": substrate_up, "down": substrate_down, "status": substrate_status,
         "env": substrate_env_report, "images": lambda: sys.exit(1 if image_report() else 0),
         "versions": lambda: sys.exit(1 if version_report() else 0)}[cmd]()
    elif tier == "bucket":
        {"up": ensure_bucket, "status": bucket_status}[cmd]()
    elif tier == "workload" and len(sys.argv) > 2 and sys.argv[2] == "list":
        # The LONG-LIVED workloads, one per line, for CD to iterate. CI used to carry its own
        # hardcoded list, so a new process was deployed only when somebody remembered to add it
        # there too — a second place to declare something `WORKLOADS` already declares. One-shot
        # jobs are excluded: `restart=NEVER` means "run once", and running one on every push is
        # not a deployment.
        print("\n".join(sorted(n for n, w in WORKLOADS.items()
                               if w.get("restart") == "ALWAYS")))
    elif tier == "workload" and len(sys.argv) > 2 and sys.argv[2] in WORKLOADS:
        {"up": workload_up, "down": workload_down, "status": workload_status,
         "env": workload_env_report}[cmd](sys.argv[2])
    else:
        raise SystemExit(usage)
