"""Deploy the lab to Railway as two independent tiers (see deploy/README.md):

  substrate  — the shared plane: gateway (public), semantic-mcp + adoit-mcp (internal),
               review (public). Lives in the existing project alongside Jaeger, so the
               gateway reaches the MCP servers over Railway private DNS (*.railway.internal).
  workload   — a business process (e.g. visio) as its OWN service, referencing the substrate
               ONLY via the gateway's PUBLIC domain + the shared managed backends — never the
               MCP servers (internal to the substrate) or another workload. Run-to-completion
               jobs deploy with restartPolicyType=NEVER (re-run = redeploy); event/A2A-driven
               hosts stay long-lived. Each workload is deployed/torn down independently.

Builds `deploy/Dockerfile` from the PUBLIC GitHub repo (no local Docker, no GitHub app needed).
Config/secrets come from `.env`: active `KEY=value` lines, with `# CLOUD: KEY=value` comment
values overriding the machine-local ones (Redis Cloud, Railway Jaeger). Secrets stay only in
`.env`, never in this script. Idempotent: services are found by name and updated in place.

Usage: set -a && source .env && set +a && python deploy/railway.py substrate up|down|status
       set -a && source .env && set +a && python deploy/railway.py workload visio up|down|status
"""
import json
import os
import re
import sys
import urllib.request

REPO = "shlapolosa/local-agent-lab"
BRANCH = "main"
API = "https://backboard.railway.com/graphql/v2"
H = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
     "Content-Type": "application/json", "Accept": "application/json",
     "Project-Access-Token": os.environ["RAILWAY_TOKEN"]}
PROJECT = os.environ["RAILWAY_PROJECT_ID"]
ENV = os.environ["RAILWAY_ENVIRONMENT_ID"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- substrate services: name -> role command, ingress, health ---
SUBSTRATE = {
    "semantic-mcp": {"cmd": "python mcp/semantic_mcp/server.py", "port": None},
    "adoit-mcp":    {"cmd": "python mcp/adoit_mcp/server.py", "port": None},
    "gateway":      {"cmd": "litellm --config gateway/litellm-config.yaml --host 0.0.0.0 --port 4000 --num_workers 1",
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
    "review":       {"cmd": "streamlit run review/app.py --server.port 8501 "
                            "--server.address :: --server.headless true", "port": 8501},
}


JAEGER_NAME = "local-agent-lab"   # pre-existing Jaeger service (Docker image; NOT built from our repo)


def gql(query, variables=None):
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables or {}}).encode(), headers=H)
    r = json.load(urllib.request.urlopen(req, timeout=90))
    if r.get("errors"):
        raise SystemExit(f"railway error: {[e.get('message') for e in r['errors']]}")
    return r["data"]


def load_env_for_cloud() -> dict:
    """Active KEY=value from .env, with `# CLOUD: KEY=value` values winning; drop management/meta
    keys the runtime doesn't need. Container overrides are layered on per service by the caller."""
    active, cloud = {}, {}
    for raw in open(os.path.join(ROOT, ".env")):
        line = raw.rstrip("\n")
        m = re.match(r"# CLOUD:\s*([A-Z0-9_]+)=(.*)$", line)
        if m:
            cloud[m.group(1)] = m.group(2).strip().strip("'\"")
            continue
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if re.match(r"^[A-Z0-9_]+$", k):
            active[k] = v.strip().strip("'\"")
    active.update(cloud)                                   # cloud values override local
    # Expand `$VAR` / `${VAR}` references against the parsed values — the shell does this on
    # `source .env`, but Railway passes values verbatim, so e.g. ARTIFACTS_URL=$DATABASE_URL would
    # otherwise reach the container as the literal "$DATABASE_URL" (psycopg: missing "=" ...). Two
    # passes resolve one level of chaining; unknown refs are left untouched.
    def expand(v):
        return re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", lambda m: active.get(m.group(1), m.group(0)), v)
    for _ in range(2):
        active = {k: expand(v) for k, v in active.items()}
    drop = {"RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "NEON_API_KEY",
            "NEON_PROJECT_ID", "NEON_ORG_ID", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"}
    return {k: v for k, v in active.items() if k not in drop and v != ""}


def services():
    d = gql('query($p:String!){ project(id:$p){ services{ edges{ node{ id name } } } } }', {"p": PROJECT})
    return {e["node"]["name"]: e["node"]["id"] for e in d["project"]["services"]["edges"]}


def ensure_service(name):
    existing = services()
    if name in existing:
        return existing[name], False
    d = gql('mutation($in:ServiceCreateInput!){ serviceCreate(input:$in){ id } }',
            {"in": {"projectId": PROJECT, "name": name, "branch": BRANCH,
                    "source": {"repo": REPO}}})
    return d["serviceCreate"]["id"], True


def configure(sid, spec, base_env):
    env = dict(base_env)
    env["BIND_HOST"] = "::"                                 # IPv6 for Railway private networking
    env["ADOIT_MCP_URL"] = "http://adoit-mcp.railway.internal:9100/mcp"
    env["SEMANTIC_MCP_URL"] = "http://semantic-mcp.railway.internal:9200/mcp"
    env["GATEWAY_URL"] = "http://gateway.railway.internal:4000"
    env.update(spec.get("env", {}))
    gql('mutation($in:VariableCollectionUpsertInput!){ variableCollectionUpsert(input:$in) }',
        {"in": {"projectId": PROJECT, "environmentId": ENV, "serviceId": sid,
                "variables": env, "replace": True, "skipDeploys": True}})
    # Always send healthcheckPath — empty string CLEARS any stale probe. The gateway must have NO
    # healthcheck (its IPv6 probe fights the IPv4 0.0.0.0 bind and kills the deploy); see SUBSTRATE.
    upd = {"dockerfilePath": "deploy/Dockerfile", "startCommand": spec["cmd"],
           "healthcheckPath": spec.get("health", "")}
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
    print(f"deploying substrate ({len(SUBSTRATE)} services) from {REPO}@{BRANCH}")
    for name, spec in SUBSTRATE.items():
        sid, created = ensure_service(name)
        print(f"  {name:13} {'created' if created else 'exists '} {sid[:8]}")
        configure(sid, spec, base)
        deploy(sid)
    ensure_jaeger(services())                              # observability is part of the substrate
    print("\ntriggered builds. Public URLs (once healthy):")
    ids = services()
    for name in ("gateway", "review"):
        print(f"  {name:8} https://{domain_of(ids[name]) or '(pending)'}")
    print(f"  jaeger   {os.environ.get('JAEGER_UI_URL', '(see .env)')}")
    print("Watch builds: railway dashboard, or `python deploy/railway.py substrate status`.")


def substrate_status():
    ids = services()
    for name in list(SUBSTRATE) + [JAEGER_NAME]:
        sid = ids.get(name)
        label = "jaeger" if name == JAEGER_NAME else name
        if not sid:
            print(f"  {label:13} (not created)")
            continue
        st = latest(sid)["status"]
        dom = domain_of(sid)
        print(f"  {label:13} {st.lower():10} {('https://'+dom) if dom else '(internal)'}")


def substrate_down():
    ids = services()
    # include Jaeger: tearing the substrate down stops its observability too (metered)
    for name in list(SUBSTRATE) + [JAEGER_NAME]:
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
# plus the shared managed backends (Neon, Redis Cloud, Railway Jaeger) from .env — never the MCP
# servers (internal to the substrate) or another workload; cross-workflow coupling goes via events
# (Redis Streams) or A2A through the gateway. The public URL is the door by design (and the gateway
# binds IPv4 — see SUBSTRATE — so its *.railway.internal name would not be reachable anyway).
WORKLOADS = {
    "visio": {
        "service": "wf-visio",
        # Railway has no volume mounts and the .vsdx fixture is git-ignored: generate it at start,
        # then run the host to completion (Visio -> BA -> Architect -> ADOIT import staged for approval).
        "cmd": "python -m processes.visio_to_archimate.make_sample_vsdx && "
               "python -m processes.visio_to_archimate.host",
        "restart": "NEVER",   # run-to-completion job: exit 0 means done, not crashed; re-run = redeploy
        "env": {"AGENT_RESPONSES_STORE": "false"},
    },
}


def _public(ids, name):
    d = domain_of(ids[name]) if ids.get(name) else None
    return f"https://{d}" if d else None


def configure_workload(sid, spec, base_env, ids):
    env = dict(base_env)
    gw = _public(ids, "gateway")
    if not gw:
        raise SystemExit("substrate gateway has no public domain — deploy the substrate first")
    env["GATEWAY_URL"] = gw                                     # the ONLY substrate coordinate
    env["REVIEW_APP_URL"] = _public(ids, "review") or env.get("REVIEW_APP_URL", "")
    for k in ("ADOIT_MCP_URL", "SEMANTIC_MCP_URL", "BIND_HOST"):
        env.pop(k, None)                                      # workloads never see the MCP servers
    env.update(spec.get("env", {}))
    gql('mutation($in:VariableCollectionUpsertInput!){ variableCollectionUpsert(input:$in) }',
        {"in": {"projectId": PROJECT, "environmentId": ENV, "serviceId": sid,
                "variables": env, "replace": True, "skipDeploys": True}})
    gql('mutation($s:String!,$e:String!,$in:ServiceInstanceUpdateInput!){ '
        'serviceInstanceUpdate(serviceId:$s, environmentId:$e, input:$in) }',
        {"s": sid, "e": ENV, "in": {"dockerfilePath": "deploy/Dockerfile", "startCommand": spec["cmd"],
                                    "healthcheckPath": "",        # a job serves nothing to probe
                                    "restartPolicyType": spec.get("restart", "ON_FAILURE")}})
    return gw


def workload_up(name):
    spec = WORKLOADS[name]
    ids = services()
    base = load_env_for_cloud()
    sid, created = ensure_service(spec["service"])
    print(f"deploying workload '{name}' as service {spec['service']} "
          f"({'created' if created else 'exists '} {sid[:8]}) from {REPO}@{BRANCH}")
    gw = configure_workload(sid, spec, base, ids)
    deploy(sid)
    print(f"  references substrate gateway {gw}; restart={spec.get('restart')}; no ingress (job)")
    print(f"  watch: python deploy/railway.py workload {name} status   (logs: Railway dashboard)")


def workload_status(name):
    spec = WORKLOADS[name]
    sid = services().get(spec["service"])
    if not sid:
        print(f"  {spec['service']:13} (not created)")
        return
    d = latest(sid)
    print(f"  {spec['service']:13} {d['status'].lower():10} (job: SUCCESS = ran; check logs for the result)")


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
    usage = ("usage: railway.py substrate up|down|status\n"
             "       railway.py workload <" + "|".join(WORKLOADS) + "> up|down|status")
    tier = sys.argv[1] if len(sys.argv) > 1 else ""
    if tier == "substrate":
        cmd = sys.argv[2] if len(sys.argv) > 2 else "status"
        {"up": substrate_up, "down": substrate_down, "status": substrate_status}[cmd]()
    elif tier == "workload" and len(sys.argv) > 2 and sys.argv[2] in WORKLOADS:
        cmd = sys.argv[3] if len(sys.argv) > 3 else "status"
        {"up": workload_up, "down": workload_down, "status": workload_status}[cmd](sys.argv[2])
    else:
        raise SystemExit(usage)
