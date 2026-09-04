"""src/lab/substrate/mcp/adoit/adoit_rest.py — the ADOIT 18 REST 2.0 facade, OFFLINE against a fake
`urllib.request.urlopen` that records every request and returns canned bodies.
Covers: credential shape (_cfg / Basic auth header), url-encoding of the search JSON, the
className <-> ArchiMate maps, search/get_object/object_impact reads, the DORMANT write facade
(create/patch/delete/relation — bodies asserted against the documented BOC shapes), HTTP 4xx/5xx
propagation and the hosted-CE edge BLOCK PAGE (HTML instead of JSON -> a clear ValueError).
Run: .venv/bin/python tests/unit/substrate/mcp/adoit/test_adoit_rest.py   (also pytest-compatible)"""
import base64
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager


FAKE_ENV = {"ADOIT_BASE_URL": "https://adoit.test/ADOIT/", "ADOIT_USERNAME": "lab-user",
            "ADOIT_PASSWORD": "s3cret", "ADOIT_REPO_ID": "{repo-1234}"}
os.environ.update(FAKE_ENV)

from lab.substrate.mcp.adoit import adoit_rest as R  # noqa: E402

BASE = "https://adoit.test/ADOIT/rest/2.0/repos/{repo-1234}"   # braces kept (safe="{}")
BLOCK_PAGE = "<html><head><title>Error</title></head><body>URL not available on this server</body></html>"


class _Resp(io.BytesIO):
    """Just enough of an HTTP response: a readable context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@contextmanager
def fake_urlopen(body="{}", status=200):
    """Swap urllib.request.urlopen (the attribute adoit_rest resolves at call time) for a recorder.
    `body` may be a str/dict or a callable(req) -> str/dict; status >= 400 raises HTTPError."""
    calls = []

    def _open(req, timeout=None):
        calls.append(req)
        b = body(req) if callable(body) else body
        raw = json.dumps(b) if isinstance(b, (dict, list)) else b
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, f"HTTP {status}", {}, io.BytesIO(raw.encode()))
        return _Resp(raw.encode())

    real = urllib.request.urlopen
    urllib.request.urlopen = _open
    try:
        yield calls
    finally:
        urllib.request.urlopen = real


def _body(req):
    return json.loads(req.data.decode()) if req.data else None


def test_class_and_relation_maps():
    assert R.archimate_to_classname("ApplicationComponent") == "C_APPLICATION_COMPONENT"
    assert R.archimate_to_classname("CourseOfAction") == "C_COURSE_OF_ACTION"
    assert R.archimate_to_classname("WorkPackage") == "C_WORK_PACKAGE"
    assert R.archimate_to_classname("Node") == "C_NODE"
    assert R.classname_to_archimate("C_APPLICATION_COMPONENT") == "ApplicationComponent"
    assert R.classname_to_archimate("APPLICATION_COMPONENT") == "ApplicationComponent"   # no C_ prefix tolerated
    for t in ("ApplicationComponent", "CourseOfAction", "DataObject"):
        assert R.classname_to_archimate(R.archimate_to_classname(t)) == t
    for rel in ("Composition", "Serving", "Realization", "Assignment", "Access", "Aggregation",
                "Association", "Triggering", "Flow", "Influence", "Specialization"):
        assert R.archimate_to_relclass(rel) == "RC_" + rel.upper()
    assert R.archimate_to_relclass("SomeTwoWords") == "RC_SOME_TWO_WORDS"


def test_cfg_builds_basic_auth_and_keeps_braces():
    base, repo, auth = R._cfg()
    assert base == "https://adoit.test/ADOIT"                     # trailing slash stripped
    assert repo == "{repo-1234}"                                  # braces kept — ADOIT expects them
    assert base64.b64decode(auth).decode() == "lab-user:s3cret"


def test_req_get_headers_url_and_empty_body():
    with fake_urlopen("") as calls:                                # 204-style empty body -> {}
        assert R._get("/objects/x") == {}
    req = calls[0]
    assert req.get_method() == "GET" and req.data is None
    assert req.full_url == BASE + "/objects/x"
    assert req.get_header("Authorization") == "Basic " + base64.b64encode(b"lab-user:s3cret").decode()
    assert req.get_header("Accept") == "application/json"
    assert req.get_header("Content-type") is None


def test_req_json_body_sets_content_type_and_method():
    with fake_urlopen({"ok": 1}) as calls:
        assert R._req("PATCH", "/objects/o1", {"name": "N"}, timeout=5) == {"ok": 1}
    req = calls[0]
    assert req.get_method() == "PATCH" and _body(req) == {"name": "N"}
    assert req.get_header("Content-type") == "application/json"


def test_http_errors_propagate_as_httperror():
    for status in (400, 401, 404, 429, 500, 503):
        with fake_urlopen({"message": "nope"}, status=status):
            try:
                R._get("/objects/o1")
            except urllib.error.HTTPError as e:
                assert e.code == status
            else:
                raise AssertionError(f"expected HTTPError {status}")


def test_ce_edge_block_page_is_a_clear_error():
    """The hosted CE edge answers write verbs with an HTML block page (HTTP 200, not JSON)."""
    with fake_urlopen(BLOCK_PAGE) as calls:
        try:
            R.create_object("Portal", "ApplicationComponent")
        except ValueError as e:
            msg = str(e)
            assert "POST /objects" in msg and "not JSON" in msg and "edge" in msg.lower(), msg
            assert "URL not available" in msg
        else:
            raise AssertionError("expected ValueError for the HTML block page")
    assert calls[0].get_method() == "POST"


def test_build_query_shapes_and_scopes():
    q = R.build_query("portal", "ApplicationComponent", "all")
    assert q == {"filters": [{"className": "C_APPLICATION_COMPONENT"},
                             {"attrName": "NAME", "op": "OP_LIKE", "value": "portal"}],
                 "scope": {"repoObjects": True, "models": True, "modObjects": True}}
    assert R.build_query(class_name="C_NODE")["filters"] == [{"className": "C_NODE"}]   # raw class kept
    assert R.build_query("x")["scope"] == {"repoObjects": True}                          # default scope
    assert R.build_query("x", scope="models")["scope"] == {"models": True}
    assert R.build_query("x", scope="bogus")["scope"] == {"repoObjects": True}           # unknown -> objects
    try:
        R.build_query()
    except ValueError as e:
        assert "400" in str(e)
    else:
        raise AssertionError("empty filter must be rejected before the wire")


SEARCH_ITEMS = {"items": [
    {"id": "{o1}", "name": "Portal", "type": "Application Component", "artefactType": "REPOSITORY_OBJECT",
     "metaName": "C_APPLICATION_COMPONENT", "groupId": "{g1}", "modelId": None, "modelName": None},
    {"id": "{m1}", "name": "Landscape", "type": "Diagram", "artefactType": "DIAGRAM",
     "groupId": "{g2}", "modelId": "{m1}", "modelName": "Landscape"},          # no metaName -> type used
    {"id": "{o3}", "name": "Third", "metaName": "C_NODE", "artefactType": "REPOSITORY_OBJECT"},
]}


def test_search_encodes_query_and_maps_items():
    with fake_urlopen(SEARCH_ITEMS) as calls:
        res = R.search("port", "ApplicationComponent", "all", limit=2)
    url = calls[0].full_url
    assert url.startswith(BASE + "/search?query=")
    encoded = url.split("query=", 1)[1]
    assert " " not in encoded and "{" not in encoded                                  # url-encoded
    assert json.loads(urllib.parse.unquote(encoded)) == R.build_query("port", "ApplicationComponent", "all")
    assert len(res) == 2                                                             # limit applied
    assert res[0] == {"id": "{o1}", "name": "Portal", "class": "ApplicationComponent",
                      "className": "C_APPLICATION_COMPONENT", "artefactType": "REPOSITORY_OBJECT",
                      "groupId": "{g1}", "modelId": None, "modelName": None}
    assert res[1]["class"] == "Diagram" and res[1]["className"] is None
    with fake_urlopen({"items": None}):
        assert R.search("x") == []
    with fake_urlopen({}):
        assert R.search(class_name="Node") == []


OBJECT = {"item": {
    "id": "{o1}", "name": "Portal", "metaName": "C_APPLICATION_COMPONENT", "groupId": "{g1}",
    "attributes": [
        {"name": "Description", "value": "Web front end"},
        {"name": "Empty", "value": ""},
        {"name": "Multi", "value": None, "values": ["a", "b"]},
        {"name": "Nothing", "value": None, "values": []},
    ] + [{"name": f"Attr{i}", "value": f"v{i}"} for i in range(20)],
    "relations": [
        {"name": "Composition", "metaName": "RC_COMPOSITION",
         "targets": [{"id": "{o2}", "name": "Adjudication", "metaName": "C_APPLICATION_COMPONENT", "direction": "outgoing"}]},
        {"name": "Serving", "metaName": "RC_SERVING", "targets": []},
        {"name": "Access", "metaName": "RC_ACCESS", "targets": None},
        {"name": "Realization", "targets": [{"id": "{s1}", "name": "Svc", "type": "Application Service", "direction": "outgoing"}]},
    ]}}


def test_get_object_trims_attributes_and_flattens_relations():
    with fake_urlopen(OBJECT) as calls:
        obj = R.get_object("{o1}", keep_attrs=5)
    assert calls[0].full_url == BASE + "/objects/{o1}"
    assert obj["id"] == "{o1}" and obj["class"] == "ApplicationComponent" and obj["className"] == "C_APPLICATION_COMPONENT"
    assert obj["groupId"] == "{g1}"
    assert len(obj["attributes"]) == 5                                              # keep_attrs cap
    assert obj["attributes"][0] == {"name": "Description", "value": "Web front end"}
    assert obj["attributes"][1] == {"name": "Multi", "value": ["a", "b"]}            # values fallback; empties dropped
    assert obj["relations"] == [
        {"type": "Composition", "direction": "outgoing", "target_id": "{o2}", "target_name": "Adjudication",
         "target_class": "ApplicationComponent"},
        {"type": "Realization", "direction": "outgoing", "target_id": "{s1}", "target_name": "Svc",
         "target_class": "Application Service"},
    ]
    with fake_urlopen({}):                                                          # missing item -> empty shell
        empty = R.get_object("{zz}")
    assert empty["id"] is None and empty["attributes"] == [] and empty["relations"] == []
    with fake_urlopen({"item": {"id": "{t}", "type": "Thing", "relations": None}}):
        assert R.get_object("{t}")["class"] == "Thing"                              # no metaName -> type


def test_create_object_body_matches_boc_shape():
    with fake_urlopen({"item": {"id": "{new}"}}) as calls:
        res = R.create_object("Portal", "ApplicationComponent", description="Web front end")
    assert res == {"item": {"id": "{new}"}}
    req = calls[0]
    assert req.get_method() == "POST" and req.full_url == BASE + "/objects"
    assert _body(req) == {"name": "Portal", "metaName": "C_APPLICATION_COMPONENT",
                          "attributes": [{"metaName": "A_DESCRIPTION", "value": "Web front end"}]}
    # raw className kept; explicit A_DESCRIPTION not duplicated by `description`
    with fake_urlopen({}) as calls:
        R.create_object("N", "C_NODE", attributes=[{"metaName": "A_DESCRIPTION", "value": "x"}], description="y")
    assert _body(calls[0]) == {"name": "N", "metaName": "C_NODE",
                               "attributes": [{"metaName": "A_DESCRIPTION", "value": "x"}]}
    with fake_urlopen({}) as calls:
        R.create_object("N", "Node")                                                 # no attributes key at all
    assert _body(calls[0]) == {"name": "N", "metaName": "C_NODE"}


def test_patch_object_sends_only_changes():
    with fake_urlopen({}) as calls:
        R.patch_object("{o1}", name="Portal v2")
    assert calls[0].get_method() == "PATCH" and calls[0].full_url == BASE + "/objects/{o1}"
    assert _body(calls[0]) == {"name": "Portal v2"}
    with fake_urlopen({}) as calls:
        R.patch_object("{o1}", attributes=[{"metaName": "A_DESCRIPTION", "value": "d"}])
    assert _body(calls[0]) == {"attributes": [{"metaName": "A_DESCRIPTION", "value": "d"}]}
    with fake_urlopen({}) as calls:
        try:
            R.patch_object("{o1}")
        except ValueError as e:
            assert "name and/or attributes" in str(e)
        else:
            raise AssertionError("empty patch must be rejected")
    assert calls == []                                                               # nothing hit the wire


def test_delete_object():
    with fake_urlopen("") as calls:
        assert R.delete_object("{o1}") == {}
    assert calls[0].get_method() == "DELETE" and calls[0].full_url == BASE + "/objects/{o1}"
    assert calls[0].data is None


def test_create_relation_path_body_and_direction():
    with fake_urlopen({}) as calls:
        R.create_relation("{o1}", "Composition", "{o2}")
    req = calls[0]
    assert req.get_method() == "POST"
    assert req.full_url == BASE + "/objects/{o1}/relations/outgoing/RC_COMPOSITION"
    assert _body(req) == {"toId": "{o2}"}
    with fake_urlopen({}) as calls:
        R.create_relation("{o1}", "RC_SERVING", "{o2}", direction="Incoming")       # raw class + case-insensitive dir
    assert calls[0].full_url.endswith("/relations/incoming/RC_SERVING")
    with fake_urlopen({}) as calls:
        try:
            R.create_relation("{o1}", "Serving", "{o2}", direction="sideways")
        except ValueError as e:
            assert "outgoing" in str(e) and "incoming" in str(e)
        else:
            raise AssertionError("bad direction must be rejected")
    assert calls == []


def test_object_impact_collects_distinct_hosting_views():
    hits = {"items": [
        {"artefactType": "MODINST", "modelId": "{m1}", "modelName": "Landscape"},
        {"artefactType": "MODINST", "modelId": "{m1}", "modelName": "Landscape"},   # duplicate view
        {"artefactType": "MODINST", "modelId": "{m2}", "modelName": "Integration"},
        {"artefactType": "REPOSITORY_OBJECT", "modelId": None},                    # not a placement
        {"artefactType": "MODINST", "modelId": None},
    ]}
    with fake_urlopen(hits) as calls:
        views = R.object_impact("{o1}", name="Portal")
    assert views == [{"view_id": "{m1}", "view_name": "Landscape"}, {"view_id": "{m2}", "view_name": "Integration"}]
    q = json.loads(urllib.parse.unquote(calls[0].full_url.split("query=", 1)[1]))
    assert q == {"filters": [{"attrName": "NAME", "op": "OP_LIKE", "value": "Portal"}], "scope": {"modObjects": True}}
    # name not supplied -> read from the object first (two calls), then search
    with fake_urlopen(lambda req: OBJECT if "/objects/" in req.full_url else hits) as calls:
        assert len(R.object_impact("{o1}", limit=1)) == 1
    assert len(calls) == 2 and "/objects/{o1}" in calls[0].full_url and "/search?" in calls[1].full_url
    # object without a name -> nothing to search
    with fake_urlopen({"item": {"id": "{x}"}}) as calls:
        assert R.object_impact("{x}") == []
    assert len(calls) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
