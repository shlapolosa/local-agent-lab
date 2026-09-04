"""src/lab/substrate/mcp/adoit/server.py — every tool through an in-memory fastmcp Client, OFFLINE:
the artifact store is a temp LocalStore, `lab.substrate.approvals` is a recording fake, ADOIT REST is a
fake `urllib.request.urlopen`, and BOTH values of config.ADOIT_REST_WRITE drive adoit_import_status
(review F1: the REST-enabled branch must never claim a changeset executes — nothing calls the
write facade). The `__main__` env check runs via runpy with `lab.substrate.mcpserver.serve` faked.
One INTEGRATION test uses the real lab.substrate.approvals against the local brew Redis and skips when
it is down.
Run: .venv/bin/python tests/integration/test_adoit_mcp_server.py   (also pytest-compatible)"""
import asyncio
import importlib.util
import io
import json
import os
import runpy
import sys
import tempfile
import urllib.request
from contextlib import contextmanager

import pytest
from fastmcp import Client

from lab.platform import config
from lab.substrate import artifacts

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "adoit", "server.py")

TMP = srv = STORE = None            # set up by `_server` (never at import: it pins the environment)


@pytest.fixture(scope="module", autouse=True)
def _server():
    """Compose the server against a fake ADOIT tenant and a temp artifact store. The server composes
    at import, so the environment is pinned HERE (a module fixture) — at this module's import it
    leaked the fake tenant, `MCP_SHARED_SECRET` and a popped `DATABASE_URL` into every other test
    module. The store the server writes to is THIS temp LocalStore whatever config resolved to:
    override the kit's provider rather than the environment. Undone with the module."""
    global TMP, srv, STORE
    mp = pytest.MonkeyPatch()
    TMP = tempfile.mkdtemp(prefix="adoit-mcp-test-")
    for k, v in {"ADOIT_BASE_URL": "https://adoit.test/ADOIT", "ADOIT_USERNAME": "lab-user",
                 "ADOIT_PASSWORD": "s3cret", "ADOIT_REPO_ID": "{repo-1}",
                 "MCP_SHARED_SECRET": "shh"}.items():
        mp.setenv(k, v)
    for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "UPLOADS_URL", "DATABASE_URL", "ADOIT_REST_WRITE"):
        mp.delenv(k, raising=False)

    spec = importlib.util.spec_from_file_location("adoit_mcp_server", SERVER)
    srv = importlib.util.module_from_spec(spec)
    sys.modules["adoit_mcp_server"] = srv
    spec.loader.exec_module(srv)

    STORE = artifacts.LocalStore(os.path.join(TMP, "store"))
    srv.server.container.artifacts.override(STORE)
    yield
    sys.modules.pop("adoit_mcp_server", None)
    mp.undo()
    TMP = srv = STORE = None

TOOLS = {"archimate_validate", "archimate_render", "adoit_excel_render", "adoit_repos", "adoit_search",
         "adoit_object", "adoit_request_import", "adoit_import_status", "adoit_import_instructions"}

SPEC = {
    "name": "Claims Portal", "id": "claims-portal",
    "elements": [
        {"id": "portal", "type": "ApplicationComponent", "name": "Portal", "doc": "Web front end"},
        {"id": "svc", "type": "ApplicationService", "name": "Claims Service"},
        {"id": "api", "type": "ApplicationInterface", "name": "Claims API"},
        {"id": "claim", "type": "DataObject", "name": "Claim", "folder": "Data"},
        {"id": "clerk", "type": "BusinessActor", "name": "Clerk"},
    ],
    "relations": [
        {"id": "r1", "type": "Realization", "src": "portal", "tgt": "svc"},
        {"id": "r2", "type": "Composition", "src": "portal", "tgt": "api"},
        {"id": "r3", "type": "Assignment", "src": "api", "tgt": "svc"},
        {"id": "r4", "type": "Access", "src": "portal", "tgt": "claim", "accessType": "Write"},
        {"id": "r5", "type": "Serving", "src": "svc", "tgt": "clerk"},
    ],
    "views": [{"id": "landscape", "title": "Landscape", "elements": ["clerk", "svc", "api", "portal", "claim"]}],
}


# ---------------------------------------------------------------- fakes
class FakeApprovals:
    """The approval contract adoit-mcp depends on (request / status / CHANNELS), recorded in memory."""
    CHANNELS = ("review-app", "telegram")

    def __init__(self):
        self.requests = {}

    def request(self, kind, subject, payload, requester, trace_id=None):
        rid = f"apr-{len(self.requests) + 1:012x}"
        self.requests[rid] = {"request_id": rid, "kind": kind, "subject": subject, "payload": payload,
                              "requester": requester, "trace_id": trace_id or "", "status": "pending"}
        return rid

    def status(self, rid):
        return dict(self.requests.get(rid, {}))

    def decide(self, rid, decision, comment=""):
        self.requests[rid].update(status=decision, comment=comment)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@contextmanager
def fake_urlopen(body):
    calls = []

    def _open(req, timeout=None):
        calls.append(req)
        return _Resp(json.dumps(body).encode())

    real = urllib.request.urlopen
    urllib.request.urlopen = _open
    try:
        yield calls
    finally:
        urllib.request.urlopen = real


@contextmanager
def approvals(fake=None):
    fake = fake or FakeApprovals()
    real = srv.approvals
    srv.approvals = fake
    try:
        yield fake
    finally:
        srv.approvals = real


@contextmanager
def rest_write(flag):
    old = srv.config.ADOIT_REST_WRITE
    srv.config.ADOIT_REST_WRITE = flag
    try:
        yield
    finally:
        srv.config.ADOIT_REST_WRITE = old


def call(_tool, **args):
    async def go():
        async with Client(srv.server.mcp) as c:
            return (await c.call_tool(_tool, args)).data
    return asyncio.run(go())


def call_error(_tool, **args) -> str:
    async def go():
        async with Client(srv.server.mcp) as c:
            r = await c.call_tool(_tool, args, raise_on_error=False)
            assert r.is_error, f"{_tool} should have failed"
            return r.content[0].text
    return asyncio.run(go())


def tools():
    async def go():
        async with Client(srv.server.mcp) as c:
            return await c.list_tools()
    return asyncio.run(go())


# ---------------------------------------------------------------- tests
def test_tool_catalogue():
    listed = {t.name for t in tools()}
    assert listed == TOOLS, listed
    assert all(t.description for t in tools())


def test_build_covers_rows_containers_and_standard_views():
    spec = json.loads(json.dumps(SPEC))
    spec["views"] = [{"id": "grid", "title": "Grid", "rows": [["portal", "api", "svc"], ["claim"]],
                      "containers": [{"id": "portal", "children": ["api"]}]}]
    spec["standard_views"] = True
    m = srv._build(spec)
    assert len(m.elements) == 5 and len(m.relations) == 5
    assert len(m.views) > 1                         # standard_views added the catalogue views
    assert m.views[0].vid == "grid"


def test_archimate_validate_by_value_ref_and_path():
    r = call("archimate_validate", spec=SPEC)
    assert r["elements"] == 5 and r["relations"] == 5 and r["warnings"] == []
    bad = json.loads(json.dumps(SPEC))
    bad["relations"].append({"type": "Serving", "src": "claim", "tgt": "portal"})   # passive cannot serve
    assert call("archimate_validate", spec=bad)["warnings"]
    ref = STORE.put("spec.json", json.dumps(SPEC).encode(), "application/json")
    assert call("archimate_validate", spec_ref=ref)["elements"] == 5
    p = os.path.join(TMP, "spec.json"); json.dump(SPEC, open(p, "w"))
    assert call("archimate_validate", spec_path=p)["relations"] == 5
    assert "spec_ref" in call_error("archimate_validate")                           # nothing given


def test_archimate_render_stores_refs():
    r = call("archimate_render", basename="claims", spec=SPEC)
    assert r["files"] == []                                     # nothing durable on the host without outdir
    assert r["xml_ref"].startswith("art://") and r["xml_ref"].endswith("/claims.archimate.xml")
    assert set(r["svg_refs"]) == {"landscape"}
    assert r["violations"] == [] and isinstance(r["warnings"], list) and r["views"]
    xml = STORE.get(r["xml_ref"]).decode()
    assert xml.count("<element ") == 5 and xml.count("<relationship ") == 5
    assert STORE.get(r["svg_refs"]["landscape"]).lstrip().startswith(b"<svg")
    assert STORE.info(r["xml_ref"])["content_type"] == "application/xml"


def test_archimate_render_outdir_ref_and_lenient():
    out = os.path.join(TMP, "out")
    ref = STORE.put("claims.spec.json", json.dumps(SPEC).encode(), "application/json")
    r = call("archimate_render", basename="claims", spec_ref=ref, outdir=out, strict=False)
    assert len(r["files"]) == 2 and all(os.path.exists(f) for f in r["files"])       # kept locally
    assert os.path.exists(os.path.join(out, "claims.archimate.xml"))
    assert r["violations"] == []
    assert "spec_ref" in call_error("archimate_render", basename="x")


def test_adoit_excel_render():
    r = call("adoit_excel_render", basename="claims", spec=SPEC)
    assert "path" not in r and r["xlsx_ref"].endswith("/claims.objects.xlsx")
    assert r["objects"] == 5 and r["skipped"] == [] and r["relations"] >= 3
    assert "Application Component" in r["sheets"]
    assert STORE.get(r["xlsx_ref"])[:2] == b"PK"                                      # a real xlsx (zip)
    assert "spec_ref" in call_error("adoit_excel_render", basename="x")


def test_adoit_repos_uses_credential_shape():
    with fake_urlopen({"items": [{"id": "{repo-1}", "name": "Lab"}]}) as calls:
        r = call("adoit_repos")
    assert r == {"items": [{"id": "{repo-1}", "name": "Lab"}]}
    req = calls[0]
    assert req.full_url == "https://adoit.test/ADOIT/rest/2.0/repos"
    assert req.get_header("Authorization").startswith("Basic ") and req.get_header("Accept") == "application/json"


def test_adoit_search_and_object():
    items = {"items": [{"id": "{o1}", "name": "Portal", "metaName": "C_APPLICATION_COMPONENT",
                        "artefactType": "REPOSITORY_OBJECT", "groupId": "{g}"}]}
    with fake_urlopen(items) as calls:
        r = call("adoit_search", name_like="port", class_name="ApplicationComponent", scope="all")
    assert r == [{"id": "{o1}", "name": "Portal", "class": "ApplicationComponent", "className": "C_APPLICATION_COMPONENT",
                  "artefactType": "REPOSITORY_OBJECT", "groupId": "{g}", "modelId": None, "modelName": None}]
    assert "/search?query=" in calls[0].full_url
    with fake_urlopen({"items": []}):
        assert call("adoit_search", class_name="Node") == []
    assert "name_like or class_name" in call_error("adoit_search")                    # empty filter rejected
    obj = {"item": {"id": "{o1}", "name": "Portal", "metaName": "C_APPLICATION_COMPONENT", "groupId": "{g}",
                    "attributes": [{"name": "Description", "value": "d"}],
                    "relations": [{"name": "Composition", "targets": [{"id": "{o2}", "name": "API", "metaName": "C_APPLICATION_INTERFACE"}]}]}}
    with fake_urlopen(obj) as calls:
        r = call("adoit_object", object_id="{o1}")
    assert calls[0].full_url.endswith("/objects/{o1}")
    assert r["class"] == "ApplicationComponent" and r["relations"][0]["target_class"] == "ApplicationInterface"
    with fake_urlopen({"item": {"id": "{x}"}}):
        assert call("adoit_object", object_id="{x}")["relations"] == []


def _render_refs():
    r = call("archimate_render", basename="claims", spec=SPEC)
    x = call("adoit_excel_render", basename="claims", spec=SPEC)
    return r["xml_ref"], r["svg_refs"], x["xlsx_ref"]


def test_request_import_publishes_approval_event():
    xml_ref, svg_refs, xlsx_ref = _render_refs()
    with approvals() as fake:
        r = call("adoit_request_import", xml_ref=xml_ref, model_name="Claims Portal",
                 summary={"elements": 5}, svg_refs=svg_refs, xlsx_ref=xlsx_ref)
        assert r["status"] == "pending" and r["channels"] == ["review-app", "telegram"]
        assert r["review_app"] == config.REVIEW_APP_URL
        rid = r["request_id"]
        st = fake.requests[rid]
        assert st["kind"] == "adoit-import" and st["subject"] == "Claims Portal"
        assert st["requester"] == "ea-modeling-agent"
        assert st["payload"] == {"xml_ref": xml_ref, "svg_refs": svg_refs, "xlsx_ref": xlsx_ref,
                                 "summary": {"elements": 5}}
        # svg_refs omitted -> {} ; custom requester
        r2 = call("adoit_request_import", xml_ref=xml_ref, model_name="M", summary={}, requester="arch")
        assert fake.requests[r2["request_id"]]["payload"]["svg_refs"] == {}
        assert fake.requests[r2["request_id"]]["requester"] == "arch"
        # unknown / malformed ref fails fast, nothing published
        n = len(fake.requests)
        assert call_error("adoit_request_import", xml_ref="art://nope/x.xml", model_name="M", summary={})
        assert call_error("adoit_request_import", xml_ref="/tmp/x.xml", model_name="M", summary={})
        assert len(fake.requests) == n


NEVER_CLAIMED = ("executes here", "executes", "changeset runs", "is running")


def test_import_status_file_import_path():
    xml_ref, _svg, _x = _render_refs()
    with approvals() as fake, rest_write(False):
        rid = call("adoit_request_import", xml_ref=xml_ref, model_name="M", summary={})["request_id"]
        st = call("adoit_import_status", request_id=rid)
        assert st["status"] == "pending" and "awaiting" in st["next"]
        assert st["write_path"] == "file-import" and st["rest_write_enabled"] is False
        fake.decide(rid, "approve")
        st = call("adoit_import_status", request_id=rid)
        assert st["status"] == "approve" and st["write_path"] == "file-import"
        assert "file-import" in st["next"] and "adoit_import_instructions" in st["next"]
        assert "ADOIT_REST_WRITE=false" in st["next"]
        fake.decide(rid, "decline")
        assert "do not import" in call("adoit_import_status", request_id=rid)["next"]
        fake.decide(rid, "update", "rename X")
        st = call("adoit_import_status", request_id=rid)
        assert "changes requested" in st["next"] and st["comment"] == "rename X"
        fake.requests[rid]["status"] = "weird"
        assert call("adoit_import_status", request_id=rid)["next"] == ""
        assert "unknown request" in call_error("adoit_import_status", request_id="apr-000000000000")


def test_import_status_rest_enabled_tells_the_truth():
    """F1: with ADOIT_REST_WRITE=true nothing calls the write facade, so the tool must not claim a
    changeset executes; file-import remains the release path and the flag is reported separately."""
    xml_ref, _svg, _x = _render_refs()
    with approvals() as fake, rest_write(True):
        rid = call("adoit_request_import", xml_ref=xml_ref, model_name="M", summary={})["request_id"]
        st = call("adoit_import_status", request_id=rid)
        assert st["write_path"] == "file-import" and st["rest_write_enabled"] is True
        fake.decide(rid, "approve")
        st = call("adoit_import_status", request_id=rid)
        nxt = st["next"]
        assert st["write_path"] == "file-import" and st["rest_write_enabled"] is True
        assert "ENABLED" in nxt and "not implemented" in nxt and "file-import" in nxt, nxt
        assert not any(c in nxt.lower() for c in NEVER_CLAIMED), nxt
        for status in ("pending", "decline", "update"):
            fake.requests[rid]["status"] = status
            out = call("adoit_import_status", request_id=rid)
            assert out["write_path"] == "file-import" and out["rest_write_enabled"] is True
            assert not any(c in out["next"].lower() for c in NEVER_CLAIMED)


def test_import_status_never_writes_to_adoit():
    """Neither toggle value touches the ADOIT REST API from adoit_import_status."""
    xml_ref, _svg, _x = _render_refs()
    for flag in (False, True):
        with approvals() as fake, rest_write(flag), fake_urlopen({"item": {}}) as calls:
            rid = call("adoit_request_import", xml_ref=xml_ref, model_name="M", summary={})["request_id"]
            fake.decide(rid, "approve")
            call("adoit_import_status", request_id=rid)
        assert calls == [], f"REST touched with ADOIT_REST_WRITE={flag}"


def test_import_instructions():
    txt = call("adoit_import_instructions")
    assert "https://adoit.test/ADOIT" in txt
    assert "A) OBJECTS" in txt and "B) VIEWS" in txt and "Import objects from Excel" in txt
    assert "Human approval is required" in txt


def test_main_env_check_and_serve():
    import lab.substrate.mcpserver as ms
    served = []
    real = ms.serve
    ms.serve = lambda mcp, service, port, **kw: served.append((service, port, type(mcp).__name__))
    try:
        runpy.run_path(SERVER, run_name="__main__")
        assert served == [("adoit-mcp", config.ADOIT_MCP_PORT, "FastMCP")]
        pw = os.environ.pop("ADOIT_PASSWORD")
        try:
            runpy.run_path(SERVER, run_name="__main__")
        except SystemExit as e:
            assert "ADOIT_PASSWORD" in str(e) and "source .env" in str(e)
        else:
            raise AssertionError("missing env var must exit")
        finally:
            os.environ["ADOIT_PASSWORD"] = pw
        assert len(served) == 1                                       # not served on the failed start
    finally:
        ms.serve = real


def test_integration_real_approvals_on_local_redis():
    """INTEGRATION: the real lab.substrate.approvals over the local brew Redis; skipped when it is down."""
    from lab.substrate import approvals as real_approvals
    url = config.REDIS_URL
    if not any(h in url for h in ("127.0.0.1", "localhost")):
        print("  (skip: REDIS_URL is not local)"); return
    try:
        r = real_approvals._r(); r.ping()
    except Exception:
        print("  (skip: local Redis not reachable)"); return
    xml_ref, _svg, _x = _render_refs()
    assert srv.approvals is real_approvals
    rid = call("adoit_request_import", xml_ref=xml_ref, model_name="IT test", summary={"t": 1})["request_id"]
    try:
        assert call("adoit_import_status", request_id=rid)["status"] == "pending"
        real_approvals.decide(rid, "approve", "test", "cli", "ok")
        st = call("adoit_import_status", request_id=rid)
        assert st["status"] == "approve" and st["decided_via"] == "cli" and st["payload"]["xml_ref"] == xml_ref
    finally:
        r.delete(f"approvals:req:{rid}"); r.srem("approvals:pending", rid)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
