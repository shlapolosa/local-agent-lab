"""Offline tests for deploy/railway.py's Railway REST surface: the GraphQL client, `substrate
up|down|status|env`, `bucket up|status`, `workload <n> up|down|status|env`, the job log-marker
status reading, domain/targetPort handling and the CLI dispatcher. Everything runs against a
RECORDING fake GraphQL endpoint (urllib.request.urlopen is replaced; canned responses per
operation) and a temp `.env` — the real .env is never read (module ROOT is pointed at the temp
dir) and nothing is written outside it. The env parser / allowlist themselves are pinned by
tests/deploy/test_railway_env.py; here the assertions are about BEHAVIOUR: which mutations with which
variables, in what order, and what `status` prints.

Env is pinned in FIXTURES, never at import: `deploy/railway.py` reads RAILWAY_* at import time (the
GraphQL headers, the project and environment ids), so the fake credentials — and the temp repo ROOT —
live in the module fixture below and are undone with it. Pinning them at import would leak a fake
Railway tenant into every other test module in the shared process (see tests/conftest.py).

Run: `.venv/bin/python tests/deploy/test_railway_cli.py`  (also pytest-compatible).
"""
import contextlib
import importlib.util
import io
import json
import os
import runpy
import sys
import tempfile
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAILWAY_PATH = os.path.join(ROOT, "deploy", "railway.py")

CREDS = {"RAILWAY_TOKEN": "tok-fake-project-token", "RAILWAY_PROJECT_ID": "proj-fake",
         "RAILWAY_ENVIRONMENT_ID": "env-fake"}

ENV_TEXT = """\
LITELLM_MASTER_KEY=sk-master-fake
DATABASE_URL=postgresql://fake/db
ARTIFACTS_URL=$DATABASE_URL
OLLAMA_API_KEY=ollama-fake
ANTHROPIC_UPSTREAM_API_KEY=an-fake
MCP_SHARED_SECRET=secret-fake
REDIS_URL=redis://127.0.0.1:6379/0
# CLOUD: REDIS_URL=redis://redis.railway.internal:6379/0
REVIEW_APP_URL=http://127.0.0.1:8501
JAEGER_UI_URL=https://jaeger.example
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp.example
S3_ENDPOINT=https://s3.example
S3_ACCESS_KEY_ID=ak-fake
S3_SECRET_ACCESS_KEY=sk-fake
UPLOADS_URL=s3://lab-uploads/uploads
BA_AGENT_KEY=sk-ba-fake
ENTRA_TENANT_ID=tenant-fake
GATEWAY_EVENTS_FILE=/nowhere/events.jsonl
RAILWAY_TOKEN=must-never-ship
"""


def _load():
    spec = importlib.util.spec_from_file_location("lab_railway_cli", RAILWAY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rw = None                                           # the module under test; loaded by `railway_module`
TMP = None                                          # its temp repo root: .env reads/writes go there only


@pytest.fixture(scope="module", autouse=True)
def railway_module():
    """Load deploy/railway.py with the fake Railway credentials in place (it reads them at import)
    and its ROOT pointed at a temp `.env`, so nothing here touches the real project or repo. Torn
    down with the module — the environment is never pinned at import."""
    global rw, TMP
    mp = pytest.MonkeyPatch()
    for k, v in {**CREDS, "JAEGER_UI_URL": "https://jaeger.example"}.items():
        mp.setenv(k, v)
    TMP = tempfile.mkdtemp()
    with open(os.path.join(TMP, ".env"), "w") as f:
        f.write(ENV_TEXT)
    rw = _load()
    rw.ROOT = TMP
    yield
    mp.undo()
    rw, TMP = None, None


@contextlib.contextmanager
def env_file(text):
    """Point the module at ANOTHER temp `.env` for one test (e.g. one that configures a channel)."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, ".env"), "w") as f:
        f.write(text)
    saved, rw.ROOT = rw.ROOT, d
    try:
        yield d
    finally:
        rw.ROOT = saved

@contextlib.contextmanager
def env_file_missing():
    """Point the module at a directory with NO `.env` (an ops box that only exports RAILWAY_*)."""
    saved, rw.ROOT = rw.ROOT, tempfile.mkdtemp()
    try:
        yield
    finally:
        rw.ROOT = saved


# ---------------------------------------------------------------- the fake Railway GraphQL endpoint
_OPS = [("source{ image }", "image"), ("serviceCreate(", "serviceCreate"), ("serviceInstanceUpdate(", "serviceInstanceUpdate"),
        ("serviceInstanceDeploy(", "serviceInstanceDeploy"), ("serviceDomainCreate(", "serviceDomainCreate"),
        ("variableCollectionUpsert(", "variableCollectionUpsert"), ("volumeCreate(", "volumeCreate"),
        ("volumes{", "volumes"), ("deploymentRemove(", "deploymentRemove"), ("deploymentLogs(", "deploymentLogs"),
        ("deployments(", "deployments"), ("bucketCreate(", "bucketCreate"),
        ("bucketS3Credentials(", "bucketS3Credentials"), ("bucketInstanceDetails(", "bucketInstanceDetails"),
        ("buckets{", "buckets"), ("serviceInstances{", "domains"), ("services{", "services")]


def _op(query):
    return next((op for token, op in _OPS if token in query), "unknown")


def _edges(nodes):
    return {"edges": [{"node": n} for n in nodes]}


class FakeRailway:
    """urlopen replacement: records (op, variables, query) and answers from small state tables."""
    def __init__(self, services=None, status=None, domains=None, volumes=(), buckets=None, logs=(),
                 errors=None, creds=None, images=None):
        self.services = dict(services or {})           # name -> id
        self.status = dict(status or {})               # sid -> deployment status (None = no deployments)
        self.domains = dict(domains or {})             # sid -> public domain
        self.images = dict(images or {})               # sid -> the image its instance runs
        self.volumes = list(volumes)                   # (sid, mountPath)
        self.buckets = dict(buckets or {})             # name -> id
        self.logs = list(logs)
        self.errors = dict(errors or {})               # op -> GraphQL error message
        self.creds = creds or {"endpoint": "https://s3.example", "region": "auto", "bucketName": "lab-uploads",
                               "accessKeyId": "AK", "secretAccessKey": "SK", "urlStyle": "PATH"}
        self.calls, self.requests = [], []

    def ops(self, *names):
        return [c for c in self.calls if not names or c[0] in names]

    def __call__(self, req, timeout=None):
        body = json.loads(req.data)
        op, v = _op(body["query"]), body["variables"]
        self.requests.append((req, timeout))
        self.calls.append((op, v, body["query"]))
        if op in self.errors:
            return io.BytesIO(json.dumps({"errors": [{"message": self.errors[op]}]}).encode())
        return io.BytesIO(json.dumps({"data": self._answer(op, v)}).encode())

    def _answer(self, op, v):
        if op == "services":
            return {"project": {"services": _edges([{"id": i, "name": n} for n, i in self.services.items()])}}
        if op == "image":
            sid = v["s"]
            return {"service": {"serviceInstances": _edges(
                [{"source": {"image": self.images.get(sid)}}])}}
        if op == "serviceCreate":
            name = v["in"]["name"]
            self.services[name] = sid = f"svc-{name}"
            return {"serviceCreate": {"id": sid}}
        if op == "volumes":
            return {"project": {"volumes": _edges([
                {"id": "vol-1", "volumeInstances": _edges([{"serviceId": s, "mountPath": m} for s, m in self.volumes])}])}}
        if op == "volumeCreate":
            self.volumes.append((v["in"]["serviceId"], v["in"]["mountPath"]))
            return {"volumeCreate": {"id": "vol-new"}}
        if op == "serviceDomainCreate":
            sid = v["in"]["serviceId"]
            self.domains[sid] = f"{sid}-production.up.railway.app"
            return {"serviceDomainCreate": {"domain": self.domains[sid]}}
        if op == "domains":
            d = self.domains.get(v["s"])
            return {"service": {"serviceInstances": _edges([{"domains": {"serviceDomains": [{"domain": d}] if d else []}}])}}
        if op == "deployments":
            st = self.status.get(v["s"], "SUCCESS")
            return {"deployments": _edges([] if st is None else [{"id": f"dep-{v['s']}", "status": st}])}
        if op == "deploymentLogs":
            return {"deploymentLogs": [{"message": m} for m in self.logs]}
        if op == "buckets":
            return {"project": {"buckets": _edges([{"id": i, "name": n} for n, i in self.buckets.items()])}}
        if op == "bucketCreate":
            self.buckets[v["in"]["name"]] = "bkt-new-0001"
            return {"bucketCreate": {"id": "bkt-new-0001"}}
        if op == "bucketS3Credentials":
            return {"bucketS3Credentials": self.creds}
        if op == "bucketInstanceDetails":
            return {"bucketInstanceDetails": {"objectCount": 3, "sizeBytes": 4096}}
        return {op: True, "echo": v}                   # mutations answering a scalar / unknown queries


@contextlib.contextmanager
def railway(fake):
    real = urllib.request.urlopen
    urllib.request.urlopen = fake
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        urllib.request.urlopen = real


ALL_SUBSTRATE = ["redis", "semantic-mcp", "adoit-mcp", "storage-mcp", "workflow-mcp", "gateway", "review"]


def _project(*names, jaeger=True):
    svc = {n: f"svc-{n}" for n in names}
    if jaeger:
        svc[rw.JAEGER_NAME] = "svc-jaeger"
    return svc


# ---------------------------------------------------------------- the GraphQL client
def test_gql_sends_browser_user_agent_and_project_token_and_surfaces_errors():
    fake = FakeRailway()
    with railway(fake):
        data = rw.gql("query($a:Int){ thing(a:$a){ id } }", {"a": 1})
        assert data == {"unknown": True, "echo": {"a": 1}}
        assert rw.gql("query{ thing }") == {"unknown": True, "echo": {}}     # variables default to {}
    req, timeout = fake.requests[0]
    assert req.full_url == rw.API and timeout == 90
    hdr = {k.lower(): v for k, v in req.header_items()}
    assert hdr["user-agent"].startswith("Mozilla/5.0") and "Chrome" in hdr["user-agent"]   # Railway rejects bare UAs
    assert hdr["project-access-token"] == CREDS["RAILWAY_TOKEN"]
    assert hdr["content-type"] == "application/json" and hdr["accept"] == "application/json"
    assert json.loads(req.data) == {"query": "query($a:Int){ thing(a:$a){ id } }", "variables": {"a": 1}}
    with railway(FakeRailway(errors={"unknown": "Not Authorized"})):
        try:
            rw.gql("query{ thing }")
        except SystemExit as e:
            assert "railway error" in str(e) and "Not Authorized" in str(e)
        else:
            raise AssertionError("GraphQL errors must abort")


def test_require_railway_names_every_missing_credential(monkeypatch):
    for k, v in CREDS.items():
        monkeypatch.setenv(k, v)
    rw._require_railway()                                             # all three set -> silent
    monkeypatch.delenv("RAILWAY_TOKEN")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID")
    with pytest.raises(SystemExit) as e:
        rw._require_railway()
    assert "RAILWAY_TOKEN, RAILWAY_ENVIRONMENT_ID" in str(e.value) and "source .env" in str(e.value)


# ---------------------------------------------------------------- substrate up
def test_substrate_up_fresh_project_creates_configures_and_deploys_in_order():
    fake = FakeRailway(services={}, status={})                       # nothing exists yet, no jaeger
    with railway(fake) as out:
        rw.substrate_up()
    text = out.getvalue()
    calls = fake.calls
    # 1) Redis first: image service, dual-stack start command, no healthcheck, ALWAYS, /data volume, plain redeploy
    assert [c[0] for c in calls[:6]] == ["services", "serviceCreate", "serviceInstanceUpdate", "volumes",
                                         "volumeCreate", "serviceInstanceDeploy"]
    assert calls[1][1]["in"] == {"projectId": "proj-fake", "name": "redis", "source": {"image": rw.REDIS_IMAGE}}
    upd = calls[2][1]
    assert upd["s"] == "svc-redis" and upd["e"] == "env-fake"
    assert upd["in"] == {"source": {"image": rw.REDIS_IMAGE}, "startCommand": rw.REDIS_CMD,
                         "healthcheckPath": "", "restartPolicyType": "ALWAYS"}
    assert "--bind 0.0.0.0 ::" in rw.REDIS_CMD and "--appendonly yes" in rw.REDIS_CMD
    assert calls[4][1]["in"] == {"projectId": "proj-fake", "environmentId": "env-fake",
                                 "serviceId": "svc-redis", "mountPath": "/data"}
    assert calls[5][1] == {"s": "svc-redis", "e": "env-fake"} and "latestCommit" not in calls[5][2]
    # 2) each substrate service, in table order: create from the ONE prebuilt image, vars, instance
    #    update, [domain], deploy
    created = [c[1]["in"] for c in fake.ops("serviceCreate")][1:]
    assert [c["name"] for c in created] == list(rw.SUBSTRATE)
    assert all(c["source"] == {"image": rw.IMAGE} and "branch" not in c for c in created)   # image mode
    upserts = {c[1]["in"]["serviceId"]: c[1]["in"] for c in fake.ops("variableCollectionUpsert")}
    assert set(upserts) == {f"svc-{n}" for n in rw.SUBSTRATE}
    for u in upserts.values():
        assert u["projectId"] == "proj-fake" and u["environmentId"] == "env-fake"
        assert u["replace"] is True and u["skipDeploys"] is True
        assert "RAILWAY_TOKEN" not in u["variables"]                 # management keys never ship
    gw = upserts["svc-gateway"]["variables"]
    assert gw["DISABLE_SCHEMA_UPDATE"] == "true" and gw["OTEL_SERVICE_NAME"] == "litellm-gateway"
    assert gw["ADOIT_MCP_URL"] == "http://adoit-mcp.railway.internal:9100/mcp"
    assert gw["SEMANTIC_MCP_URL"] == "http://semantic-mcp.railway.internal:9200/mcp"
    assert gw["STORAGE_MCP_URL"] == "http://storage-mcp.railway.internal:9300/mcp"
    assert gw["WORKFLOW_MCP_URL"] == "http://workflow-mcp.railway.internal:9400/mcp"
    assert gw["REDIS_URL"] == "redis://redis.railway.internal:6379/0"    # `# CLOUD:` value
    assert gw["LITELLM_MASTER_KEY"] == "sk-master-fake" and gw["OLLAMA_API_KEY"] == "ollama-fake"
    assert not any(k.startswith("S3_") for k in gw) and "UPLOADS_URL" not in gw
    assert "GATEWAY_EVENTS_FILE" not in gw                         # F4: reader deleted, grant removed
    assert "BIND_HOST" not in gw                                    # litellm binds via --host on its cmd
    st = upserts["svc-storage-mcp"]["variables"]
    assert st["S3_ENDPOINT"] == "https://s3.example" and st["UPLOADS_URL"] == "s3://lab-uploads/uploads"
    assert st["BIND_HOST"] == "::" and st["ARTIFACTS_URL"] == "postgresql://fake/db"   # $VAR expanded
    assert "S3_ENDPOINT" in upserts["svc-review"]["variables"]
    assert not any(k.startswith("S3_") for k in upserts["svc-semantic-mcp"]["variables"])
    assert not any(k.startswith("S3_") for k in upserts["svc-adoit-mcp"]["variables"])
    # workflow-mcp publishes/reads workflow:requests and NOTHING else: Redis + trust + tracing only
    wf = upserts["svc-workflow-mcp"]["variables"]
    assert wf["REDIS_URL"] == "redis://redis.railway.internal:6379/0"
    assert wf["MCP_SHARED_SECRET"] == "secret-fake" and wf["BIND_HOST"] == "::"
    for k in ("DATABASE_URL", "ARTIFACTS_URL", "UPLOADS_URL", "S3_ENDPOINT", "S3_ACCESS_KEY_ID",
              "ADOIT_PASSWORD", "LITELLM_MASTER_KEY", "OLLAMA_API_KEY"):
        assert k not in wf, k
    inst = {c[1]["s"]: c[1]["in"] for c in fake.ops("serviceInstanceUpdate") if c[1]["s"] != "svc-redis"}
    for name, spec in rw.SUBSTRATE.items():
        # every field is sent every time: a partial patch would let a stale probe or restart policy
        # outlive the table (ON_FAILURE is Railway's default, so this states what already happened)
        assert inst[f"svc-{name}"] == {"source": {"image": rw.IMAGE}, "startCommand": spec["cmd"],
                                       "healthcheckPath": "", "restartPolicyType": "ON_FAILURE"}, name
    assert "--host 0.0.0.0" in inst["svc-gateway"]["startCommand"]  # IPv4 edge + no probe (verified combo)
    domains = [c[1]["in"] for c in fake.ops("serviceDomainCreate")]
    assert domains == [{"environmentId": "env-fake", "serviceId": "svc-gateway", "targetPort": 4000},
                       {"environmentId": "env-fake", "serviceId": "svc-review", "targetPort": 8501}]
    # image mode: nothing fetches a commit (every service pulls the same prebuilt tag)
    deploys = [(c[1]["s"], "latestCommit:true" in c[2]) for c in fake.ops("serviceInstanceDeploy")]
    assert deploys == [("svc-redis", False)] + [(f"svc-{n}", False) for n in rw.SUBSTRATE]
    # per-service order: vars before instance update before deploy
    seq = [c[0] for c in calls if c[0].endswith(("Upsert", "Update", "Create", "Deploy"))
           and (c[1].get("s") == "svc-gateway" or c[1].get("in", {}).get("serviceId") == "svc-gateway")]
    assert seq == ["variableCollectionUpsert", "serviceInstanceUpdate", "serviceDomainCreate", "serviceInstanceDeploy"]
    # 3) jaeger absent -> pointer to lab.sh; public URLs printed from the domains just created
    assert "jaeger        not in project" in text
    assert "gateway  https://svc-gateway-production.up.railway.app" in text
    assert "review   https://svc-review-production.up.railway.app" in text
    assert "jaeger   https://jaeger.example" in text
    assert "sk-master-fake" not in text and "ollama-fake" not in text   # values never printed
    assert "gateway       env (" in text and "DISABLE_SCHEMA_UPDATE" in text


def test_image_tag_defaults_to_an_immutable_sha_when_the_repo_can_supply_one():
    """A mutable `:main` tag makes "what is deployed" unknowable — the exact condition that let a
    workload run one commit while the gateway ran another. Default to the CI sha tag for HEAD."""
    assert rw.IMAGE_TAG.startswith("sha-") or rw.IMAGE_TAG == rw.BRANCH   # sha when git answers
    if rw.IMAGE_TAG.startswith("sha-"):
        assert len(rw.IMAGE_TAG) >= len("sha-") + 7


def test_deployed_images_reports_every_service_and_flags_a_mismatch():
    """The failure was INVISIBLE: nothing showed that two services ran different images."""
    ours = f"ghcr.io/{rw.REPO}"
    fake = FakeRailway(services=_project("gateway", "review", "wf-visio", "redis"),
                       images={"svc-gateway": f"{ours}:sha-aaaaaaa",
                               "svc-review": f"{ours}:sha-aaaaaaa",
                               "svc-wf-visio": f"{ours}:sha-bbbbbbb",
                               "svc-redis": "redis:7-alpine"})   # third-party: never a mismatch
    with railway(fake) as out:
        mismatch = rw.image_report()
    text = out.getvalue()
    assert "sha-aaaaaaa" in text and "sha-bbbbbbb" in text
    assert mismatch is True
    assert "MISMATCH" in text.upper()


def test_image_report_is_quiet_when_every_service_agrees():
    ours = f"ghcr.io/{rw.REPO}"
    fake = FakeRailway(services=_project("gateway", "review", "redis"),
                       images={"svc-gateway": f"{ours}:sha-aaaaaaa",
                               "svc-review": f"{ours}:sha-aaaaaaa",
                               "svc-redis": "redis:7-alpine"})
    with railway(fake) as out:
        assert rw.image_report() is False
    assert "MISMATCH" not in out.getvalue().upper()


def test_image_mode_is_the_default_and_points_every_service_at_one_prebuilt_image():
    """Build once in CI (.github/workflows/image.yml -> GHCR), deploy the SAME immutable image to every
    role: no per-service Dockerfile build, identical bits across roles."""
    assert rw.BUILD_MODE == "image"                       # default; LAB_BUILD=repo restores repo builds
    assert rw.IMAGE.startswith("ghcr.io/") and rw.REPO in rw.IMAGE
    fake = FakeRailway()
    with railway(fake):
        rw.substrate_up()
    created = [v["in"] for op, v, _ in fake.ops("serviceCreate")]
    assert all(c["source"] == {"image": rw.IMAGE} for c in created if c["name"] in rw.SUBSTRATE), created
    upd = {v["s"]: v["in"] for op, v, _ in fake.ops("serviceInstanceUpdate")}
    for name in rw.SUBSTRATE:
        i = upd[f"svc-{name}"]
        assert i.get("source") == {"image": rw.IMAGE}, (name, i)
        assert i["restartPolicyType"] == "ON_FAILURE", name
        assert "dockerfilePath" not in i, name           # nothing is built from the repo
        assert i["startCommand"] == rw.SUBSTRATE[name]["cmd"]
    # an image service has no repo commit to fetch
    assert all(v.get("latestCommit") is not True for op, v, q in fake.ops("serviceInstanceDeploy")
               if "latestCommit" in q)


def test_repo_mode_still_builds_the_dockerfile(monkeypatch):
    """LAB_BUILD=repo keeps the original per-service Railway build (fallback / no registry)."""
    monkeypatch.setattr(rw, "BUILD_MODE", "repo")
    fake = FakeRailway()
    with railway(fake):
        rw.substrate_up()
    upd = {v["s"]: v["in"] for op, v, _ in fake.ops("serviceInstanceUpdate")}
    gw = upd["svc-gateway"]
    assert gw["dockerfilePath"] == "deploy/Dockerfile" and "source" not in gw


def test_workload_up_uses_the_same_image(monkeypatch):
    fake = FakeRailway(services={"gateway": "svc-gateway", "review": "svc-review"},
                       domains={"svc-gateway": "gw.up.railway.app", "svc-review": "rev.up.railway.app"})
    with railway(fake):
        rw.workload_up("visio")
    i = next(v["in"] for op, v, _ in fake.ops("serviceInstanceUpdate") if v["s"] == "svc-wf-visio")
    assert i["source"] == {"image": rw.IMAGE} and "dockerfilePath" not in i


def test_substrate_up_existing_project_is_idempotent_and_redeploys_jaeger():
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE), status={"svc-jaeger": "CRASHED"},
                       domains={"svc-gateway": "gw.example", "svc-review": "rv.example"},
                       volumes=[("svc-redis", "/data")], errors={"serviceDomainCreate": "Domain already exists"})
    with railway(fake) as out:
        rw.substrate_up()
    text = out.getvalue()
    assert fake.ops("serviceCreate") == [] and fake.ops("volumeCreate") == []       # found by name, volume kept
    assert "redis         exists" in text and "volume attached" not in text
    assert "domain note" not in text                                                # "already exists" swallowed
    assert [c[1]["s"] for c in fake.ops("serviceInstanceDeploy")][-1] == "svc-jaeger"
    assert "latestCommit" not in fake.ops("serviceInstanceDeploy")[-1][2]           # image service
    assert "jaeger        redeploying" in text
    assert "gateway  https://gw.example" in text and "review   https://rv.example" in text
    # a different domain error is reported, not hidden; a healthy jaeger is left alone
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE), status={"svc-jaeger": "SUCCESS"},
                       volumes=[("svc-redis", "/data")], errors={"serviceDomainCreate": "quota exceeded"})
    with railway(fake) as out:
        rw.substrate_up()
    text = out.getvalue()
    assert text.count("domain note") == 2 and "quota exceeded" in text
    assert "jaeger        already up" in text
    assert all(c[1]["s"] != "svc-jaeger" for c in fake.ops("serviceInstanceDeploy"))
    assert "gateway  https://(pending)" in text                                     # no domain yet


def test_ensure_volume_survives_lookup_failure():
    fake = FakeRailway(errors={"volumes": "field not found"})
    with railway(fake) as out:
        assert rw.ensure_volume("svc-x", "/data") is True                          # created after failed lookup
    assert "volume lookup unavailable" in out.getvalue()
    assert fake.ops("volumeCreate")[0][1]["in"]["mountPath"] == "/data"
    fake = FakeRailway(volumes=[("svc-x", "/other")])
    with railway(fake):
        assert rw.ensure_volume("svc-x", "/data") is True                          # other mount != attached
        assert rw.ensure_volume("svc-x", "/data") is False                         # now attached


# ---------------------------------------------------------------- substrate status / env / down
def test_substrate_status_prints_state_domain_and_env_audit():
    fake = FakeRailway(services=_project("redis", "gateway", "semantic-mcp"),
                       status={"svc-gateway": "SUCCESS", "svc-semantic-mcp": "BUILDING", "svc-redis": None,
                               "svc-jaeger": "CRASHED"},
                       domains={"svc-gateway": "gw.example"})
    with railway(fake) as out:
        rw.substrate_status()
    text = out.getvalue()
    assert "gateway       success    https://gw.example" in text
    assert "semantic-mcp  building   (internal)" in text
    assert "redis         none       (internal)" in text                          # no deployment yet
    assert "adoit-mcp     (not created)" in text and "review        (not created)" in text
    assert "jaeger        crashed    (internal)" in text
    assert "substrate env allowlist" in text
    assert "redis         env (0):" in text and "jaeger        env (0):" in text
    assert "storage-mcp   env (" in text and "S3_ENDPOINT" in text
    assert fake.ops("deploymentLogs") == [] and fake.ops("serviceInstanceDeploy") == []   # read-only


def test_substrate_env_report_is_offline():
    fake = FakeRailway()
    with railway(fake) as out:
        rw.substrate_env_report()
    text = out.getvalue()
    assert fake.calls == []                                                        # no Railway call at all
    for name in rw.SUBSTRATE:
        assert f"{name:13} env (" in text, name
    assert "must-never-ship" not in text and "sk-master-fake" not in text


def test_substrate_down_removes_only_running_deployments():
    fake = FakeRailway(services=_project("redis", "gateway", "review"),
                       status={"svc-redis": "SUCCESS", "svc-gateway": "SUCCESS", "svc-review": "CRASHED",
                               "svc-jaeger": "SUCCESS"})
    with railway(fake) as out:
        rw.substrate_down()
    text = out.getvalue()
    removed = [c[1]["id"] for c in fake.ops("deploymentRemove")]
    assert removed == ["dep-svc-redis", "dep-svc-gateway", "dep-svc-jaeger"]       # table order, jaeger last
    assert "gateway       stopped (config/variables/domain kept)" in text
    assert "review        already crashed" in text
    assert "semantic-mcp" not in text                                              # not created -> silent


# ---------------------------------------------------------------- approval channels (optional services)
CHANNEL_ENV = ENV_TEXT + "TEAMS_WEBHOOK_URL=https://teams.example/hook\n"


def test_a_configured_channel_is_deployed_like_any_other_substrate_service():
    """A channel that has its settings becomes a real service: same image, its own start command,
    restart ALWAYS (it is a loop), NO domain (nothing calls it) and ONLY its own env."""
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE),
                       domains={"svc-gateway": "gw.example", "svc-review": "rv.example"},
                       volumes=[("svc-redis", "/data")])
    with env_file(CHANNEL_ENV), railway(fake) as out:
        rw.substrate_up()
    text = out.getvalue()
    assert fake.ops("serviceCreate")[0][1]["in"]["name"] == "teams"        # the only service missing
    inst = {c[1]["s"]: c[1]["in"] for c in fake.ops("serviceInstanceUpdate")}["svc-teams"]
    assert inst == {"source": {"image": rw.IMAGE}, "startCommand": rw.CHANNELS["teams"]["cmd"],
                    "healthcheckPath": "", "restartPolicyType": "ALWAYS"}
    assert "python -m lab.substrate.channels.teams" == inst["startCommand"]
    assert all(c[1]["in"]["serviceId"] != "svc-teams" for c in fake.ops("serviceDomainCreate"))
    env = {c[1]["in"]["serviceId"]: c[1]["in"]["variables"] for c in fake.ops("variableCollectionUpsert")}["svc-teams"]
    assert set(env) == {"TEAMS_WEBHOOK_URL", "REDIS_URL", "REVIEW_APP_URL", "JAEGER_UI_URL",
                        "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert env["TEAMS_WEBHOOK_URL"] == "https://teams.example/hook"
    assert env["REDIS_URL"] == "redis://redis.railway.internal:6379/0"     # the substrate's own Redis
    assert [c[1]["s"] for c in fake.ops("serviceInstanceDeploy")][-1] == "svc-teams"
    # the channel with no settings is never created, and says so
    assert "telegram      skipped  (not configured: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)" in text
    assert "teams         created" in text and "teams         env (5)" in text
    assert all(c[1]["in"]["name"] != "telegram" for c in fake.ops("serviceCreate"))


def test_an_unconfigured_channel_is_not_part_of_the_substrate_at_all():
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE), volumes=[("svc-redis", "/data")])
    with railway(fake) as out:                                             # the default .env: no channel
        rw.substrate_up()
    assert fake.ops("serviceCreate") == []
    upserts = {c[1]["in"]["serviceId"] for c in fake.ops("variableCollectionUpsert")}
    assert upserts == {f"svc-{n}" for n in rw.SUBSTRATE}
    text = out.getvalue()
    for name in rw.CHANNELS:
        assert f"{name:13} skipped  (not configured:" in text
    with railway(FakeRailway()) as out:
        rw.substrate_env_report()
    assert "teams" not in out.getvalue() and "telegram" not in out.getvalue()


def test_status_and_down_cover_a_channel_that_is_deployed_but_no_longer_configured():
    """Settings removed from .env must not orphan a running channel: it is still listed and stopped."""
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE, "teams"),
                       status={"svc-teams": "SUCCESS", "svc-jaeger": "SUCCESS"})
    with railway(fake) as out:                                             # .env no longer configures it
        rw.substrate_status()
    assert "teams         success" in out.getvalue()
    with railway(fake) as out:
        rw.substrate_down()
    assert "teams         stopped (config/variables/domain kept)" in out.getvalue()
    assert "dep-svc-teams" in [c[1]["id"] for c in fake.ops("deploymentRemove")]
    # ... and BOTH read-side commands still work on a box with no .env at all (neither needed one
    # before channels made the service list depend on it)
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE, "teams"), status={"svc-teams": "SUCCESS"})
    with env_file_missing(), railway(fake) as out:
        rw.substrate_down()
    assert "teams         stopped" in out.getvalue()
    with env_file_missing(), railway(FakeRailway(services=_project(*ALL_SUBSTRATE, "teams"))) as out:
        rw.substrate_status()
    text = out.getvalue()
    assert "teams         success" in text and "0 keys in the pool" in text   # empty pool, no crash
    # a channel that is neither configured nor deployed is not mentioned at all
    fake = FakeRailway(services=_project(*ALL_SUBSTRATE))
    with railway(fake) as out:
        rw.substrate_status()
    assert "teams" not in out.getvalue() and "telegram" not in out.getvalue()


# ---------------------------------------------------------------- bucket up / status
def test_bucket_up_creates_once_and_writes_cloud_lines_to_env():
    env_path = os.path.join(TMP, ".env")
    fake = FakeRailway(buckets={}, creds={"endpoint": "https://s3.example", "region": None, "bucketName": "lab-uploads",
                                          "accessKeyId": "AK1", "secretAccessKey": "SK1", "urlStyle": None})
    with railway(fake) as out:
        assert rw.ensure_bucket() == "bkt-new-0001"
    text = out.getvalue()
    assert fake.ops("bucketCreate")[0][1]["in"] == {"projectId": "proj-fake", "environmentId": "env-fake",
                                                    "name": rw.BUCKET_NAME}
    assert fake.ops("bucketS3Credentials")[0][1] == {"b": "bkt-new-0001"}
    assert "bucket lab-uploads created bkt-new-" in text and "applies to review + storage-mcp" in text
    s = open(env_path).read()
    for line in ("# CLOUD: RAILWAY_BUCKET_ID=bkt-new-0001", "# CLOUD: S3_ENDPOINT=https://s3.example",
                 "# CLOUD: S3_REGION=", "# CLOUD: S3_ACCESS_KEY_ID=AK1", "# CLOUD: S3_SECRET_ACCESS_KEY=SK1",
                 "# CLOUD: S3_URL_STYLE=path", "# CLOUD: UPLOADS_URL=s3://lab-uploads/uploads"):
        assert s.count(line + "\n") == 1, line
    assert s.startswith(ENV_TEXT)                                                  # existing lines intact
    # second run: bucket found by name (no create), lines REPLACED in place (no duplicates)
    fake = FakeRailway(buckets={rw.BUCKET_NAME: "bkt-existing"},
                       creds={"endpoint": "https://s3-2.example", "region": "eu", "bucketName": "lab-uploads",
                              "accessKeyId": "AK2", "secretAccessKey": "SK2", "urlStyle": "VIRTUAL"})
    with railway(fake) as out:
        assert rw.ensure_bucket() == "bkt-existing"
    assert fake.ops("bucketCreate") == [] and "bucket lab-uploads exists" in out.getvalue()
    s = open(env_path).read()
    assert s.count("# CLOUD: S3_ENDPOINT=") == 1 and "# CLOUD: S3_ENDPOINT=https://s3-2.example\n" in s
    assert "# CLOUD: S3_REGION=eu\n" in s and "# CLOUD: S3_URL_STYLE=virtual\n" in s
    assert "# CLOUD: RAILWAY_BUCKET_ID=bkt-existing\n" in s and "AK1" not in s
    # the deploy profile now carries the bucket to the services flagged s3 only
    pool = rw.load_env_for_cloud()
    assert pool["S3_ENDPOINT"] == "https://s3-2.example"
    assert "S3_ENDPOINT" in rw.substrate_env("review", rw.SUBSTRATE["review"], pool)
    assert "S3_ENDPOINT" not in rw.substrate_env("gateway", rw.SUBSTRATE["gateway"], pool)


def test_bucket_status_lists_details_errors_and_absence():
    fake = FakeRailway(buckets={"lab-uploads": "bkt-000001"})
    with railway(fake) as out:
        rw.bucket_status()
    assert "lab-uploads   bkt-0000  objects=3 bytes=4096" in out.getvalue()
    fake = FakeRailway(buckets={"lab-uploads": "bkt-000001"}, errors={"bucketInstanceDetails": "no details"})
    with railway(fake) as out:
        rw.bucket_status()
    assert "lab-uploads   bkt-0000  (railway error: ['no details'])" in out.getvalue()
    with railway(FakeRailway(buckets={})) as out:
        rw.bucket_status()
    assert "(no buckets — run: railway.py bucket up)" in out.getvalue()


# ---------------------------------------------------------------- workloads
def test_workload_up_references_only_the_public_gateway():
    fake = FakeRailway(services=_project("gateway", "review"),
                       domains={"svc-gateway": "gw.example", "svc-review": "rv.example"})
    with railway(fake) as out:
        rw.workload_up("visio")
    text = out.getvalue()
    assert fake.ops("serviceCreate")[0][1]["in"]["name"] == "wf-visio"
    up = fake.ops("variableCollectionUpsert")[0][1]["in"]
    assert up["serviceId"] == "svc-wf-visio" and up["replace"] is True and up["skipDeploys"] is True
    env = up["variables"]
    assert env["GATEWAY_URL"] == "https://gw.example" and env["REVIEW_APP_URL"] == "https://rv.example"
    assert env["AGENT_RESPONSES_STORE"] == "false" and env["WF_CONSUMER"] == "1"
    assert env["REDIS_URL"] == "redis://redis.railway.internal:6379/0" and env["BA_AGENT_KEY"] == "sk-ba-fake"
    for k in ("DATABASE_URL", "ARTIFACTS_URL", "UPLOADS_URL", "S3_ENDPOINT", "STORAGE_MCP_URL", "ADOIT_MCP_URL",
              "SEMANTIC_MCP_URL", "MCP_SHARED_SECRET", "LITELLM_MASTER_KEY", "OLLAMA_API_KEY", "RAILWAY_TOKEN"):
        assert k not in env, k
    inst = fake.ops("serviceInstanceUpdate")[0][1]["in"]
    assert inst == {"source": {"image": rw.IMAGE}, "startCommand": rw.WORKLOADS["visio"]["cmd"],
                    "healthcheckPath": "", "restartPolicyType": "ALWAYS"}
    dep = fake.ops("serviceInstanceDeploy")[0]
    assert dep[1]["s"] == "svc-wf-visio" and "latestCommit" not in dep[2]   # image mode: no commit to fetch
    assert "deploying workload 'visio' as service wf-visio (created" in text
    assert "references substrate gateway https://gw.example; restart=ALWAYS" in text
    # the one-shot job: NEVER restart, sh -c chain (Railway execs without a shell), review URL falls back to .env
    fake = FakeRailway(services=_project("gateway", "wf-visio-job"), domains={"svc-gateway": "gw.example"})
    with railway(fake) as out:
        rw.workload_up("visio-job")
    assert fake.ops("serviceCreate") == [] and "(exists " in out.getvalue()
    inst = fake.ops("serviceInstanceUpdate")[0][1]["in"]
    assert inst["restartPolicyType"] == "NEVER" and inst["startCommand"].startswith("sh -c '")
    env = fake.ops("variableCollectionUpsert")[0][1]["in"]["variables"]
    assert env["REVIEW_APP_URL"] == "http://127.0.0.1:8501" and "WF_CONSUMER" not in env


def test_workload_up_refuses_without_a_public_gateway():
    fake = FakeRailway(services=_project("gateway"))                              # no domain yet
    with railway(fake):
        try:
            rw.workload_up("visio")
        except SystemExit as e:
            assert "deploy the substrate first" in str(e)
        else:
            raise AssertionError("expected SystemExit")
    assert fake.ops("variableCollectionUpsert") == [] and fake.ops("serviceInstanceDeploy") == []
    with railway(FakeRailway(services={})):
        try:
            rw.workload_up("visio")
        except SystemExit:
            pass
        else:
            raise AssertionError("expected SystemExit")


def test_workload_env_report_is_offline_with_placeholders():
    fake = FakeRailway()
    with railway(fake) as out:
        rw.workload_env_report("visio")
    text = out.getvalue()
    assert fake.calls == []
    assert "workload 'visio' env allowlist" in text and "wf-visio      env (" in text
    assert "GATEWAY_URL" in text and "REVIEW_APP_URL" in text and "DATABASE_URL" not in text


def _status(name, status="SUCCESS", logs=(), errors=None, created=True):
    svc = _project("wf-visio", "wf-visio-job") if created else _project()
    fake = FakeRailway(services=svc, status={"svc-wf-visio": status, "svc-wf-visio-job": status},
                       logs=logs, errors=errors)
    with railway(fake) as out:
        rw.workload_status(name)
    return out.getvalue(), fake


def test_workload_status_reads_log_markers_not_deployment_status():
    # long-lived consumer: READY + last finished request
    text, fake = _status("visio", logs=["boot", "consumer ready", "request r1 running", "request r1 done",
                                        "request r2 running", "request r2 failed: boom", "trace x"])
    assert "wf-visio      success    READY — request r2 failed: boom" in text
    assert fake.ops("deploymentLogs")[0][1] == {"d": "dep-svc-wf-visio"}
    assert "workload 'visio' env allowlist" in text                                # env audit appended
    text, _ = _status("visio", logs=["booting"])
    assert "starting — no runs yet" in text
    text, _ = _status("visio", logs=["consumer ready"])
    assert "READY — no runs yet" in text
    # one-shot job: SUCCESS is not the verdict — the markers are
    text, _ = _status("visio-job", logs=["step 1", "approval requested: apr-77 (review app)", "bye"])
    assert "wf-visio-job  success    RAN TO COMPLETION — approval requested: apr-77 (review app)" in text
    text, _ = _status("visio-job", logs=["start", "Traceback (most recent call last):", "  File x",
                                         "RuntimeError: gateway 502", ""])
    assert "FAILED — RuntimeError: gateway 502" in text
    text, _ = _status("visio-job", status="DEPLOYING", logs=["building image"])
    assert "wf-visio-job  deploying  running / in progress" in text
    text, _ = _status("visio-job", logs=[])
    assert "no logs yet" in text
    text, _ = _status("visio-job", errors={"deploymentLogs": "logs unavailable"})   # logs query failing is not fatal
    assert "wf-visio-job  success    no logs yet" in text
    text, fake = _status("visio", created=False)
    assert "wf-visio      (not created)" in text and fake.ops("deployments") == []


def test_workload_down_stops_active_deployments_only():
    for st, expect_remove in (("SUCCESS", True), ("DEPLOYING", True), ("BUILDING", True), ("CRASHED", False)):
        fake = FakeRailway(services=_project("wf-visio"), status={"svc-wf-visio": st})
        with railway(fake) as out:
            rw.workload_down("visio")
        assert bool(fake.ops("deploymentRemove")) is expect_remove, st
        if expect_remove:
            assert fake.ops("deploymentRemove")[0][1] == {"id": "dep-svc-wf-visio"}
            assert "wf-visio      stopped (config/variables kept)" in out.getvalue()
        else:
            assert f"wf-visio      already {st.lower()}" in out.getvalue()
    fake = FakeRailway(services={})
    with railway(fake) as out:
        rw.workload_down("visio")
    assert out.getvalue() == "" and fake.ops("deployments") == []


# ---------------------------------------------------------------- CLI dispatcher (python deploy/railway.py …)
def _cli(*argv, fake=None, env=None):
    """Run the script as __main__ (the real entry point) against the fake endpoint; returns
    (stdout, SystemExit message or None, fake). Only commands that never touch .env are driven here
    (runpy re-executes the file, so its ROOT is the real repo). Env and argv go through MonkeyPatch
    and are undone before returning."""
    fake = fake or FakeRailway()
    mp = pytest.MonkeyPatch()
    mp.setattr(sys, "argv", ["railway.py", *argv])
    for k, v in {**CREDS, **(env or {})}.items():      # creds set per call: a value of None unsets one
        mp.delenv(k, raising=False) if v is None else mp.setenv(k, v)
    code = None
    try:
        with railway(fake) as out:
            try:
                runpy.run_path(RAILWAY_PATH, run_name="__main__")
            except SystemExit as e:
                code = str(e)
    finally:
        mp.undo()
    return out.getvalue(), code, fake


def test_cli_dispatches_substrate_bucket_and_workload_commands():
    fake = FakeRailway(services=_project("gateway"), status={"svc-gateway": "SUCCESS"})
    text, code, _ = _cli("substrate", "down", fake=fake)
    assert code is None and "gateway       stopped" in text
    assert fake.ops("deploymentRemove")[0][1] == {"id": "dep-svc-gateway"}
    text, code, fake = _cli("bucket", "status", fake=FakeRailway(buckets={"lab-uploads": "bkt-000001"}))
    assert code is None and "objects=3" in text
    text, code, fake = _cli("bucket", fake=FakeRailway(buckets={}))                 # default command = status
    assert code is None and "(no buckets" in text
    fake = FakeRailway(services=_project("wf-visio"), status={"svc-wf-visio": "SUCCESS"})
    text, code, _ = _cli("workload", "visio", "down", fake=fake)
    assert code is None and "wf-visio      stopped" in text
    # the fake token/UA travel on every CLI call too
    hdr = {k.lower(): v for k, v in fake.requests[0][0].header_items()}
    assert hdr["project-access-token"] == CREDS["RAILWAY_TOKEN"] and "Mozilla" in hdr["user-agent"]


def test_cli_usage_and_credential_errors():
    for argv in ((), ("nonsense", "up"), ("workload", "nope", "up"), ("workload",)):
        text, code, fake = _cli(*argv)
        assert code and code.startswith("usage: railway.py substrate up|down|status|env"), argv
        assert "workload <visio|visio-job>" in code and "bucket up|status" in code
        assert fake.calls == []
    text, code, fake = _cli("substrate", "status", env={"RAILWAY_TOKEN": None})
    assert code.startswith("missing RAILWAY_TOKEN") and fake.calls == []            # checked before any call
    # `env` is the offline audit: no credential check at all (an unknown workload still ends in usage)
    text, code, fake = _cli("workload", "nope", "env", env={"RAILWAY_TOKEN": None})
    assert code.startswith("usage:") and fake.calls == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
