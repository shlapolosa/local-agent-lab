"""src/lab/workloads/visio_to_archimate/ba_tools.py — every validation branch of the BA accumulator tools,
driven through the functions `make_tools(acc)` returns (what the model calls): each required field
missing, wrong types, provenance in every accepted/rejected shape, sourceShapeIds coercion, updates
that reclassify/merge, relationship field errors, the schema backstops, the finish() gate's errors
and hint, and reset(). Pure: no gateway, no LLM, no Redis. Complements
tests/unit/workloads/visio_to_archimate/test_ba_tools.py.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_ba_tools_more.py   (also pytest-compatible)"""
import json


from jsonschema import Draft7Validator

from lab.workloads.visio_to_archimate import ba_tools as B

OK = {"group": "components", "name": "Portal", "role": "Web front end", "layer": "Application",
      "aspect": "active", "candidateType": "ApplicationComponent",
      "provenance": {"source": "diagram", "representation": "structure"}}


def _tools(acc=None):
    acc = acc or B.BAAccumulator()
    return acc, {f.__name__: f for f in B.make_tools(acc)}


def _el(**over):
    return {**OK, **over}


def _only(rep):
    """The errors of a single-item batch that must have been rejected."""
    assert rep["added"] == [] and rep["updated"] == [] and len(rep["rejected"]) == 1, rep
    return rep["rejected"][0]["errors"]


def test_set_system_each_field():
    acc, t = _tools()
    assert t["set_system"](None, "s") == {"ok": False, "errors": ["systemName is required (non-empty string)"]}
    assert t["set_system"]("n", "  ") == {"ok": False, "errors": ["summary is required (non-empty string)"]}
    assert t["set_system"]("", "") == {"ok": False, "errors": ["systemName is required (non-empty string)",
                                                               "summary is required (non-empty string)"]}
    assert t["set_system"](5, ["x"])["ok"] is False
    assert acc.system_name == "" and acc.summary == ""
    assert t["set_system"]("  Portal  ", " It serves. ") == {"ok": True, "systemName": "Portal", "summary": "It serves."}
    assert t["set_system"]("Portal v2", "Refined.")["systemName"] == "Portal v2"    # may be called again


def test_add_elements_each_required_field_missing_or_wrong():
    acc, t = _tools()
    for f in ("name", "role", "candidateType"):
        item = _el(); del item[f]
        assert _only(t["add_elements"]([item])) == [f"{f} is required (non-empty string)"], f
        for bad in ("", "   ", 7, None, ["x"]):
            errs = _only(t["add_elements"]([_el(**{f: bad})]))
            assert errs == [f"{f} is required (non-empty string)"], (f, bad, errs)
    item = _el(); del item["layer"]
    assert _only(t["add_elements"]([item])) == [f"layer 'None' is not one of [{B.fmt(B.LAYERS)}]"]
    item = _el(); del item["aspect"]
    assert _only(t["add_elements"]([item])) == [f"aspect 'None' is not one of [{B.fmt(B.ASPECTS)}]"]
    assert _only(t["add_elements"]([_el(aspect="Active")])) == [f"aspect 'Active' is not one of [{B.fmt(B.ASPECTS)}]"]
    assert _only(t["add_elements"]([_el(layer="application")])) == [f"layer 'application' is not one of [{B.fmt(B.LAYERS)}]"]
    item = _el(); del item["group"]
    assert _only(t["add_elements"]([item])) == [f"group 'None' is not one of [{B.fmt(B.GROUPS)}]"]
    assert _only(t["add_elements"]([_el(group="Components")]))[0].startswith("group 'Components' is not one of")
    # a non-object item: one message naming the accepted fields, no name in the rejection
    r = t["add_elements"](["Portal", 3, None])
    assert [x["name"] for x in r["rejected"]] == [None, None, None]
    assert r["rejected"][0]["errors"] == [f"item must be an object with fields [{B.fmt(B.ITEM_FIELDS)}]"]
    # every error of one item is reported together, in check order
    errs = _only(t["add_elements"]([{"group": "x", "name": "", "role": None, "layer": "L", "aspect": "A",
                                     "candidateType": "", "extra": 1, "provenance": 7}]))
    assert errs[0] == "unknown field(s) ['extra']; allowed: [" + B.fmt(B.ITEM_FIELDS) + "]"
    assert errs[1].startswith("group 'x'") and errs[2:5] == ["name is required (non-empty string)",
                                                             "role is required (non-empty string)",
                                                             "candidateType is required (non-empty string)"]
    assert errs[5].startswith("layer 'L'") and errs[6].startswith("aspect 'A'")
    assert errs[7] == "provenance must be a string shorthand (representation) or an object {source, representation}"
    assert len(errs) == 8
    assert acc.elements == {} and acc.counts()["elements"] == 0


def test_add_elements_provenance_shapes():
    """Provenance is REQUIRED on every element and normalises to ONE shape: the bare-string
    shorthand expands (its source is the only kind that representation can come from), the object
    form must carry both fields, and anything else is a per-item rejection with a precise reason."""
    acc, t = _tools()
    r = t["add_elements"]([_el(name="A", provenance=" vision "),
                           _el(name="B", provenance={"source": "requirements", "representation": "document"})])
    assert r["added"] == ["A", "B"] and r["rejected"] == []
    assert acc.elements["A"]["element"]["provenance"] == {"source": "diagram", "representation": "vision"}
    assert acc.elements["B"]["element"]["provenance"] == {"source": "requirements", "representation": "document"}
    # every representation expands to exactly one source, and the table is the schema's own enum
    assert set(B.SOURCE_OF_REPRESENTATION) == set(B.PROVENANCE_REPRESENTATIONS)
    assert set(B.SOURCE_OF_REPRESENTATION.values()) <= set(B.PROVENANCE_SOURCES)
    # rejected: absent, half an object, bad shorthand, bad source/representation, unknown field, wrong type
    required = ("provenance is required: a representation shorthand "
                f"[{B.fmt(B.PROVENANCE_REPRESENTATIONS)}] or an object {{source, representation}}")
    item = _el(); del item["provenance"]
    assert _only(t["add_elements"]([item])) == [required]
    assert _only(t["add_elements"]([_el(provenance=None)])) == [required]
    assert _only(t["add_elements"]([_el(provenance={})])) == ["provenance.source is required",
                                                              "provenance.representation is required"]
    assert _only(t["add_elements"]([_el(provenance={"source": "diagram"})])) == ["provenance.representation is required"]
    assert _only(t["add_elements"]([_el(provenance={"representation": "structure"})])) == ["provenance.source is required"]
    assert _only(t["add_elements"]([_el(provenance="parsed")])) == [
        f"provenance 'parsed' is not one of [{B.fmt(B.PROVENANCE_REPRESENTATIONS)}] (or an object {{source, representation}})"]
    assert _only(t["add_elements"]([_el(provenance={"source": "visio", "representation": "structure"})])) == [
        f"provenance.source 'visio' is not one of [{B.fmt(B.PROVENANCE_SOURCES)}]"]
    assert _only(t["add_elements"]([_el(provenance={"source": "diagram", "representation": "image"})])) == [
        f"provenance.representation 'image' is not one of [{B.fmt(B.PROVENANCE_REPRESENTATIONS)}]"]
    assert _only(t["add_elements"]([_el(provenance={"page": 2, "source": "diagram", "representation": "structure"})])) == [
        f"provenance has unknown field(s) ['page']; allowed: [{B.fmt(('source', 'representation'))}]"]
    for bad in (7, ["vision"], True):
        assert _only(t["add_elements"]([_el(provenance=bad)])) == [
            "provenance must be a string shorthand (representation) or an object {source, representation}"], bad
    assert acc.counts()["elements"] == 2


def test_add_elements_source_shape_ids_coercion():
    acc, t = _tools()
    r = t["add_elements"]([_el(name="S", sourceShapeIds="s1"), _el(name="I", sourceShapeIds=7),
                           _el(name="M", sourceShapeIds=[1, "b", 2.5]), _el(name="E", sourceShapeIds=[]),
                           _el(name="N", sourceShapeIds=None)])
    assert r["added"] == ["S", "I", "M", "E", "N"] and r["rejected"] == []
    assert acc.elements["S"]["element"]["sourceShapeIds"] == ["s1"]
    assert acc.elements["I"]["element"]["sourceShapeIds"] == ["7"]
    assert acc.elements["M"]["element"]["sourceShapeIds"] == ["1", "b", "2.5"]
    assert "sourceShapeIds" not in acc.elements["E"]["element"] and "sourceShapeIds" not in acc.elements["N"]["element"]
    for bad in ({"a": 1}, 2.5, ("s1",)):
        assert _only(t["add_elements"]([_el(sourceShapeIds=bad)])) == ["sourceShapeIds must be a list of strings"], bad
    assert t["add_elements"]([_el(name="T", sourceShapeIds=True)])["added"] == ["T"]   # a bool is an int: coerced, not rejected
    assert acc.elements["T"]["element"]["sourceShapeIds"] == ["True"]


def test_add_elements_update_reclassifies_and_merges_ids():
    acc, t = _tools()
    t["add_elements"]([_el(name="X", group="components", sourceShapeIds=["1", "2"], provenance="vision")])
    # update with NO ids: existing ids are kept, group is reclassified, later fields win
    r = t["add_elements"]([_el(name=" X ", group="actors", role="An actor", layer="Business", candidateType="BusinessActor")])
    assert r == {"added": [], "updated": ["X"], "rejected": [], "total_elements": 1}
    cur = acc.elements["X"]
    assert cur["group"] == "actors" and cur["element"]["role"] == "An actor" and cur["element"]["layer"] == "Business"
    # provenance travels with the item, so a re-add restates it (here the OK default) rather than
    # inheriting the earlier one; sourceShapeIds, which the item omitted entirely, are kept
    assert cur["element"]["sourceShapeIds"] == ["1", "2"]
    assert cur["element"]["provenance"] == {"source": "diagram", "representation": "structure"}
    # update with overlapping ids: unioned, order preserved, deduped
    t["add_elements"]([_el(name="X", group="actors", sourceShapeIds=["2", "3", "2"])])
    assert acc.elements["X"]["element"]["sourceShapeIds"] == ["1", "2", "3"]
    # an element added without ids and updated without ids never gains the key
    t["add_elements"]([_el(name="Y")]); t["add_elements"]([_el(name="Y", role="r2")])
    assert "sourceShapeIds" not in acc.elements["Y"]["element"] and acc.elements["Y"]["element"]["role"] == "r2"
    doc = acc.result()
    assert [e["name"] for e in doc["actors"]] == ["X"] and [e["name"] for e in doc["components"]] == ["Y"]
    assert acc.counts() == {"actors": 1, "components": 1, "data": 0, "behaviors": 0, "elements": 2,
                            "relationships": 0, "openQuestions": 0}
    # a rejected update leaves the stored element untouched and reports the (raw) name
    r = t["add_elements"]([_el(name="X", layer="nope")])
    assert r["rejected"][0]["name"] == "X" and acc.elements["X"]["element"]["layer"] == "Application"   # as last updated
    # mixed batch: index positions are those of the batch, added/updated/rejected all in one report
    r = t["add_elements"]([_el(name="Z"), "bad", _el(name="X", group="actors", layer="Business", candidateType="BusinessActor")])
    assert r["added"] == ["Z"] and r["updated"] == ["X"] and r["rejected"][0]["index"] == 1 and r["total_elements"] == 3


def test_add_elements_batch_shapes_and_cap():
    acc, t = _tools()
    assert t["add_elements"](json.dumps([_el(name="J")]))["added"] == ["J"]      # JSON string
    assert t["add_elements"](_el(name="D"))["added"] == ["D"]                    # a single dict
    r = t["add_elements"]("nonsense")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)",
                 "added": [], "updated": [], "rejected": [], "total_elements": 2}
    r = t["add_elements"](None)
    assert r["error"] == "items must be a list (got NoneType)" and r["total_elements"] == 2
    r = t["add_elements"]([_el(name=f"N{i}") for i in range(B.MAX_BATCH + 1)])
    assert r["error"].startswith(f"batch too large: {B.MAX_BATCH + 1} items > {B.MAX_BATCH}") and r["total_elements"] == 2
    assert t["add_elements"]([_el(name=f"N{i}") for i in range(B.MAX_BATCH)])["total_elements"] == 2 + B.MAX_BATCH


def test_add_relationships_each_field_error():
    acc, t = _tools()
    t["add_elements"]([_el(name="A"), _el(name="B", group="actors", layer="Business", candidateType="BusinessActor")])
    rel = {"from": "A", "to": "B", "type": "Serving", "intent": "A serves B"}

    def bad(**over):
        item = {**rel, **over}
        for k, v in list(over.items()):
            if v is ...:
                del item[k]
        r = t["add_relationships"]([item])
        assert r["added"] == [] and r["duplicates"] == [] and len(r["rejected"]) == 1, r
        return r["rejected"][0]

    for f in ("from", "to", "intent"):
        for missing in (..., "", "  ", None, 3):
            rej = bad(**{f: missing})
            assert f"{f} is required (non-empty string)" in rej["errors"], (f, missing, rej)
            assert len(rej["errors"]) == 1
    rej = bad(type=...)
    assert rej["errors"] == [f"type 'None' is not one of [{B.fmt(B.RELATIONSHIP_TYPES)}]"] and rej["type"] is None
    rej = bad(type="serving")
    assert rej["errors"][0].startswith("type 'serving' is not one of")
    rej = bad(label="x")
    assert rej["errors"] == [f"unknown field(s) ['label']; allowed: [{B.fmt(B.RELATIONSHIP_FIELDS)}]"]
    rej = bad(**{"from": "Ghost"})
    assert rej["errors"] == ["from 'Ghost' is not a declared element — add it with add_elements first "
                             "(declared: 2 elements), then resend this relationship"]
    assert rej["from"] == "Ghost" and rej["to"] == "B" and rej["type"] == "Serving" and rej["index"] == 0
    rej = bad(**{"from": "Ghost", "to": "Phantom"})
    assert [e.split(" ")[0] for e in rej["errors"]] == ["from", "to"]
    # every error at once, in check order: unknown, required, type, endpoints
    rej = bad(**{"from": "Ghost", "intent": "", "type": "Uses", "x": 1})
    assert rej["errors"][0].startswith("unknown field(s) ['x']") and rej["errors"][1] == "intent is required (non-empty string)"
    assert rej["errors"][2].startswith("type 'Uses'") and rej["errors"][3].startswith("from 'Ghost'")
    # non-object items carry no from/to in the rejection
    r = t["add_relationships"]([["A", "B"], 5])
    assert r["rejected"] == [{"index": 0, "errors": [f"item must be an object with fields [{B.fmt(B.RELATIONSHIP_FIELDS)}]"]},
                             {"index": 1, "errors": [f"item must be an object with fields [{B.fmt(B.RELATIONSHIP_FIELDS)}]"]}]
    assert acc.relationships == [] and acc.counts()["relationships"] == 0
    # endpoints and intent are stripped; the same triple with another intent is a duplicate (first intent kept)
    r = t["add_relationships"]([{"from": " A ", "to": " B ", "type": "Serving", "intent": "  A serves B  "}])
    assert r["added"] == [["A", "B", "Serving"]] and acc.relationships == [{"from": "A", "to": "B", "type": "Serving", "intent": "A serves B"}]
    r = t["add_relationships"]([{"from": "A", "to": "B", "type": "Serving", "intent": "other reading"},
                                {"from": "B", "to": "A", "type": "Serving", "intent": "reverse is distinct"},
                                {"from": "A", "to": "B", "type": "Flow", "intent": "another type is distinct"}])
    assert r["duplicates"] == [["A", "B", "Serving"]] and r["added"] == [["B", "A", "Serving"], ["A", "B", "Flow"]]
    assert acc.relationships[0]["intent"] == "A serves B" and r["total_relationships"] == 3
    # batch shapes
    assert t["add_relationships"](rel)["duplicates"] == [["A", "B", "Serving"]]
    r = t["add_relationships"]("{bad")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)",
                 "added": [], "duplicates": [], "rejected": [], "total_relationships": 3}


def test_note_questions_shapes():
    acc, t = _tools()
    r = t["note_questions"]("not json")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)",
                 "added": 0, "skipped": 0, "total_questions": 0}
    r = t["note_questions"](42)
    assert r == {"error": "items must be a list (got int)", "added": 0, "skipped": 0, "total_questions": 0}
    r = t["note_questions"]([" Q1 ", "Q1", "", None, 3, {"q": 1}, "Q2"])
    assert r == {"added": 2, "skipped": 5, "total_questions": 2} and acc.open_questions == ["Q1", "Q2"]
    assert t["note_questions"]({"q": "x"}) == {"added": 0, "skipped": 1, "total_questions": 2}   # a dict is a 1-item batch
    assert t["note_questions"]([]) == {"added": 0, "skipped": 0, "total_questions": 2}
    assert acc.result()["openQuestions"] == ["Q1", "Q2"]


def test_finish_gate_errors_and_hint():
    acc, t = _tools()
    # nothing at all: both completeness errors, no hint
    r = t["finish"]()
    assert r["ok"] is False and r["counts"]["elements"] == 0 and "hint" not in r
    assert r["errors"] == ["summary: '' should be non-empty", "systemName: '' should be non-empty",   # sorted by path
                           "systemName/summary not set — call set_system(systemName, summary)",
                           "no elements described — call add_elements with the system's actors, components, data and behaviors"]
    # one element, system set: valid, no hint (a single element cannot be 'unrelated')
    t["set_system"]("S", "Summary.")
    t["add_elements"]([_el(name="A")])
    r = t["finish"]()
    assert r == {"ok": True, "counts": {"actors": 0, "components": 1, "data": 0, "behaviors": 0, "elements": 1,
                                       "relationships": 0, "openQuestions": 0}}
    # two unrelated elements: ok, with a hint naming them
    t["add_elements"]([_el(name="B")])
    r = t["finish"]()
    assert r["ok"] is True and r["hint"].startswith("2 element(s) have no relationship: ['A', 'B'] — connect them")
    assert " …" not in r["hint"]
    # connect one: the hint names only the other
    t["add_relationships"]([{"from": "A", "to": "B", "type": "Flow", "intent": "i"}])
    assert "hint" not in t["finish"]()
    t["add_elements"]([_el(name=f"U{i}") for i in range(9)])
    r = t["finish"]()
    assert r["hint"].startswith("9 element(s) have no relationship: ['U0', 'U1', 'U2', 'U3', 'U4', 'U5', 'U6', 'U7'] …")
    # dangling endpoints cannot arise through the tools; the gate still reports them when state is doctored
    del acc.elements["B"]
    r = t["finish"]()
    assert r["ok"] is False and r["errors"] == ["1 relationship endpoint(s) reference undeclared elements"]
    assert acc.last_finish is r


def test_schema_backstops_report_precisely_when_the_contract_tightens():
    """The per-item validators are the schema's last word: if the contract gains a rule the hand
    checks do not know, the item is rejected with the schema's own path + message."""
    acc, t = _tools()
    saved_el, saved_rel = B._ELEMENT_VALIDATOR, B._RELATIONSHIP_VALIDATOR
    try:
        B._ELEMENT_VALIDATOR = Draft7Validator({"properties": {"name": {"maxLength": 3}}, "maxProperties": 6})
        r = t["add_elements"]([_el(name="Portal", sourceShapeIds=["s1"]), _el(name="Web")])
        assert r["added"] == ["Web"] and r["rejected"][0]["name"] == "Portal"
        assert r["rejected"][0]["errors"] == [
            "<element>: {'name': 'Portal', 'role': 'Web front end', 'layer': 'Application', "
            "'aspect': 'active', 'candidateType': 'ApplicationComponent', 'sourceShapeIds': ['s1'], "
            "'provenance': {'source': 'diagram', 'representation': 'structure'}} has too many properties",
            "name: 'Portal' is too long"]
        B._ELEMENT_VALIDATOR = saved_el
        t["add_elements"]([_el(name="Portal")])
        B._RELATIONSHIP_VALIDATOR = Draft7Validator({"properties": {"intent": {"maxLength": 2}}})
        r = t["add_relationships"]([{"from": "Web", "to": "Portal", "type": "Serving", "intent": "too long"}])
        assert r["added"] == [] and r["rejected"] == [{"index": 0, "from": "Web", "to": "Portal", "type": "Serving",
                                                       "errors": ["intent: 'too long' is too long"]}]
        B._RELATIONSHIP_VALIDATOR = Draft7Validator({"maxProperties": 1})
        r = t["add_relationships"]([{"from": "Web", "to": "Portal", "type": "Serving", "intent": "ok"}])
        assert r["rejected"][0]["errors"][0].startswith("<relationship>: ")
    finally:
        B._ELEMENT_VALIDATOR, B._RELATIONSHIP_VALIDATOR = saved_el, saved_rel
    assert t["add_relationships"]([{"from": "Web", "to": "Portal", "type": "Serving", "intent": "ok"}])["added"] == [["Web", "Portal", "Serving"]]


def test_reset_clears_everything_and_tools_stay_bound():
    acc, t = _tools()
    t["set_system"]("S", "Summary."); t["add_elements"]([_el(name="A"), _el(name="B")])
    t["add_relationships"]([{"from": "A", "to": "B", "type": "Flow", "intent": "i"}]); t["note_questions"](["q"])
    assert t["finish"]()["ok"] is True and acc.last_finish is not None
    acc.reset()
    assert (acc.system_name, acc.summary, acc.elements, acc.relationships, acc._rel_keys, acc.open_questions,
            acc.last_finish) == ("", "", {}, [], set(), [], None)
    assert acc.result() == {"systemName": "", "summary": "", "actors": [], "components": [], "data": [],
                            "behaviors": [], "relationships": [], "openQuestions": []}
    # the closures still point at the same (now empty) accumulator; a previously-added triple is new again
    t["add_elements"]([_el(name="A"), _el(name="B")])
    assert t["add_relationships"]([{"from": "A", "to": "B", "type": "Flow", "intent": "i"}])["added"] == [["A", "B", "Flow"]]
    assert t["finish"]()["ok"] is False                      # set_system was cleared too
    # the module exports and the schema-derived field lists
    assert set(B.__all__) <= set(dir(B)) and B.ITEM_FIELDS[0] == "group"
    assert set(B.ELEMENT_REQUIRED) == {"name", "role", "layer", "aspect", "candidateType", "provenance"}
    assert set(B.RELATIONSHIP_FIELDS) == {"from", "to", "type", "intent"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
