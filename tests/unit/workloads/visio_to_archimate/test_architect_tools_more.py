"""src/lab/workloads/visio_to_archimate/architect_tools.py — every validation branch of the Architect
accumulator tools, driven through the functions `make_tools(acc)` returns: `suggest()` name matching
(exact via canon.squash, difflib, containment), id rules (slug / ADOIT uuid / whitespace / XML
characters), each element and relation field error, accessType rules, explicit relation ids
(invalid, colliding, reused), the legality gate's allowed-list hint, checker warnings, add_view
errors, the finish() gate on doctored specs (duplicate ids, bad types, dangling, illegal, unknown
view ids, engine build failure) and its hint, and reset(). Pure: no gateway, no LLM, no Redis.
Complements tests/unit/workloads/visio_to_archimate/test_architect_tools.py.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_architect_tools_more.py   (also pytest-compatible)"""
import json


from lab.workloads.visio_to_archimate import architect_tools as T
from lab.workloads import ids

UUID = "6f1c2a3e-1111-4222-8333-444455556666"
ELS = [{"id": "portal", "type": "ApplicationComponent", "name": "Portal"},
       {"id": "portal-service", "type": "ApplicationService", "name": "Portal Service"},
       {"id": "record", "type": "DataObject", "name": "Record"},
       {"id": "clinician", "type": "BusinessActor", "name": "Clinician"}]


def _tools(acc=None):
    acc = acc or T.ArchitectAccumulator()
    return acc, {f.__name__: f for f in T.make_tools(acc)}


def _seeded():
    acc, t = _tools()
    assert t["set_model"]("Clinic")["ok"]
    r = t["add_elements"](ELS)
    assert r["rejected"] == [] and r["total_elements"] == 4
    return acc, t


def _only(rep):
    assert rep["added"] == [] and len(rep["rejected"]) == 1, rep
    return rep["rejected"][0]


def test_suggest_three_strategies_and_edges():
    assert T.suggest("", T.ELEMENT_TYPES) == [] and T.suggest("   ", T.ELEMENT_TYPES) == []
    assert T.suggest(None, T.ELEMENT_TYPES) == [] and T.suggest(5, T.ELEMENT_TYPES) == []
    # 1. exact match ignoring case/spaces/underscores/punctuation (canon.squash)
    assert T.suggest("application component", T.ELEMENT_TYPES) == ["ApplicationComponent"]
    assert T.suggest("APPLICATION_COMPONENT", T.ELEMENT_TYPES) == ["ApplicationComponent"]
    assert T.suggest(" data-object ", T.ELEMENT_TYPES) == ["DataObject"]
    assert T.suggest("serving", T.RELATION_TYPES) == ["Serving"]
    # 2. difflib similarity (n bounded)
    assert T.suggest("AppComponent", T.ELEMENT_TYPES) == ["ApplicationComponent"]
    assert T.suggest("Object", T.ELEMENT_TYPES) == ["DataObject", "BusinessObject"]
    assert len(T.suggest("Interface", T.ELEMENT_TYPES)) == 3 and len(T.suggest("Interface", T.ELEMENT_TYPES, n=1)) == 1
    # 3. containment either way, when difflib finds nothing
    assert T.suggest("Event", T.ELEMENT_TYPES) == ["BusinessEvent", "ApplicationEvent", "TechnologyEvent"]
    assert T.suggest("event", T.ELEMENT_TYPES, n=2) == ["BusinessEvent", "ApplicationEvent"]
    assert T.suggest("x" * 40 + "Node" + "y" * 40, T.ELEMENT_TYPES) == ["Node"]
    assert T.suggest("zzzz", T.ELEMENT_TYPES) == []
    assert T.suggest("Junction", T.RELATION_TYPES) == []                    # Junction is not a relation the model may pick
    # _type_error: with and without a hint
    assert T._type_error("type", "app component", T.ELEMENT_TYPES) == (
        "type 'app component' is not a valid ArchiMate 3.1 type — did you mean ApplicationComponent? (exact CamelCase name required)")
    assert T._type_error("type", "Object", T.ELEMENT_TYPES).endswith("did you mean DataObject or BusinessObject? (exact CamelCase name required)")
    assert T._type_error("type", "zzzz", T.ELEMENT_TYPES) == f"type 'zzzz' is not a valid ArchiMate 3.1 type; valid: [{T.fmt(T.ELEMENT_TYPES)}]"
    assert T._type_error("type", None, T.ELEMENT_TYPES).startswith("type 'None' is not a valid ArchiMate 3.1 type; valid: [")
    assert T._type_error("relation type", 7, T.RELATION_TYPES).startswith("relation type '7' is not")


def test_valid_id_rules():
    assert T._valid_id("portal") is None and T._valid_id("  a-b_c.d  ") is None
    assert T._valid_id(UUID) is None and T._valid_id("{" + UUID + "}") is None and T._valid_id(UUID.upper()) is None
    for bad in (None, "", "  ", 3, ["x"]):
        assert T._valid_id(bad) == "id is required (non-empty string: a stable slug of the name, or the ADOIT id verbatim)", bad
    assert T._valid_id("my model") == "id 'my model' must not contain whitespace — use a slug (lowercase, dashes) or the ADOIT id verbatim"
    assert T._valid_id("a\tb").startswith("id 'a\tb' must not contain whitespace")
    for ch in "<>\"'&":
        assert T._valid_id(f"id{ch}x") == f"id 'id{ch}x' contains characters not allowed in an XML id (<>\"'&)", ch
    assert T._valid_id("{" + UUID + "}&") is not None                      # a decorated uuid is not a uuid


def test_set_model_id_derivation_and_errors():
    acc, t = _tools()
    for bad in ("", "  ", None, 3):
        assert t["set_model"](bad) == {"ok": False, "errors": ["name is required (non-empty string: the systemName)"]}, bad
    assert t["set_model"]("  Clinic Portal  ") == {"ok": True, "name": "Clinic Portal", "id": "clinic-portal"}
    assert t["set_model"]("###") == {"ok": True, "name": "###", "id": "model"}          # nothing survives the slug
    assert t["set_model"]("Clinic", " custom-id ") == {"ok": True, "name": "Clinic", "id": "custom-id"}
    assert t["set_model"]("Clinic", UUID)["id"] == UUID
    r = t["set_model"]("Clinic", "has space")
    assert r["ok"] is False and r["errors"][0].startswith("id 'has space' must not contain whitespace")
    assert t["set_model"]("Clinic", "a&b")["ok"] is False
    assert (acc.name, acc.id) == ("Clinic", UUID)                          # a failed call leaves the model untouched
    assert t["set_model"]("Clinic", "   ")["id"] == "clinic"               # blank id -> derived


def test_add_elements_each_field_error():
    acc, t = _tools()
    ok = {"id": "portal", "type": "ApplicationComponent", "name": "Portal"}
    rej = _only(t["add_elements"]([{**ok, "id": "has space"}]))
    assert rej["id"] == "has space" and rej["errors"][0].startswith("id 'has space' must not contain whitespace")
    rej = _only(t["add_elements"]([{**ok, "id": "a<b"}]))
    assert rej["errors"] == ["id 'a<b' contains characters not allowed in an XML id (<>\"'&)"]
    rej = _only(t["add_elements"]([{**ok, "type": "application component"}]))
    assert rej["errors"] == ["type 'application component' is not a valid ArchiMate 3.1 type — did you mean ApplicationComponent? (exact CamelCase name required)"]
    rej = _only(t["add_elements"]([{**ok, "type": "zzzz"}]))
    assert rej["errors"][0].startswith("type 'zzzz' is not a valid ArchiMate 3.1 type; valid: [")
    rej = _only(t["add_elements"]([{"id": "x", "name": "X"}]))
    assert rej["errors"][0].startswith("type 'None' is not a valid ArchiMate 3.1 type; valid: [")
    for bad in ("", "  ", None, 4):
        assert _only(t["add_elements"]([{**ok, "name": bad}]))["errors"] == ["name is required (non-empty string)"], bad
    rej = _only(t["add_elements"]([{**ok, "doc": 5, "folder": ["Lab"]}]))
    assert rej["errors"] == ["doc must be a string", "folder must be a string"]
    # non-object items: one message, no id
    r = t["add_elements"](["portal", None])
    assert r["rejected"] == [{"index": 0, "id": None, "errors": [f"item must be an object with fields [{T.fmt(T.ELEMENT_FIELDS)}]"]},
                             {"index": 1, "id": None, "errors": [f"item must be an object with fields [{T.fmt(T.ELEMENT_FIELDS)}]"]}]
    # every error of one item, in check order
    rej = _only(t["add_elements"]([{"id": "", "type": "Nope", "name": "", "doc": 1, "folder": 2, "extra": True}]))
    assert rej["errors"][0] == f"unknown field(s) ['extra']; allowed: [{T.fmt(T.ELEMENT_FIELDS)}]"
    assert rej["errors"][1].startswith("id is required") and rej["errors"][2].startswith("type 'Nope'")
    assert rej["errors"][3:] == ["name is required (non-empty string)", "doc must be a string", "folder must be a string"]
    assert acc.elements == {}
    # accepted shapes: doc/folder None or blank are dropped, ids/names stripped, uuid ids kept verbatim
    r = t["add_elements"]([{"id": " portal ", "type": "ApplicationComponent", "name": " Portal ", "doc": None, "folder": "  "},
                           {"id": "{" + UUID + "}", "type": "Node", "name": "Host", "doc": " d ", "folder": " Lab "}])
    assert r["added"] == ["portal", "{" + UUID + "}"] and r["rejected"] == []
    assert acc.elements["portal"] == {"id": "portal", "type": "ApplicationComponent", "name": "Portal"}
    assert acc.elements["{" + UUID + "}"] == {"id": "{" + UUID + "}", "type": "Node", "name": "Host", "doc": "d", "folder": "Lab"}
    # update keeps fields the update omits; batch shapes
    assert t["add_elements"]({"id": "portal", "type": "ApplicationComponent", "name": "Portal v2"})["updated"] == ["portal"]
    assert acc.elements["portal"]["name"] == "Portal v2"
    assert t["add_elements"](json.dumps([{"id": "j", "type": "Device", "name": "J"}]))["added"] == ["j"]
    r = t["add_elements"]("{bad")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)", "added": [], "updated": [],
                 "rejected": [], "total_elements": 3}


def test_add_relations_each_field_error():
    acc, t = _seeded()
    ok = {"type": "Serving", "src": "portal-service", "tgt": "clinician"}

    def rej_of(item):
        return _only(t["add_relations"]([item]))

    r = t["add_relations"]([["portal", "clinician"], 7])
    assert r["rejected"] == [{"index": 0, "errors": [f"item must be an object with fields [{T.fmt(T.RELATION_FIELDS)}]"]},
                             {"index": 1, "errors": [f"item must be an object with fields [{T.fmt(T.RELATION_FIELDS)}]"]}]
    rej = rej_of({**ok, "label": "x"})
    assert rej["errors"] == [f"unknown field(s) ['label']; allowed: [{T.fmt(T.RELATION_FIELDS)}]"]
    rej = rej_of({**ok, "type": "serving"})
    assert rej["errors"] == ["relation type 'serving' is not a valid ArchiMate 3.1 relation type — did you mean Serving? (exact CamelCase name required)"]
    rej = rej_of({"src": "portal", "tgt": "clinician"})
    assert rej["type"] is None and rej["errors"][0].startswith("relation type 'None' is not a valid ArchiMate 3.1 relation type; valid: [")
    for end in ("src", "tgt"):
        for missing in ("", "  ", None, 3):
            rej = rej_of({**ok, end: missing})
            assert rej["errors"] == [f"{end} is required (an element id already added with add_elements)"], (end, missing)
    # a near-miss id gets a did-you-mean (canon.squash exact match), an unknown one does not
    rej = rej_of({**ok, "src": "portal_service"})
    assert rej["errors"] == ["src 'portal_service' is not an added element id — add it with add_elements first "
                             "(added: 4 elements; did you mean portal-service), then resend this relation"]
    rej = rej_of({**ok, "tgt": "zzzz"})
    assert rej["errors"] == ["tgt 'zzzz' is not an added element id — add it with add_elements first (added: 4 elements), then resend this relation"]
    assert rej["src"] == "portal-service" and rej["tgt"] == "zzzz" and rej["type"] == "Serving"
    # accessType rules
    rej = rej_of({"type": "Access", "src": "portal", "tgt": "record", "accessType": "read"})
    assert rej["errors"] == [f"accessType 'read' is not one of [{T.fmt(T.ACCESS_TYPES)}]"]
    rej = rej_of({**ok, "accessType": "Read"})
    assert rej["errors"] == ["accessType is only meaningful on an Access relation"]
    # explicit relation ids: invalid, colliding with an element id
    rej = rej_of({**ok, "id": "bad id"})
    assert rej["errors"][0].startswith("id 'bad id' must not contain whitespace")
    rej = rej_of({**ok, "id": ""})
    assert rej["errors"][0].startswith("id is required")
    rej = rej_of({**ok, "id": " portal "})
    assert rej["errors"] == ["relation id ' portal ' collides with an element id"]
    # every error of one item together, in check order
    rej = rej_of({"type": "Uses", "src": "", "tgt": "nope", "accessType": "Read", "id": "x y", "z": 1})
    assert rej["errors"][0].startswith("unknown field(s) ['z']") and rej["errors"][1].startswith("relation type 'Uses'")
    assert rej["errors"][2].startswith("src is required") and rej["errors"][3].startswith("tgt 'nope' is not an added element id")
    assert rej["errors"][4] == "accessType is only meaningful on an Access relation"    # valid accessType, wrong relation
    assert rej["errors"][5].startswith("id 'x y' must not contain whitespace")
    assert acc.relations == []


def test_add_relations_legality_ids_and_duplicates():
    acc, t = _seeded()
    # illegal: allowed list + advice; the advice is omitted when NOTHING is allowed
    rej = _only(t["add_relations"]([{"type": "Composition", "src": "clinician", "tgt": "record"}]))
    e = rej["errors"][0]
    assert e.startswith("Composition not permitted for BusinessActor -> DataObject; allowed: [")
    assert e.endswith(" — pick one of the allowed types that keeps the intent (weakest relation that is still true) and resend")
    saved = T.check_relation
    try:
        T.check_relation = lambda st, rt, tt: (False, [], None)
        rej = _only(t["add_relations"]([{"type": "Serving", "src": "portal", "tgt": "clinician"}]))
        assert rej["errors"] == ["Serving not permitted for ApplicationComponent -> BusinessActor; allowed: []"]
        # checker unavailable: accepted unchecked, the note surfaces ONCE as a warning
        T.check_relation = lambda st, rt, tt: (True, [], "legality check unavailable (X: y); accepted unchecked")
        r = t["add_relations"]([{"type": "Serving", "src": "portal", "tgt": "clinician"},
                                {"type": "Flow", "src": "portal", "tgt": "clinician"}])
        assert len(r["added"]) == 2 and r["warnings"] == ["legality check unavailable (X: y); accepted unchecked"]
    finally:
        T.check_relation = saved
    assert "warnings" not in t["add_relations"]([{"type": "Realization", "src": "portal", "tgt": "portal-service"}])
    # explicit id honoured (stripped); an explicit id equal to another relation's id is rejected
    r = t["add_relations"]([{"type": "Access", "src": "portal", "tgt": "record", "accessType": "ReadWrite", "id": " rw-1 "}])
    assert r["added"] == [["portal", "record", "Access"]] and acc.relations[-1] == {"id": "rw-1", "type": "Access", "src": "portal",
                                                                                    "tgt": "record", "accessType": "ReadWrite"}
    rej = _only(t["add_relations"]([{"type": "Serving", "src": "portal-service", "tgt": "clinician", "id": "rw-1"}]))
    assert rej["errors"] == ["relation id 'rw-1' is already used by another relation"]
    auto = ids.rid("portal-service", "clinician", "Serving")
    rej = _only(t["add_relations"]([{"type": "Serving", "src": "portal-service", "tgt": "portal", "id": acc.relations[0]["id"]}]))
    assert rej["errors"][0].startswith("relation id 'r-") and "already used" in rej["errors"][0]
    # the same triple again (with or without an id / accessType) is a duplicate, never re-added
    r = t["add_relations"]([{"type": "Access", "src": " portal ", "tgt": " record ", "id": "other"},
                            {"type": "Access", "src": "portal", "tgt": "record", "accessType": "Read"}])
    assert r["duplicates"] == [["portal", "record", "Access"], ["portal", "record", "Access"]] and r["added"] == []
    assert acc.relations[-1]["accessType"] == "ReadWrite" and acc._rel_keys[("portal", "record", "Access")] == "rw-1"
    r = t["add_relations"]([{"type": "Serving", "src": "portal-service", "tgt": "clinician"}])
    assert r["added"] == [["portal-service", "clinician", "Serving"]] and acc.relations[-1]["id"] == ids.rid("portal-service", "Serving", "clinician")
    assert acc.relations[-1]["id"] != auto
    assert "accessType" not in acc.relations[-1]
    # batch shapes
    r = t["add_relations"]("{bad")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)", "added": [], "duplicates": [],
                 "rejected": [], "total_relations": len(acc.relations)}
    assert t["add_relations"](json.dumps({"type": "Serving", "src": "portal-service", "tgt": "clinician"}))["duplicates"] == [
        ["portal-service", "clinician", "Serving"]]


def test_check_relation_contract():
    ok, allowed, note = T.check_relation("ApplicationComponent", "Realization", "ApplicationService")
    assert ok is True and isinstance(allowed, list) and note is None
    ok, allowed, note = T.check_relation("BusinessActor", "Composition", "DataObject")
    assert ok is False and "Association" in allowed and note is None


def test_add_view_errors_and_updates():
    acc, t = _seeded()
    t["add_relations"]([{"type": "Realization", "src": "portal", "tgt": "portal-service"},
                        {"type": "Serving", "src": "portal-service", "tgt": "clinician"}])
    r = t["add_view"]("", "T", ["portal"])
    assert r == {"ok": False, "id": "", "errors": ["id is required (non-empty string: a stable slug of the name, or the ADOIT id verbatim)"], "total_views": 0}
    r = t["add_view"]("ctx x", "T", ["portal"])
    assert r["errors"][0].startswith("id 'ctx x' must not contain whitespace")
    for bad in ("", "  ", None, 3):
        assert t["add_view"]("ctx", bad, ["portal"])["errors"] == ["title is required (non-empty string)"], bad
    r = t["add_view"]("ctx", "T", "{bad")                                        # the coercion error alone: no 'at least one' echo
    assert r["errors"] == ["element_ids must be a JSON array of objects (got an unparsable string)"]
    r = t["add_view"]("ctx", "T", 7)
    assert r["errors"] == ["element_ids must be a list (got int)"]
    for empty in ([], "[]", [None, "", "  ", 2.5, {"id": "portal"}]):
        assert t["add_view"]("ctx", "T", empty)["errors"] == ["element_ids must list at least one added element id"], empty
    r = t["add_view"]("ctx", "T", ["portal", "ghost", "phantom", "ghost"])
    assert r["errors"] == ["element_ids not added: ['ghost', 'phantom'] — add them with add_elements first, then resend the view"]
    # all errors together: id, title, ids
    r = t["add_view"]("a&b", "", ["ghost"])
    assert len(r["errors"]) == 3 and r["total_views"] == 0 and acc.views == {}
    # accepted: JSON string / ints / padded ids, dedupe, relations counted among the placed ids only
    r = t["add_view"](" ctx ", " Context ", json.dumps([" portal ", "portal-service", "portal"]))
    assert r == {"ok": True, "id": "ctx", "updated": False, "elements": 2, "relations_in_view": 1, "total_views": 1}
    assert acc.views["ctx"] == {"id": "ctx", "title": "Context", "elements": ["portal", "portal-service"]}
    r = t["add_view"]("ctx", "Context 2", ["portal", "portal-service", "clinician"])
    assert r == {"ok": True, "id": "ctx", "updated": True, "elements": 3, "relations_in_view": 2, "total_views": 1}
    r = t["add_view"]("solo", "Solo", "record")                                  # a bare string id is one JSON-unparsable item
    assert r["ok"] is False and r["errors"] == ["element_ids must be a JSON array of objects (got an unparsable string)"]
    r = t["add_view"]("solo", "Solo", {"x": 1})                                  # a dict is a one-item batch of a non-id
    assert r["errors"] == ["element_ids must list at least one added element id"]
    assert t["add_view"]("solo", "Solo", ["record"]) == {"ok": True, "id": "solo", "updated": False, "elements": 1,
                                                          "relations_in_view": 0, "total_views": 2}
    assert [v["id"] for v in acc.result()["views"]] == ["ctx", "solo"]


def test_finish_gate_hint_and_doctored_specs():
    acc, t = _seeded()
    r = t["finish"]()
    assert r["ok"] is True and r["counts"] == {"elements": 4, "relations": 0, "views": 0}
    assert r["hint"] == ("4 element(s) have no relation: ['portal', 'portal-service', 'record', 'clinician'] — connect them "
                         "with add_relations (the BA's relationships map one-to-one) or leave them if the BA left them orphaned")
    t["add_elements"]([{"id": f"u{i}", "type": "Node", "name": f"U{i}"} for i in range(6)])
    assert t["finish"]()["hint"].startswith("10 element(s) have no relation: ['portal', 'portal-service', 'record', 'clinician', 'u0', 'u1', 'u2', 'u3'] …")
    acc.reset(); acc, t = _seeded()
    t["add_relations"]([{"type": "Realization", "src": "portal", "tgt": "portal-service"},
                        {"type": "Serving", "src": "portal-service", "tgt": "clinician"},
                        {"type": "Access", "src": "portal", "tgt": "record", "accessType": "Read"}])
    assert "hint" not in t["finish"]() and acc.last_finish["ok"] is True
    # the gate re-checks the assembled spec: doctored copies expose every honest-but-unreachable branch
    base = acc.result()

    def gate(**over):
        return acc._gate({**base, **over})

    assert gate() == ([], None)
    assert gate(name="")[0] == ["model name not set — call set_model(name) with the systemName"]
    assert gate(elements=base["elements"] + [dict(base["elements"][0])])[0] == ["duplicate element ids"]
    bad = [dict(e) for e in base["elements"]]; bad[0]["type"] = "Widget"
    assert gate(elements=bad)[0] == ["invalid element type(s): ['portal:Widget']"]
    dangling = base["relations"] + [{"id": "r-x", "type": "Serving", "src": "portal", "tgt": "ghost"}]
    errs, _ = gate(relations=dangling)
    assert errs == ["relation(s) with undeclared endpoints: ['r-x']"]                # skipped by the legality loop
    dup = base["relations"] + [dict(base["relations"][0])]
    assert gate(relations=dup)[0] == ["duplicate relation ids"]
    illegal = [dict(r) for r in base["relations"]]; illegal[0]["type"] = "Composition"
    errs, _ = gate(relations=illegal)
    assert len(errs) == 1 and errs[0].startswith(f"{illegal[0]['id']} (portal->portal-service): Composition not permitted for "
                                                 "ApplicationComponent -> ApplicationService; allowed: [")
    errs, _ = gate(views=[{"id": "v", "title": "V", "elements": ["portal", "ghost"]}])
    assert errs == ["view 'v' references unknown element ids: ['ghost']"]
    # engine probe failure is reported, never raised
    saved = T.Model
    try:
        class Boom:
            def __init__(self, *a, **k):
                raise ValueError("no engine")
        T.Model = Boom
        r = t["finish"]()
        assert r["ok"] is False and r["errors"] == ["engine build failed: ValueError: no engine"] and acc.last_finish is r
    finally:
        T.Model = saved
    assert t["finish"]()["ok"] is True
    # the probe build itself: a legal spec with a view yields no findings
    t["add_view"]("ctx", "Context", ["portal", "portal-service", "clinician"])
    assert acc._probe_build(acc.result()) == [] and t["finish"]() == {"ok": True, "counts": {"elements": 4, "relations": 3, "views": 1}}
    # the empty-elements gate with no name set (both messages, in order)
    fresh, ft = _tools()
    assert ft["finish"]()["errors"] == ["model name not set — call set_model(name) with the systemName",
                                        "no elements added — call add_elements with one element per BA element (actors, components, data, behaviors)"]


def test_reset_and_result_shapes():
    acc, t = _seeded()
    t["add_relations"]([{"type": "Realization", "src": "portal", "tgt": "portal-service"}])
    t["add_view"]("ctx", "Context", ["portal"]); t["finish"]()
    spec = acc.result()
    assert list(spec) == ["name", "id", "elements", "relations", "views"] and spec["id"] == "clinic"
    spec["views"][0]["elements"].append("x"); spec["relations"].clear()
    assert acc.result()["views"][0]["elements"] == ["portal"] and len(acc.result()["relations"]) == 1   # deep copy
    acc.reset()
    assert (acc.name, acc.id, acc.elements, acc.relations, acc._rel_keys, acc.views, acc.last_finish) == ("", "", {}, [], {}, {}, None)
    assert acc.result() == {"name": "", "id": "", "elements": [], "relations": []}            # no views key when empty
    assert acc.counts() == {"elements": 0, "relations": 0, "views": 0}
    # the closures are still bound; the previously-added relation is new again after reset
    t["set_model"]("Again"); t["add_elements"](ELS)
    assert t["add_relations"]([{"type": "Realization", "src": "portal", "tgt": "portal-service"}])["added"] == [["portal", "portal-service", "Realization"]]
    assert set(T.__all__) <= set(dir(T)) and T.ACCESS_TYPES == ("Read", "Write", "ReadWrite", "Access")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
