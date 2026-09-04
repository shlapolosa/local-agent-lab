"""src/lab/substrate/mcp/semantic/server.py — all 13 tools through an in-memory fastmcp Client, OFFLINE:
REFERENCE_MODELS_DIR is an EMPTY temp dir (the licensed BA Guild workbooks are never required),
a SYNTHETIC SkosScheme pair is injected into the running service/registry/store, and the artifact
store is a temp LocalStore overriding the server container's `artifacts` provider. Every question in service.QUESTIONS is asked over a small loaded model.
Run: .venv/bin/python tests/unit/substrate/mcp/semantic/test_server.py   (also pytest-compatible)"""
import asyncio
import importlib.util
import json
import os
import runpy
import sys
import tempfile

import pytest
from fastmcp import Client
from rdflib import URIRef

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lab.core.semantic.service import QUESTIONS
from lab.core.semantic.skos import SkosScheme
from lab.platform import config
from lab.substrate import artifacts

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
SERVER = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "semantic", "server.py")

TMP = srv = STORE = None            # set up by `_server` (never at import: it pins the environment)

TOOLS = {"semantic_ontologies", "semantic_describe", "semantic_classify", "semantic_check",
         "semantic_validate_model", "semantic_load_model", "semantic_query", "semantic_schemes",
         "semantic_concepts", "semantic_export_archimate", "semantic_store_spec", "semantic_questions",
         "semantic_ask"}


def _scheme(name, title, extra=()):
    concepts = [
        {"id": "c1", "label": "Care Delivery", "definition": "Deliver care", "kind": "capability",
         "parent": None, "level": 1, "tier": 1},
        {"id": "c2", "label": "Triage", "definition": "Sort by urgency", "kind": "capability",
         "parent": "c1", "level": 2, "tier": 1},
        {"id": "c3", "label": "Discharge", "definition": "", "kind": "capability", "parent": "c1", "level": 2, "tier": 1},
        {"id": "c4", "label": "Discharge Letter", "definition": "", "kind": "capability", "parent": "c3", "level": 3, "tier": 1},
        {"id": "c5", "label": "Billing", "definition": "", "kind": "capability", "parent": None, "level": 1, "tier": 2},
        {"id": "v1", "label": "Admit Patient", "definition": "", "kind": "value-stream", "parent": None, "level": 1, "tier": None},
    ] + list(extra)
    return SkosScheme(name, f"urn:lab:semantic:ref:{name}#", title, concepts, source="in-code fixture")


def _inject(sc):
    """Register a synthetic scheme exactly where SemanticService.__init__ would have put a loaded one."""
    srv.S.registry.add(sc); srv.S.schemes_[sc.name] = sc
    g = srv.S.store.ds.graph(URIRef(f"urn:lab:semantic:vocab:{sc.name}"))
    for t in sc.graph():
        g.add(t)


@pytest.fixture(scope="module", autouse=True)
def _server():
    """Compose the server the way its own `__main__` would, but against an EMPTY reference dir and a
    temp artifact store. `lab.platform.config` reads the env once at import and the server composes at
    import (`SemanticService(reference_dir=config.REFERENCE_MODELS_DIR)`), so both the environment and
    the config module are pinned HERE — around the import — instead of at this module's import, where
    they would leak into every other test module. Undone when the module's last test finishes."""
    global TMP, srv, STORE
    mp = pytest.MonkeyPatch()
    TMP = tempfile.mkdtemp(prefix="semantic-mcp-test-")
    ref_dir = os.path.join(TMP, "no-ref-models")
    os.makedirs(ref_dir)
    mp.setenv("REFERENCE_MODELS_DIR", ref_dir)
    mp.setenv("MCP_SHARED_SECRET", "shh")
    for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "UPLOADS_URL", "DATABASE_URL"):
        mp.delenv(k, raising=False)
    mp.setattr(config, "REFERENCE_MODELS_DIR", ref_dir)          # config already read the real env

    spec = importlib.util.spec_from_file_location("semantic_mcp_server", SERVER)
    srv = importlib.util.module_from_spec(spec)
    sys.modules["semantic_mcp_server"] = srv
    spec.loader.exec_module(srv)

    STORE = artifacts.LocalStore(os.path.join(TMP, "store"))
    srv.server.container.artifacts.override(STORE)       # the store the tools write to, via the kit

    assert srv.S.schemes_ == {}, "the licensed workbooks must not be loaded — REFERENCE_MODELS_DIR is empty"
    _inject(_scheme("synthetic-v1", "Synthetic Provider Ref"))
    _inject(_scheme("synthetic-v2", "Synthetic Payer Ref"))
    srv.S._link_shared_top_concepts()        # 'Care Delivery' / 'Billing' are shared top concepts
    yield
    sys.modules.pop("semantic_mcp_server", None)
    mp.undo()
    TMP = srv = STORE = None

MODEL = {
    "name": "Claims", "id": "claims",
    "elements": [
        {"id": "n1", "type": "Node", "name": "App Server"},
        {"id": "c1", "type": "ApplicationComponent", "name": "Portal", "doc": "Web front end"},
        {"id": "s1", "type": "ApplicationService", "name": "Claims Service"},
        {"id": "s2", "type": "ApplicationService", "name": "Lookup Service"},
        {"id": "i1", "type": "ApplicationInterface", "name": "Claims API"},
        {"id": "p1", "type": "BusinessProcess", "name": "Handle Claim"},
        {"id": "g1", "type": "Goal", "name": "Faster claims"},
        {"id": "r1", "type": "Requirement", "name": "Sub-second lookup"},
    ],
    "relations": [
        {"id": "x1", "type": "Serving", "src": "n1", "tgt": "c1"},
        {"id": "x2", "type": "Realization", "src": "c1", "tgt": "s1"},
        {"id": "x3", "type": "Realization", "src": "c1", "tgt": "s2"},
        {"id": "x4", "type": "Composition", "src": "c1", "tgt": "i1"},
        {"id": "x5", "type": "Assignment", "src": "i1", "tgt": "s1"},
        {"id": "x6", "type": "Serving", "src": "s1", "tgt": "p1"},
        {"id": "x7", "type": "Serving", "src": "s2", "tgt": "p1"},           # consumed, no interface -> warning
        {"id": "x8", "type": "Realization", "src": "c1", "tgt": "g1"},
        {"id": "x9", "type": "Realization", "src": "c1", "tgt": "r1"},
    ],
}


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


def test_tool_catalogue():
    assert {t.name for t in tools()} == TOOLS


def test_ontologies_describe_classify_check():
    names = {o["name"]: o for o in call("semantic_ontologies")}
    assert names["archimate-3.1"]["kind"] == "metamodel" and names["archimate-3.1"]["classes"] > 50
    assert names["synthetic-v1"] == {"name": "synthetic-v1", "kind": "skos-scheme", "concepts": 6}
    card = call("semantic_describe", type="ApplicationComponent")
    assert card["type"] == "ApplicationComponent" and card["layer"] and card["aspect"]
    assert "not a archimate-3.1 type" in call_error("semantic_describe", type="Widget")
    assert "not a metamodel vocabulary" in call_error("semantic_describe", type="Node", vocab="synthetic-v1")
    assert "unknown vocabulary" in call_error("semantic_describe", type="Node", vocab="nope")
    cands = call("semantic_classify", text="REST API exposed by the backend component", limit=3)
    assert len(cands) == 3 and all(c["type"] for c in cands)
    ok = call("semantic_check", source="ApplicationComponent", relation="Realization", target="ApplicationService")
    assert ok["ok"] is True and "Realization" in ok["allowed"]
    bad = call("semantic_check", source="DataObject", relation="Serving", target="ApplicationComponent")
    assert bad["ok"] is False and "Serving" not in bad["allowed"]


def test_validate_model_legal_illegal_ref_and_errors():
    r = call("semantic_validate_model", spec=MODEL)
    assert r["illegal"] == [] and r["elements"] == 8 and r["relations"] == 9
    assert len(r["warnings"]) == 1 and r["warnings"][0].startswith("s2 (ApplicationService) is consumed")
    bad = json.loads(json.dumps(MODEL))
    bad["relations"] += [{"type": "Serving", "src": "g1", "tgt": "c1"},                  # motivation cannot serve
                         {"id": "dangling", "type": "Serving", "src": "ghost", "tgt": "c1"},
                         {"type": "Serving", "src": "i1", "tgt": "p1"}]                  # interface serving -> warning
    r = call("semantic_validate_model", spec=bad)
    ids = {i.get("id") or i.get("relation", {}).get("id") for i in r["illegal"]}
    assert ids == {"r10", "dangling"}, r["illegal"]
    assert any(i.get("reason") == "endpoint not declared" for i in r["illegal"])
    first = next(i for i in r["illegal"] if i.get("id") == "r10")
    assert first["types"] == "Goal -> ApplicationComponent" and isinstance(first["allowed"], list)
    assert any("interfaces expose services" in w for w in r["warnings"])
    ref = STORE.put("m.spec.json", json.dumps(MODEL).encode(), "application/json")
    assert call("semantic_validate_model", spec_ref=ref)["illegal"] == []
    assert "spec_ref" in call_error("semantic_validate_model")                            # nothing given
    assert call_error("semantic_validate_model", spec={"name": "x"})                       # no elements
    assert "unknown vocabulary" in call_error("semantic_validate_model", spec=MODEL, vocab="nope")


def test_store_spec_dict_and_json_string():
    r = call("semantic_store_spec", spec=MODEL, name="claims.spec.json")
    assert r["spec_ref"].startswith("art://") and r["spec_ref"].endswith("/claims.spec.json")
    assert (r["name"], r["elements"], r["relations"], r["views"]) == ("claims.spec.json", 8, 9, 0)
    assert json.loads(STORE.get(r["spec_ref"])) == MODEL
    s = call("semantic_store_spec", spec=json.dumps(MODEL))
    assert s["name"] == "model.spec.json" and s["elements"] == 8
    assert json.loads(STORE.get(s["spec_ref"])) == MODEL
    assert "not valid JSON" in call_error("semantic_store_spec", spec="{nope")
    assert "JSON object" in call_error("semantic_store_spec", spec="[1,2]")
    assert "spec_ref" in call_error("semantic_store_spec", spec="")


def test_load_query_questions_and_every_ask():
    r = call("semantic_load_model", spec=MODEL, model_id="claims")
    assert r["model"].endswith("claims") and r["triples"] > 40 and r["derived_relations"] > 0
    q = call("semantic_query", sparql="PREFIX am: <urn:lab:semantic:archimate#> SELECT ?c WHERE { ?c a am:ApplicationComponent }")
    assert q["count"] == 1 and q["columns"] == ["c"]
    capped = call("semantic_query", sparql="SELECT ?s WHERE { ?s ?p ?o }", limit=3)
    assert len(capped["rows"]) == 3
    assert call("semantic_questions") == {k: {"params": v["params"], "doc": v["doc"]} for k, v in QUESTIONS.items()}
    params = {"node": "App Server", "element": "Claims Service", "label": "Care Delivery"}
    seen = {}
    for name, q in QUESTIONS.items():
        seen[name] = call("semantic_ask", question=name, params={p: params[p] for p in q["params"]})
        assert set(seen[name]) >= {"question", "columns", "rows", "count"}, name
    assert seen["goals_realized_by_components_on_node"]["rows"] == [["App Server", "Portal", "Faster claims"]]
    assert seen["what_serves"]["rows"] and seen["what_serves"]["rows"][0][2] == "Handle Claim"
    assert [r[0] for r in seen["services_without_interface"]["rows"]] == ["Lookup Service"]
    assert {r[2] for r in seen["concepts_under"]["rows"]} == {"Triage", "Discharge", "Discharge Letter"}
    assert {r[0] for r in seen["shared_reference_concepts"]["rows"]} == {"Care Delivery", "Billing"}
    assert seen["elements_by_layer_aspect"]["count"] == 8
    assert seen["goals_realized_by_components_on_node"]["question"] == QUESTIONS["goals_realized_by_components_on_node"]["doc"]
    assert call("semantic_ask", question="services_without_interface")["count"] == 1     # params omitted
    assert "unknown question" in call_error("semantic_ask", question="who_knows")
    assert "missing params ['node']" in call_error("semantic_ask", question="goals_realized_by_components_on_node")


def test_schemes_and_concepts():
    sch = {s["name"]: s for s in call("semantic_schemes")}
    assert set(sch) == {"synthetic-v1", "synthetic-v2"}
    assert sch["synthetic-v1"]["counts"] == {"capability": {"L1": 2, "L2": 2, "L3": 1}, "value-stream": {"L1": 1}}
    assert sch["synthetic-v1"]["source"] == "in-code fixture"
    allc = call("semantic_concepts", scheme="synthetic-v1")
    assert [c["label"] for c in allc] == ["Care Delivery", "Triage", "Discharge", "Discharge Letter", "Billing"]
    sub = call("semantic_concepts", scheme="synthetic-v1", root_label="Discharge", depth=0)
    assert sub == [{"id": "c3", "label": "Discharge", "level": 2, "tier": 1, "parent": "c1", "definition": ""}]
    assert [c["label"] for c in call("semantic_concepts", scheme="synthetic-v1", kind="value-stream")] == ["Admit Patient"]
    assert "unknown scheme" in call_error("semantic_concepts", scheme="nope")
    assert "no capability named 'Nope'" in call_error("semantic_concepts", scheme="synthetic-v1", root_label="Nope")


def test_export_archimate_by_ref_inline_subtree_and_errors():
    r = call("semantic_export_archimate", scheme="synthetic-v1")
    assert r["spec_ref"].startswith("art://") and r["spec_path"] is None
    assert (r["elements"], r["relations"], r["views"]) == (5, 3, 2)          # overview + 1 branch (Billing has no kids)
    spec = json.loads(STORE.get(r["spec_ref"]))
    assert spec["id"] == "synthetic-v1" and r["id"] == "synthetic-v1" and r["name"] == spec["name"]
    assert all(e["type"] == "Capability" for e in spec["elements"])
    assert spec["views"][0]["rows"] == [["c1", "c5"]] and spec["views"][1]["containers"] == [{"id": "c1", "children": ["c2", "c3"]}]
    inline = call("semantic_export_archimate", scheme="synthetic-v1", root_label="Care Delivery", depth=1, by_ref=False)
    assert {e["id"] for e in inline["elements"]} == {"c1", "c2", "c3"} and len(inline["relations"]) == 2
    assert inline["name"].endswith("under Care Delivery)") and inline["standard_views"] is False
    out = os.path.join(TMP, "exports", "vs.spec.json")
    vs = call("semantic_export_archimate", scheme="synthetic-v1", kind="value-stream", views="overview", out_path=out)
    assert vs["spec_path"] == out and json.load(open(out))["elements"][0]["type"] == "ValueStream"
    assert vs["views"] == 1
    assert "unknown scheme" in call_error("semantic_export_archimate", scheme="nope")
    assert "no capability named 'Nope'" in call_error("semantic_export_archimate", scheme="synthetic-v1", root_label="Nope")


def test_span_attributes_are_the_telemetry_contract():
    """The span keys are what Jaeger/App Insights queries are written against, so they are a contract:
    assert them, or a rename slips through silently (it already did once — see the git history of
    this file's server). Recorded through the kit's overridable tracer."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(exporter))
    with srv.server.container.tracer.override(provider.get_tracer("t")):
        call("semantic_validate_model", spec=MODEL)
        call("semantic_export_archimate", scheme="synthetic-v1")
        call("semantic_ask", question="services_without_interface")
        call("semantic_store_spec", spec=MODEL)
    by = {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}
    assert set(by) == {"semantic_validate_model", "semantic_export_archimate", "semantic_ask",
                       "semantic_store_spec"}, "one span per tool call, named after the tool"
    for name, attrs in by.items():
        assert attrs["mcp.tool"] == name and attrs["mcp.server"] == "semantic-mcp"
    v = by["semantic_validate_model"]
    assert v["semantic.illegal"] == 0 and v["semantic.warnings"] == 1
    e = by["semantic_export_archimate"]
    assert e["semantic.scheme"] == "synthetic-v1" and e["semantic.elements"] == 5
    assert by["semantic_ask"]["semantic.question"] == "services_without_interface"
    st = by["semantic_store_spec"]
    assert st["semantic.spec_ref"].startswith("art://") and st["semantic.relations"] == 9


def test_main_serves():
    import lab.substrate.mcpserver as ms
    served = []
    real = ms.serve
    ms.serve = lambda mcp, service, port, **kw: served.append((service, port))
    try:
        runpy.run_path(SERVER, run_name="__main__")
    finally:
        ms.serve = real
    assert served == [("semantic-mcp", config.SEMANTIC_MCP_PORT)]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
