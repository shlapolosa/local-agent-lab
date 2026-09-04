"""src/lab/workloads/visio_to_archimate/workflow.py — the pure / deterministic helpers, tested directly:
JSON extraction, the jsonschema + completeness gates, MCP-result parsing (dict AND JSON-string forms,
AF #3313), image-block extraction, relation repair, the span->executor table (must equal the graph's
`@executor(id=…)` set — review A-F5), `_ea_search_many` (candidates, error) and `_call_tools_raw`
against the in-memory gateway from tests/unit/workloads/visio_to_archimate/test_workflow_run.py. Offline: no gateway, no LLM, no Redis.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_workflow_helpers.py   (also pytest-compatible)"""
import asyncio
import json
from types import SimpleNamespace


from agent_framework import Content, Message
from jsonschema import Draft7Validator

from lab.workloads.visio_to_archimate import workflow as W
from fixtures.workflow import (  # noqa: E402
    BA_OK, SCHEMA, SPEC_OK, EXECUTOR_IDS, FakeResult, Router, image_block, make_cfg, text_block)

VALIDATOR = Draft7Validator(SCHEMA)
HEADERS = {"Authorization": "Bearer ar-key"}
URL = "http://gw.test/mcp/"


# ------------------------------------------------------------------ JSON extraction + gates
def test_extract_json_accepts_fenced_embedded_and_rejects_garbage():
    assert W._extract_json('{"a": 1}') == {"a": 1}
    assert W._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert W._extract_json('```\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert W._extract_json('Here you go:\n{"a": {"b": 2}}\nthanks') == {"a": {"b": 2}}
    assert W._extract_json("no json at all") is None
    assert W._extract_json("{broken: json}") is None
    assert W._extract_json("") is None and W._extract_json(None) is None


def test_schema_errors_message_shape():
    assert W._schema_errors(VALIDATOR, None) == "not valid JSON"
    assert W._schema_errors(VALIDATOR, BA_OK) is None
    bad = json.loads(json.dumps(BA_OK))
    bad["actors"][0]["layer"] = "Cloud"
    del bad["summary"]
    err = W._schema_errors(VALIDATOR, bad)
    assert err.startswith("<root>: 'summary' is a required property; actors/0/layer: 'Cloud' is not one of"), err
    # at most five errors are reported, sorted by path
    many = {k: 1 for k in ("systemName", "summary", "actors", "components", "data", "behaviors", "relationships", "openQuestions")}
    assert W._schema_errors(VALIDATOR, many).count("; ") == 4


def test_incomplete_gate_branches():
    assert W._incomplete(BA_OK) is None
    assert W._incomplete({**BA_OK, "systemName": ""}) == "missing systemName/summary"
    assert W._incomplete({"systemName": "x", "summary": "y"}) == "no elements described"
    dangling = {**BA_OK, "relationships": [{"from": "Portal", "to": "Nobody", "type": "Serving", "intent": "i"},
                                           {"from": "Ghost", "to": "Portal", "type": "Serving", "intent": "i"}]}
    assert W._incomplete(dangling) == "2 relationship endpoint(s) reference undeclared elements"


# ------------------------------------------------------------------ MCP result parsing
def test_ref_from_dict_and_string_with_any_key():
    assert W._ref_from({"spec_ref": "art://a/b"}) == "art://a/b"
    assert W._ref_from(json.dumps({"xml_ref": "art://c/d"}), "xml_ref") == "art://c/d"


def test_pick_result_matches_on_suffix():
    res = {"semantic_mcp-semantic_validate_model": {"illegal": []}, "ea_mcp-archimate_render": "r"}
    assert W._pick_result(res, "semantic_validate_model") == {"illegal": []}
    assert W._pick_result(res, "archimate_render") == "r"
    assert W._pick_result(res, "ea_stage_import") is None
    assert W._pick_result({}, "anything") is None


def test_tool_results_maps_calls_to_parsed_results():
    contents = [Content.from_function_call(call_id="1", name="ea_mcp-archimate_render", arguments={}),
                Content.from_function_result(call_id="1", result='{"xml_ref": "art://x"}'),     # JSON string
                Content.from_function_call(call_id="2", name="semantic_mcp-semantic_validate_model", arguments={}),
                Content.from_function_result(call_id="2", result={"illegal": []}),              # dict
                Content.from_function_call(call_id="3", name="other", arguments={}),
                Content.from_function_result(call_id="3", result="plain text"),                 # not JSON: kept
                Content.from_function_result(call_id="unknown", result="orphan")]               # no call: name ""
    r = SimpleNamespace(messages=[Message("assistant", contents), Message("assistant", [Content.from_text("done")])])
    out = W._tool_results(r)
    assert out == {"ea_mcp-archimate_render": {"xml_ref": "art://x"},
                   "semantic_mcp-semantic_validate_model": {"illegal": []},
                   "other": "plain text", "": "orphan"}
    assert W._tool_results(SimpleNamespace(messages=[])) == {}


def test_images_from_pairs_image_blocks_with_their_labels():
    assert W._images_from(SimpleNamespace(content=None)) == []
    assert W._images_from(object()) == []                                # no .content at all
    assert W._images_from(FakeResult(content=[text_block("only text")])) == []
    res = FakeResult(content=[image_block(b"one"), text_block("figure 1"),
                              image_block(b"two", "image/jpeg"), image_block(b"three"),   # two images, no label between
                              text_block("figure 3"), image_block(b"four")])              # trailing, unlabelled
    assert W._images_from(res) == [(b"one", "image/png", "figure 1"), (b"two", "image/jpeg", ""),
                                   (b"three", "image/png", "figure 3"), (b"four", "image/png", "")]


# ------------------------------------------------------------------ relation repair
def test_repair_relations_legalises_and_reports_without_mutating_input():
    legal = {"elements": SPEC_OK["elements"], "relations": [dict(SPEC_OK["relations"][0], id="r1")]}
    fixed, report = W._repair_relations(legal)
    assert fixed == legal and report == []
    spec = json.loads(json.dumps(SPEC_OK))
    spec["relations"] = [dict(r, id=f"r{i}") for i, r in enumerate(spec["relations"])]
    fixed, report = W._repair_relations(spec)
    assert spec["relations"][1]["type"] == "Aggregation"                 # input untouched
    assert fixed["relations"][0]["type"] == "Serving" and fixed["relations"][1]["type"] != "Aggregation"
    assert len(report) == 1 and report[0]["original"] == "Aggregation" and report[0]["replaced"] == fixed["relations"][1]["type"]
    assert report[0]["rid"] == "r1" and report[0].get("reason")
    assert W._repair_relations({"elements": [], "relations": []}) == ({"elements": [], "relations": []}, [])


# ------------------------------------------------------------------ the graph's shape
def test_span_to_executor_table_matches_the_built_graph():
    """review A-F5: the OTel span -> run-log node table can never drift from the @executor(id=...) set."""
    wf = W.build_workflow(make_cfg(run_id=None))
    assert set(W._EXECUTOR_OF_SPAN.values()) == {e.id for e in wf.get_executors_list()}
    assert [e.id for e in wf.get_executors_list()] == EXECUTOR_IDS          # chain order
    assert wf.get_start_executor().id == "ba"
    from lab.workloads import workflowviz
    mermaid = workflowviz.mermaid(wf)
    assert mermaid and all(eid in mermaid for eid in EXECUTOR_IDS)


def test_ba_run_timeout_defaults_to_15_minutes():
    assert W.BA_RUN_TIMEOUT == 900.0


# ------------------------------------------------------------------ gateway MCP calls (fake Client)
def _with_client(router, coro_fn):
    from unittest.mock import patch
    with patch.object(W, "Client", router.client_class()):
        return asyncio.run(coro_fn())


def test_call_tools_raw_and_call_tools_pick_by_suffix_in_order():
    router = Router({"semantic_store_spec": {"spec_ref": "art://1"}, "archimate_render": FakeResult(data={"xml_ref": "x"})})
    raw = _with_client(router, lambda: W._call_tools_raw(HEADERS, URL, [("archimate_render", {"spec_ref": "art://1"}),
                                                                        ("semantic_store_spec", {"spec": {}})]))
    assert [r.data for r in raw] == [{"xml_ref": "x"}, {"spec_ref": "art://1"}]
    assert router.calls == [("archimate_render", {"spec_ref": "art://1"}), ("semantic_store_spec", {"spec": {}})]
    data = _with_client(router, lambda: W._call_tools(HEADERS, URL, [("semantic_store_spec", {"spec": {}})]))
    assert data == [{"spec_ref": "art://1"}]


def test_call_tools_raw_fails_loud_on_an_unexposed_tool():
    router = Router({"semantic_store_spec": {}})
    try:
        _with_client(router, lambda: W._call_tools_raw(HEADERS, URL, [("ea_stage_import", {})]))
    except RuntimeError as e:
        assert "tool *ea_stage_import not exposed by gateway (['srv-semantic_store_spec'])" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert router.calls == []


def test_ea_search_many_merges_unique_candidates():
    hits = {"Portal": [{"id": "1", "name": "Portal"}, {"id": "2", "name": "Portal API"}],
            "Clinician": [{"id": "1", "name": "Portal"}, {"name": "no-id"}, {"id": "3", "name": "Clinician"}]}
    router = Router({"ea_search": lambda a: hits.get(a["name_like"], [])})
    cands, err = _with_client(router, lambda: W._ea_search_many(
        HEADERS, URL, ["Portal", "", "ab", None, "Clinician", "Nothing"], scope="repo", per=7))
    assert err is None and [c["id"] for c in cands] == ["1", "2", "3"]
    assert router.calls == [("ea_search", {"name_like": "Portal", "scope": "repo", "limit": 7}),
                            ("ea_search", {"name_like": "Clinician", "scope": "repo", "limit": 7}),
                            ("ea_search", {"name_like": "Nothing", "scope": "repo", "limit": 7})]


def test_ea_search_many_reads_text_content_and_stops_at_cap():
    text_form = FakeResult(data=None, content=[text_block(json.dumps([{"id": "t1"}, {"id": "t2"}]))])
    router = Router({"ea_search": lambda a: text_form if a["name_like"] == "one" else FakeResult(data=None, content=[])})
    cands, err = _with_client(router, lambda: W._ea_search_many(HEADERS, URL, ["one", "two", "three"], cap=2))
    assert err is None and [c["id"] for c in cands] == ["t1", "t2"]
    assert len(router.calls) == 1                                        # cap reached -> no further searches
    cands, err = _with_client(router, lambda: W._ea_search_many(HEADERS, URL, ["two"]))
    assert (cands, err) == ([], None)                                    # empty content -> no items, no error


def test_ea_search_many_surfaces_failures_instead_of_looking_new():
    router = Router({"ea_object": {}})                                   # search tool not granted
    cands, err = _with_client(router, lambda: W._ea_search_many(HEADERS, URL, ["Portal"]))
    assert cands == [] and err.startswith("ea_search not exposed to this identity")

    calls = iter([[{"id": "1"}], TimeoutError("gateway timed out")])
    router = Router({"ea_search": lambda a: (lambda v: (_ for _ in ()).throw(v) if isinstance(v, Exception) else v)(next(calls))})
    cands, err = _with_client(router, lambda: W._ea_search_many(HEADERS, URL, ["Portal", "Clinician"]))
    assert [c["id"] for c in cands] == ["1"] and err == "TimeoutError: gateway timed out"   # partial + error


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
