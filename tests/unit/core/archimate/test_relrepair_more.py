"""relrepair beyond the live-run reproduction: the decision ladder (intent miss -> category
preference -> Association fallback -> unrepairable), undeclared endpoints, the coarse legality
probe when the semantic layer is unavailable, the category fallback when the vocab table is not
importable, summarize() and the CLI. Offline.
Run: .venv/bin/python tests/unit/core/archimate/test_relrepair_more.py   (also pytest-compatible)"""
import copy
import io
import json
import os
import runpy
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SCRIPTS = os.path.join(ROOT, "src", "lab", "core", "archimate")

from lab.core.archimate import engine as E  # noqa: E402
from lab.core.archimate import relrepair as RR  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "relrepair.py")


def test_decision_ladder_exact_matrix():
    assert RR._sem() is not None
    assert RR.decide("ApplicationComponent", "Realization", "ApplicationService") is None          # legal
    # intent table misses (Composition active -> passive is neither behaviour nor service) -> category/fallback
    assert RR._intent("ApplicationComponent", "Composition", "DataObject") is None
    d = RR.decide("ApplicationComponent", "Composition", "DataObject")
    assert d["rule"] == "fallback_association" and d["replaced"] == "Association" and d["allowed"] == ["Access", "Association"]
    # category preference: Access between two components -> the nearest permitted dependency (Serving)
    d = RR.decide("ApplicationComponent", "Access", "ApplicationComponent")
    assert (d["replaced"], d["rule"]) == ("Serving", "category_preference") and "nearest permitted dependency" in d["reason"]
    # dynamic category: Triggering component -> data has no dynamic alternative -> Association
    d = RR.decide("ApplicationComponent", "Triggering", "DataObject")
    assert d["rule"] == "fallback_association"
    # structural category preference: Realization process -> actor is illegal; nothing structural fits -> Association
    d = RR.decide("BusinessProcess", "Realization", "BusinessActor")
    assert d["rule"] == "fallback_association"
    # intent hits are matrix-checked: the intent replacement must itself be allowed
    assert RR._intent("Node", "Assignment", "ApplicationComponent")[0] == "Realization"
    assert RR.decide("Node", "Assignment", "ApplicationComponent")["rule"] == "intent"
    assert RR._intent("ApplicationComponent", "Serving", "DataObject") is None                   # not an intent shape


def test_unrepairable_when_nothing_is_allowed():
    orig = RR.check
    RR.check = lambda s, r, t: (False, [])
    try:
        d = RR.decide("Goal", "Serving", "Node")
    finally:
        RR.check = orig
    assert d == {"replaced": "Serving", "rule": "unrepairable", "allowed": [],
                 "reason": "unrepairable: Serving not permitted for Goal -> Node and nothing is allowed"}


def test_undeclared_endpoint_is_reported_not_rewritten():
    spec = {"elements": [{"id": "a", "type": "ApplicationComponent", "name": "A"}],
            "relations": [{"type": "Serving", "src": "a", "tgt": "ghost"},
                          {"id": "self", "type": "Access", "src": "a", "tgt": "a"}]}
    before = copy.deepcopy(spec)
    fixed, rep = RR.repair_spec(spec)
    assert spec == before
    assert [e["rid"] for e in rep] == ["r1", "self"]                    # unnamed relation gets r<n>
    assert rep[0]["rule"] == "unrepairable" and rep[0]["tgt_type"] is None and rep[0]["allowed"] == []
    assert rep[0]["replaced"] == rep[0]["original"] == "Serving"
    assert [r["type"] for r in fixed["relations"]] == ["Serving", "Serving"]   # Access comp->comp: category preference
    lines = RR.summarize(rep)
    assert len(lines) == 2 and lines[0].startswith("r1 (a->ghost, ApplicationComponent -> None): Serving -> Serving [unrepairable]")
    # the Model API on the same shapes: unrepairable entries leave the relation untouched
    m = E.Model("u"); m.el("a", "ApplicationComponent", "A"); m.el("g", "Goal", "G")
    m.rel("Serving", "g", "a", rid="bad")
    orig = RR.check
    RR.check = lambda s, r, t: (False, [])
    try:
        same, rep = RR.repair(m)
    finally:
        RR.check = orig
    assert same is m and rep[0]["rule"] == "unrepairable" and m.relations["bad"][0] == "Serving"


def test_coarse_probe_when_semantic_layer_is_unavailable():
    RR._sem.cache_clear()
    orig = E._semantic
    E._semantic = RR._semantic = lambda: None       # relrepair binds the name at import; the probe Model uses the engine's
    try:
        assert RR._sem() is None
        ok, allowed = RR.check("ApplicationComponent", "Realization", "ApplicationService")
        assert ok and "Junction" not in allowed and "Association" in allowed
        ok, allowed = RR.check("DataObject", "Serving", "ApplicationComponent")
        assert not ok and "Serving" not in allowed and "Access" not in allowed
        assert RR._coarse_ok("Node", "Assignment", "Artifact") and not RR._coarse_ok("Node", "Assignment", "DataObject")
        m = E.Model("c"); m.el("d", "DataObject", "D"); m.el("c", "ApplicationComponent", "C")
        m.rel("Serving", "d", "c", rid="s")
        _, rep = RR.repair(m)
        assert rep[0]["replaced"] != "Serving" and m.validate_relations() == []
    finally:
        E._semantic = RR._semantic = orig
        RR._sem.cache_clear()
    assert RR._sem() is not None


def test_category_falls_back_when_vocab_table_is_not_importable():
    assert RR._category("Composition") == "structural" and RR._category("Serving") == "dependency"
    assert RR._category("Triggering") == "dynamic" and RR._category("Specialization") == "other"
    saved = sys.modules.get("lab.core.semantic.archimate.vocab")
    sys.modules["lab.core.semantic.archimate.vocab"] = None
    try:
        assert RR._category("Flow") == "dynamic" and RR._category("Association") == "other"
        assert RR._category("Realization") == "structural" and RR._category("Nope") == "other"
    finally:
        if saved is not None:
            sys.modules["lab.core.semantic.archimate.vocab"] = saved
        else:
            del sys.modules["lab.core.semantic.archimate.vocab"]


def test_cli_round_trip():
    spec = {"elements": [{"id": "c", "type": "ApplicationComponent", "name": "C"},
                         {"id": "f", "type": "ApplicationFunction", "name": "F"}],
            "relations": [{"id": "x", "type": "Aggregation", "src": "c", "tgt": "f"}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "spec.json")
        json.dump(spec, open(p, "w"))
        argv = sys.argv
        out, err = io.StringIO(), io.StringIO()
        try:
            sys.argv = [SCRIPT, p]
            with redirect_stdout(out), redirect_stderr(err):
                runpy.run_path(SCRIPT, run_name="__main__")
        finally:
            sys.argv = argv
    fixed = json.loads(out.getvalue())
    assert fixed["relations"][0]["type"] == "Assignment"
    assert err.getvalue().startswith("x (c->f, ApplicationComponent -> ApplicationFunction): Aggregation -> Assignment [intent]")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
