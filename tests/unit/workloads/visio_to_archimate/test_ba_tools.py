"""Simulated BA session against the accumulator tools (pure, no network).
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_ba_tools.py   (also pytest-compatible)"""
import json


from jsonschema import Draft7Validator

from lab.workloads.visio_to_archimate import ba_tools as B


def _tools(acc):
    return {f.__name__: f for f in B.make_tools(acc)}


def test_enums_loaded_from_schema():
    s = json.loads(B.SCHEMA_PATH.read_text())
    assert B.LAYERS == tuple(s["definitions"]["element"]["properties"]["layer"]["enum"])
    assert B.ASPECTS == tuple(s["definitions"]["element"]["properties"]["aspect"]["enum"])
    assert B.RELATIONSHIP_TYPES == tuple(s["definitions"]["relationship"]["properties"]["type"]["enum"])
    assert len(B.RELATIONSHIP_TYPES) == 11
    assert B.GROUPS == ("actors", "components", "data", "behaviors")
    assert B.PROVENANCE_REPRESENTATIONS == ("structure", "vision", "document")
    assert B.PROVENANCE_SOURCES == ("diagram", "document", "requirements")


def test_ba_session():
    acc = B.BAAccumulator()
    t = _tools(acc)
    assert sorted(t) == ["add_elements", "add_relationships", "finish", "note_questions", "set_system"]
    for f in t.values():
        assert f.__doc__ and len(f.__doc__) > 40, f"{f.__name__} needs a docstring the model sees"

    # finish() before anything -> ok false, precise errors, never raises
    r = t["finish"]()
    assert r["ok"] is False and any("no elements" in e for e in r["errors"]) and any("set_system" in e for e in r["errors"])

    # set_system
    assert t["set_system"]("", "x")["ok"] is False
    r = t["set_system"]("Claims Portal", "A web portal where members file claims that an adjudication service processes.")
    assert r["ok"] is True and r["systemName"] == "Claims Portal"

    # batch 1: 3 items, one bad layer, one provenance shorthand, one provenance object
    r = t["add_elements"]([
        {"group": "actors", "name": "Member", "role": "Person who files a claim", "layer": "Business",
         "aspect": "active", "candidateType": "BusinessActor", "provenance": "vision", "sourceShapeIds": ["s1"]},
        {"group": "components", "name": "Portal", "role": "Web front end", "layer": "Bizness",   # bad layer
         "aspect": "active", "candidateType": "ApplicationComponent"},
        {"group": "components", "name": "Adjudication Service", "role": "Decides claims", "layer": "Application",
         "aspect": "behaviour", "candidateType": "ApplicationService",
         "provenance": {"source": "requirements", "representation": "document"}},
    ])
    assert r["added"] == ["Member", "Adjudication Service"], r
    assert len(r["rejected"]) == 1 and r["rejected"][0]["name"] == "Portal"
    assert "layer 'Bizness' is not one of [Motivation, Strategy, Business" in r["rejected"][0]["errors"][0]
    assert r["total_elements"] == 2
    assert acc.elements["Member"]["element"]["provenance"] == {"source": "diagram", "representation": "vision"}
    assert acc.elements["Adjudication Service"]["element"]["provenance"] == {"source": "requirements", "representation": "document"}

    # batch 2: the corrected item + a data element + a behavior; plus unknown field + bad provenance rejected
    r = t["add_elements"]([
        {"group": "components", "name": "Portal", "role": "Web front end", "layer": "Application",
         "aspect": "active", "candidateType": "ApplicationComponent", "sourceShapeIds": ["s2"],
         "provenance": "structure"},
        {"group": "data", "name": "Claim", "role": "A filed claim record", "layer": "Business",
         "aspect": "passive", "candidateType": "BusinessObject", "provenance": "structure"},
        {"group": "behaviors", "name": "File Claim", "role": "Member submits a claim", "layer": "Business",
         "aspect": "behaviour", "candidateType": "BusinessProcess", "provenance": "document"},
        {"group": "widgets", "name": "Mystery", "role": "?", "layer": "Business", "aspect": "active",
         "candidateType": "X", "provenance": "guess", "id": 7},
    ])
    assert r["added"] == ["Portal", "Claim", "File Claim"] and r["updated"] == []
    errs = r["rejected"][0]["errors"]
    assert any("unknown field(s) ['id']" in e for e in errs)
    assert any("group 'widgets'" in e for e in errs)
    assert any("provenance 'guess'" in e for e in errs)
    assert r["total_elements"] == 5

    # re-add a name with a changed role -> UPDATE/merge, no duplicate; sourceShapeIds unioned
    r = t["add_elements"]([{"group": "components", "name": "Portal", "role": "Web front end (React SPA)",
                            "layer": "Application", "aspect": "active", "candidateType": "ApplicationComponent",
                            "sourceShapeIds": ["s3"], "provenance": "structure"}])
    assert r["added"] == [] and r["updated"] == ["Portal"] and r["total_elements"] == 5
    assert acc.elements["Portal"]["element"]["role"] == "Web front end (React SPA)"
    assert acc.elements["Portal"]["element"]["sourceShapeIds"] == ["s2", "s3"]
    assert sum(1 for e in acc.result()["components"] if e["name"] == "Portal") == 1

    # batch cap
    big = [{"group": "actors", "name": f"A{i}", "role": "r", "layer": "Business", "aspect": "active",
            "candidateType": "BusinessActor"} for i in range(B.MAX_BATCH + 1)]
    r = t["add_elements"](big)
    assert "batch too large" in r["error"] and r["added"] == [] and r["total_elements"] == 5
    r = t["add_relationships"]([{"from": "Member", "to": "Portal", "type": "Serving", "intent": "x"}] * (B.MAX_BATCH + 1))
    assert "batch too large" in r["error"] and r["total_relationships"] == 0

    # relationships: one missing endpoint (rejected with message), one bad type, one valid, one duplicate
    r = t["add_relationships"]([
        {"from": "Portal", "to": "Ghost Service", "type": "Serving", "intent": "portal calls a ghost"},
        {"from": "Portal", "to": "Member", "type": "Uses", "intent": "bad type"},
        {"from": "Portal", "to": "Member", "type": "Serving", "intent": "the portal serves the member"},
        {"from": "Portal", "to": "Member", "type": "Serving", "intent": "same again"},
        {"from": "File Claim", "to": "Claim", "type": "Access", "intent": "the process creates the claim"},
        {"from": "Adjudication Service", "to": "Portal", "type": "Serving", "intent": "adjudication serves the portal"},
    ])
    assert r["added"] == [["Portal", "Member", "Serving"], ["File Claim", "Claim", "Access"],
                          ["Adjudication Service", "Portal", "Serving"]], r
    assert r["duplicates"] == [["Portal", "Member", "Serving"]]
    assert len(r["rejected"]) == 2
    assert "to 'Ghost Service' is not a declared element" in r["rejected"][0]["errors"][0]
    assert "type 'Uses' is not one of [Composition, Aggregation" in r["rejected"][1]["errors"][0]
    assert r["total_relationships"] == 3

    # questions: dedupe + skip empties
    r = t["note_questions"](["Is the Portal also used by staff?", "", "Is the Portal also used by staff?"])
    assert r == {"added": 1, "skipped": 2, "total_questions": 1}

    # JSON-string tolerance (a model may hand the list over as a string)
    r = t["note_questions"](json.dumps(["Where does Claim persist?"]))
    assert r["added"] == 1

    # finish -> ok true, and the document validates against the schema independently
    r = t["finish"]()
    assert r["ok"] is True, r
    assert r["counts"] == {"actors": 1, "components": 2, "data": 1, "behaviors": 1,
                           "elements": 5, "relationships": 3, "openQuestions": 2}
    assert "errors" not in r
    doc = acc.result()
    v = Draft7Validator(json.loads(B.SCHEMA_PATH.read_text()))
    assert list(v.iter_errors(doc)) == []
    assert list(doc) == ["systemName", "summary", "actors", "components", "data", "behaviors", "relationships", "openQuestions"]
    assert acc.last_finish is r
    # result() is a copy: mutating it does not touch the accumulator
    doc["actors"].clear()
    assert len(acc.result()["actors"]) == 1
    return acc.result(), r


def test_finish_with_zero_elements():
    acc = B.BAAccumulator()
    t = _tools(acc)
    t["set_system"]("Empty", "Nothing here.")
    r = t["finish"]()
    assert r["ok"] is False and r["errors"] and "no elements described" in r["errors"][0]
    assert r["counts"]["elements"] == 0


if __name__ == "__main__":
    test_enums_loaded_from_schema()
    print("enums:", {"GROUPS": B.GROUPS, "LAYERS": B.LAYERS, "ASPECTS": B.ASPECTS,
                     "RELATIONSHIP_TYPES": B.RELATIONSHIP_TYPES,
                     "PROVENANCE_REPRESENTATIONS": B.PROVENANCE_REPRESENTATIONS,
                     "PROVENANCE_SOURCES": B.PROVENANCE_SOURCES})
    doc, rep = test_ba_session()
    print("finish():", json.dumps(rep))
    print("document:", json.dumps(doc, indent=1))
    test_finish_with_zero_elements()
    print("ALL TESTS PASSED")
