"""What each CAFÉ view is drawn FROM — the step outputs, mapped to the inputs the views take.

Pure: step outputs in, view inputs out. The views themselves are the CAFÉ skills' renderers
(`lab.core.usecase.views`); this is the half that is the pipeline's own, and the half that decides
what a reviewer sees, so it is tested on the shapes the steps actually emit.
"""
from lab.workloads.usecase import views as V

COVERAGE = {"matched": [
    {"function": "Read PDF packet", "capability_id": "KNW.08", "status": "new"},
    {"function": "Find key facts", "capability_id": "KNW.08", "status": "consumed"},
    {"function": "Retrieve criteria", "capability_id": "KNW.03", "status": "consumed"},
    {"function": "Apply criteria", "capability_id": "COG.02"},
    {"function": "Check version", "capability_id": "XCT.22", "status": "missing"}]}


# ------------------------------------------------------------------ step 5
def test_one_block_per_capability_with_the_strongest_status_and_the_functions_it_serves():
    caps = {c["id"]: c for c in V.capability_input(COVERAGE)}
    assert set(caps) == {"KNW.08", "KNW.03", "COG.02", "XCT.22"}
    assert caps["KNW.08"]["status"] == "new", "one function introduces it, so it is new"
    assert caps["KNW.03"]["status"] == "consumed"
    assert caps["XCT.22"]["status"] == "missing", "missing outranks everything: it is a gap"
    assert caps["COG.02"]["status"] == "new", "matched with no status: needed, and nothing said it exists"
    assert "Read PDF packet" in caps["KNW.08"]["note"] and "Find key facts" in caps["KNW.08"]["note"]


# ------------------------------------------------------------------ step 6
REALISATION = {"shortlist": [
    {"capability_id": "KNW.08", "route": "microsoft", "realisation": "Document Intelligence",
     "preferred": True},
    {"capability_id": "KNW.08", "route": "sovereign", "realisation": "Core42 OCR"},
    {"capability_id": "COG.02", "route": "sovereign", "realisation": "Core42 Compass",
     "preferred": True}]}


def test_the_realisation_view_shows_the_preferred_route_of_each_matched_capability():
    rows = {r["id"]: r for r in V.realisation_input(COVERAGE, REALISATION)}
    assert rows["KNW.08"] == {"id": "KNW.08", "status": "new", "route": "microsoft",
                              "product": "Document Intelligence"}
    assert rows["COG.02"]["route"] == "sovereign"


def test_a_matched_capability_with_nothing_shortlisted_is_a_realisation_gap():
    rows = {r["id"]: r for r in V.realisation_input(COVERAGE, REALISATION)}
    assert rows["KNW.03"]["status"] == "missing" and "no realisation" in rows["KNW.03"]["note"]


# ------------------------------------------------------------------ step 9
DELTA = {"concepts": [
    {"object": "Payer", "id": "Payer", "status": "matched"},
    {"object": "Criteria version", "status": "gap", "name": "Criteria version", "module": "CLN",
     "kind": "document", "definition": "Which criteria text was in force."}],
    "relationships": [{"subject": "Criteria version", "predicate": "governs", "object": "Payer",
                       "status": "gap"}], "conflicts": []}


def test_a_gap_is_drawn_under_the_name_its_relationships_use():
    inp = V.ontology_input(DELTA)
    ids = {c["id"]: c for c in inp["concepts"]}
    assert ids["Payer"]["status"] == "matched"
    assert ids["Criteria version"]["status"] == "gap" and ids["Criteria version"]["module"] == "CLN"
    assert inp["relationships"][0]["subject"] in ids


# ------------------------------------------------------------------ step 10
GRAPH = {"nodes": [
    {"id": "n1", "activity": "Receive request", "performed_by": "Intake"},
    {"id": "n2", "activity": "Read packet", "performed_by": "Reviewer", "function": "Read PDF packet"},
    {"id": "n3", "activity": "Record decision", "performed_by": "Reviewer"}],
    "edges": [{"from": "n1", "to": "n2", "data_class": "request"},
              {"from": "n2", "to": "n3", "data_class": "facts"}]}


def test_the_workflow_becomes_lanes_of_tasks_labelled_with_their_capability():
    spec = V.workflow_spec(GRAPH, COVERAGE, title="Prior auth")
    assert [ln["label"] for ln in spec["lanes"]] == ["Intake", "Reviewer"]
    tasks = {n["id"]: n for n in spec["nodes"] if n["type"] == "task"}
    assert tasks["n2"]["cap"] == "KNW.08" and tasks["n2"]["name"] == "Read packet"
    assert "cap" not in tasks["n1"], "a step no function exercises names no capability"


def test_the_flow_opens_where_nothing_leads_in_and_closes_where_nothing_leads_out():
    spec = V.workflow_spec(GRAPH, COVERAGE)
    kinds = {n["id"]: n["type"] for n in spec["nodes"]}
    starts = [e["to"] for e in spec["edges"] if kinds[e["from"]] == "start"]
    ends = [e["from"] for e in spec["edges"] if kinds[e["to"]] == "end"]
    assert starts == ["n1"] and ends == ["n3"]
    for e in spec["edges"]:
        assert e["from"] in kinds and e["to"] in kinds


def test_an_empty_graph_is_no_flow_rather_than_a_start_joined_to_an_end():
    assert V.workflow_spec({"nodes": [], "edges": []}, COVERAGE) is None


# ------------------------------------------------------------------ the render, best effort
import asyncio
import json


def _render_with(result, monkeypatch):
    async def call(cfg, tool, args):
        return result
    monkeypatch.setattr(V.gateway, "call", call)
    return asyncio.run(V.render_screening({}, {"ontology_delta": DELTA}, "pin-1"))


def test_a_result_arriving_as_json_text_is_read_not_dropped(monkeypatch):
    out = _render_with(json.dumps({"html_ref": "art://v/o.html"}), monkeypatch)
    assert out["view_refs"] == {"9 · ontology": "art://v/o.html"} and out["warnings"] == []


def test_a_tool_that_answers_with_no_page_says_so(monkeypatch):
    out = _render_with({"summary": {}}, monkeypatch)
    assert out["view_refs"] == {} and any("no page" in w for w in out["warnings"])
