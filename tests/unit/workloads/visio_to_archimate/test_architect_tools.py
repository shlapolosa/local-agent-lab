"""Simulated Architect session against the accumulator tools (pure, no network). Reproduces the
live defect (Aggregation Component->Service / Component->Function, Assignment SystemSoftware->
Component) and proves the gate rejects each with the permitted list, then that the finished spec
builds through the engine with zero 'not permitted' findings.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_architect_tools.py   (also pytest-compatible)"""
import json
import sys


from lab.workloads.visio_to_archimate import architect_tools as T
from lab.core.archimate.engine import _TYPES, Model  # (on sys.path via architect_tools)
from lab.workloads import ids  # (the ONE home of the relation-id formula)


def _tools(acc):
    return {f.__name__: f for f in T.make_tools(acc)}


def _errs(rep, idx):
    return " | ".join(next(r for r in rep["rejected"] if r["index"] == idx)["errors"])


def test_vocab_from_engine():
    assert T.ELEMENT_TYPES == tuple(_TYPES.keys()) and len(T.ELEMENT_TYPES) > 60
    assert "ApplicationComponent" in T.ELEMENT_TYPES and "Realization" in T.RELATION_TYPES
    assert "Junction" not in T.RELATION_TYPES
    assert ids.rid("a", "Serving", "b") == "r-" + __import__("hashlib").md5(b"a|Serving|b").hexdigest()[:10]
    # legality goes through relrepair.check (semantic matrix), not a local table
    ok, allowed, note = T.check_relation("ApplicationComponent", "Aggregation", "ApplicationService")
    assert ok is False and "Realization" in allowed and note is None


def test_architect_session():
    acc = T.ArchitectAccumulator()
    t = _tools(acc)
    assert sorted(t) == ["add_elements", "add_relations", "add_view", "finish", "set_model"]
    for f in t.values():
        assert f.__doc__ and len(f.__doc__) > 40, f"{f.__name__} needs a docstring the model sees"

    # finish() before anything -> ok false, precise errors, never raises
    r = t["finish"]()
    assert r["ok"] is False and any("no elements" in e for e in r["errors"]) and any("set_model" in e for e in r["errors"])

    r = t["set_model"]("Local Agent Lab")
    assert r == {"ok": True, "name": "Local Agent Lab", "id": "local-agent-lab"}
    assert t["set_model"]("")["ok"] is False

    # ---- elements: the four types of the live defect + a reused ADOIT id + a data object
    r = t["add_elements"]([
        {"id": "litellm-proxy", "type": "ApplicationComponent", "name": "LiteLLM Proxy", "doc": "the gateway", "folder": "Lab"},
        {"id": "gateway-service", "type": "ApplicationService", "name": "Gateway Service"},
        {"id": "route-request", "type": "ApplicationFunction", "name": "Route Request"},
        {"id": "redis", "type": "SystemSoftware", "name": "Redis"},
        {"id": "{6f1c2a3e-1111-4222-8333-444455556666}", "type": "ApplicationComponent", "name": "ADOIT (existing)"},
        {"id": "spend-log", "type": "DataObject", "name": "Spend Log"},
        # rejected: bogus type with a suggestion, missing id, missing name, unknown field
        {"id": "x1", "type": "AppComponent", "name": "X"},
        {"type": "ApplicationComponent", "name": "no id"},
        {"id": "x3", "type": "ApplicationComponent"},
        {"id": "x4", "type": "ApplicationComponent", "name": "X4", "layer": "Application"},
    ])
    assert r["added"] == ["litellm-proxy", "gateway-service", "route-request", "redis",
                          "{6f1c2a3e-1111-4222-8333-444455556666}", "spend-log"]
    assert [x["index"] for x in r["rejected"]] == [6, 7, 8, 9] and r["total_elements"] == 6
    assert "did you mean ApplicationComponent" in _errs(r, 6), _errs(r, 6)
    assert "id is required" in _errs(r, 7)
    assert "name is required" in _errs(r, 8)
    assert "unknown field(s) ['layer']" in _errs(r, 9)
    # re-adding an id = update, never a duplicate
    r = t["add_elements"]([{"id": "redis", "type": "SystemSoftware", "name": "Redis 7", "doc": "limiter state"}])
    assert r["updated"] == ["redis"] and r["added"] == [] and r["total_elements"] == 6
    assert acc.elements["redis"]["name"] == "Redis 7" and acc.elements["redis"]["doc"] == "limiter state"
    # batch cap: nothing added
    r = t["add_elements"]([{"id": f"e{i}", "type": "Node", "name": f"n{i}"} for i in range(13)])
    assert "batch too large" in r["error"] and r["total_elements"] == 6

    # ---- relations: reproduce the live defect -> every illegal one REJECTED with the allowed list
    r = t["add_relations"]([
        {"type": "Aggregation", "src": "litellm-proxy", "tgt": "gateway-service"},   # 0 illegal
        {"type": "Aggregation", "src": "litellm-proxy", "tgt": "route-request"},     # 1 illegal
        {"type": "Assignment", "src": "redis", "tgt": "litellm-proxy"},              # 2 illegal
        {"type": "Serving", "src": "litellm-proxy", "tgt": "nope"},                  # 3 missing id
        {"type": "Uses", "src": "litellm-proxy", "tgt": "redis"},                    # 4 bogus rel type
        {"type": "Access", "src": "litellm-proxy", "tgt": "spend-log", "accessType": "Write"},  # 5 ok
    ])
    assert r["added"] == [["litellm-proxy", "spend-log", "Access"]] and r["total_relations"] == 1
    assert [x["index"] for x in r["rejected"]] == [0, 1, 2, 3, 4]
    e0 = _errs(r, 0)
    assert e0.startswith("Aggregation not permitted for ApplicationComponent -> ApplicationService; allowed: [") and "Realization" in e0, e0
    e1 = _errs(r, 1)
    assert e1.startswith("Aggregation not permitted for ApplicationComponent -> ApplicationFunction; allowed: [") and "Assignment" in e1, e1
    e2 = _errs(r, 2)
    assert e2.startswith("Assignment not permitted for SystemSoftware -> ApplicationComponent; allowed: [") and "Realization" in e2, e2
    assert "tgt 'nope' is not an added element id" in _errs(r, 3)
    assert "relation type 'Uses' is not a valid" in _errs(r, 4)
    assert acc.relations[0]["accessType"] == "Write" and acc.relations[0]["id"] == ids.rid("litellm-proxy", "Access", "spend-log")

    # the legal versions the gate pointed at -> accepted; resend = duplicate
    r = t["add_relations"]([
        {"type": "Realization", "src": "litellm-proxy", "tgt": "gateway-service"},
        {"type": "Assignment", "src": "litellm-proxy", "tgt": "route-request"},
        {"type": "Realization", "src": "redis", "tgt": "litellm-proxy"},
        {"type": "Realization", "src": "route-request", "tgt": "gateway-service"},
        {"type": "Serving", "src": "gateway-service", "tgt": "{6f1c2a3e-1111-4222-8333-444455556666}"},
        {"type": "Realization", "src": "litellm-proxy", "tgt": "gateway-service"},   # dup
    ])
    assert len(r["added"]) == 5 and r["duplicates"] == [["litellm-proxy", "gateway-service", "Realization"]]
    assert r["rejected"] == [] and r["total_relations"] == 6
    # batch cap: nothing added
    r = t["add_relations"]([{"type": "Serving", "src": "a", "tgt": "b"}] * 13)
    assert "batch too large" in r["error"] and r["total_relations"] == 6

    # ---- view
    r = t["add_view"]("context", "Gateway context", ["litellm-proxy", "gateway-service", "redis", "redis", "ghost"])
    assert r["ok"] is False and "['ghost']" in r["errors"][0]
    r = t["add_view"]("context", "Gateway context", ["litellm-proxy", "gateway-service", "redis", "redis"])
    assert r == {"ok": True, "id": "context", "updated": False, "elements": 3, "relations_in_view": 2, "total_views": 1}

    # ---- finish: ok, and the spec builds through the engine with zero illegal relations
    rep = t["finish"]()
    assert rep["ok"] is True, rep
    assert rep["counts"] == {"elements": 6, "relations": 6, "views": 1}
    assert "hint" not in rep, rep  # every element is connected
    spec = acc.result()
    assert spec["name"] == "Local Agent Lab" and spec["id"] == "local-agent-lab"
    assert len(spec["elements"]) == 6 and len(spec["relations"]) == 6 and len(spec["views"]) == 1
    assert all("id" in r for r in spec["relations"]) and spec["elements"][0]["folder"] == "Lab"
    spec["elements"].clear()                       # result() is a deep copy
    assert len(acc.result()["elements"]) == 6
    spec = acc.result()
    m = Model(spec["name"], spec.get("id", "model"))   # exactly what adoit_mcp.server._build does
    for e in spec["elements"]:
        m.el(e["id"], e["type"], e["name"], e.get("doc"), folder=e.get("folder"))
    for rl in spec["relations"]:
        m.rel(rl["type"], rl["src"], rl["tgt"], rid=rl.get("id"), accessType=rl.get("accessType"))
    for v in spec.get("views", []):
        vw = m.view(v["id"], v["title"]); vw.place(*v["elements"]); vw.auto_edges()
    findings = m.validate_relations()
    assert [w for w in findings if "not permitted" in w] == [], findings
    assert m.folders["litellm-proxy"] == "Lab" and len(m.views) == 1
    return spec, rep, findings


def test_finish_with_zero_elements():
    acc = T.ArchitectAccumulator()
    t = _tools(acc)
    t["set_model"]("Empty")
    r = t["finish"]()
    assert r["ok"] is False and r["errors"] and "no elements added" in r["errors"][0]
    assert r["counts"] == {"elements": 0, "relations": 0, "views": 0}


if __name__ == "__main__":
    test_vocab_from_engine()
    print(f"vocab: {len(T.ELEMENT_TYPES)} element types from archimate_engine._TYPES; "
          f"relation types {T.RELATION_TYPES}")
    spec, rep, findings = test_architect_session()
    print("finish():", json.dumps(rep))
    print("engine validate_relations():", findings or "[] (0 findings)")
    print("spec:", json.dumps(spec, indent=1))
    test_finish_with_zero_elements()
    print("ALL TESTS PASSED")
