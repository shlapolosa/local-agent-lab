"""src/lab/workloads/visio_to_archimate/workflow.py — the WHOLE graph run OFFLINE (BA_MODE=json,
ARCHITECT_MODE=json): the real Agent Framework `WorkflowBuilder` chain (ba -> resolve_existing ->
architect_design -> store -> architect_finalize -> stage_import) is driven with fakes at the seams the
module already exposes as globals —
  * `workflow.Client`      the fastmcp client -> one in-memory "gateway MCP" (Router) that answers every
                           tool by name suffix (dict AND JSON-string results, AF #3313) and records calls;
  * `agents.make_agent`    -> scripted fake agents (ordered turns per agent name);
  * `agents.ba_tools` / `agents.architect_tools` -> inert async-context tools (no GATEWAY_URL, no HTTP);
  * `lab.platform.runlog`        -> an in-memory recorder (no Redis); OTel endpoint unset -> no-op tracer.
No gateway, no LLM, no network, no Redis. The fakes here are shared by tests/unit/workloads/visio_to_archimate/test_workflow_tools_mode.py
and tests/unit/workloads/visio_to_archimate/test_workflow_helpers.py.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_workflow_run.py   (also pytest-compatible)"""
import asyncio
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from lab.workloads.visio_to_archimate import workflow as W
from lab.workloads import ids

from fixtures.workflow import (
    SCHEMA, TRACEPARENT, BA_OK, SPEC_OK, FakeResult, image_block, text_block, Agents, text_of, data_contents, tool_call_response, make_cfg, harness, run, raises, EXECUTOR_IDS)


# ------------------------------------------------------------------ tests
def test_fixtures_honour_the_contracts():
    from jsonschema import Draft7Validator
    assert W._schema_errors(Draft7Validator(SCHEMA), BA_OK) is None
    assert W._incomplete(BA_OK) is None


def test_json_mode_vsdx_path_end_to_end():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h:
        out = run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})

    # -- the output contract of stage_import
    assert out["request_id"] == "req-1" and out["status"] == "pending" and out["review_app"] == "http://review/req-1"
    assert out["xml_ref"] == "art://x/visio-import.archimate.xml" and out["svg_refs"] == ["art://x/a.svg", "art://x/b.svg"]
    assert out["xlsx_ref"] == "art://x/visio-import.xlsx"
    assert out["semantic"] == {"illegal": [], "warnings": ["w1"]}
    s = out["summary"]
    assert s["elements"] == 3 and s["relations"] == 2 and s["views"] == 2
    assert s["semantic_illegal"] == 0 and s["semantic_warnings"] == 1
    assert s["decision"] == "NEW" and s["domain"] == "Clinic Portal" and s["base_model"] is None
    assert s["matched_existing"] == 0 and s["new_elements"] == 3 and s["search_failed"] is False
    assert s["resolve_rationale"] == "no related objects found in the ADOIT repository"
    assert s["excel_objects"] == 3 and s["ba_output_ref"] == "art://store/visio-import.ba_output.json"
    # -- deterministic stamping in architect_design: folder = domain, stable relation ids, legal relations
    spec = out["spec"]
    assert spec["standard_views"] is True
    assert all(e["folder"] == "Clinic Portal" for e in spec["elements"])
    # ids are minted from the relation AS EMITTED (before relrepair rewrites the type) - stable across runs
    assert [r["id"] for r in spec["relations"]] == [ids.rid(r["src"], r["type"], r["tgt"]) for r in SPEC_OK["relations"]]
    assert s["relation_repairs"] == 1 and len(s["repair_notes"]) == 1
    assert spec["relations"][1]["type"] != "Aggregation"          # legalised by relrepair
    assert SPEC_OK["relations"][1]["type"] == "Aggregation"       # the fixture itself is not mutated
    # -- gateway tool traffic, in order, with the Architect's identity for tool nodes
    suffixes = [s for s, _ in h.router.calls]
    assert suffixes == ["semantic_store_spec", "adoit_search", "adoit_search", "adoit_search", "adoit_search",
                        "semantic_store_spec", "semantic_validate_model", "archimate_render",
                        "adoit_excel_render", "adoit_request_import"], suffixes
    store_ba, store_spec = h.router.called("semantic_store_spec")
    assert store_ba == {"spec": BA_OK, "name": "visio-import.ba_output.json"}
    assert store_spec["name"] == "visio-import.spec.json" and store_spec["spec"]["standard_views"] is True
    assert [a["name_like"] for a in h.router.called("adoit_search")] == ["Clinic Portal", "Portal", "Clinician", "Patient Record"]
    assert h.router.called("semantic_validate_model") == [{"spec_ref": "art://store/visio-import.spec.json"}]
    assert h.router.called("archimate_render") == [{"spec_ref": "art://store/visio-import.spec.json", "basename": "visio-import"}]
    req = h.router.called("adoit_request_import")[0]
    assert req["model_name"] == "Clinic Portal" and req["requester"] == "architect-agent"
    assert req["xlsx_ref"] == "art://x/visio-import.xlsx" and req["summary"] == s
    # -- BA (local path): local function tools, no addendum, the read instruction names read_vsdx
    ba = h.agents.agent("ba-agent")
    assert "read_vsdx" in ba.tools_by_name and "read_document" in ba.tools_by_name
    assert ba.credential == "ba-key" and ba.traceparent == TRACEPARENT
    assert "Call read_vsdx with exactly that source" in text_of(h.agents.runs_of("ba-agent")[0])
    assert "add_elements" not in ba.instructions
    # -- the Architect: design prompt has no EXISTING block (nothing matched); finalize prompt is by ref
    design, finalize = h.agents.runs_of("architect-agent")
    assert "EXISTING ARCHITECTURE" not in design and json.dumps(BA_OK) in design
    assert "art://store/visio-import.spec.json" in finalize and "semantic_validate_model" in finalize
    assert h.agents.made[-1].credential == "ar-key" and h.agents.made[-1].tools[0].name == "ea-tools"
    # -- live run visibility: every executor node start/done in graph order + the mermaid graph
    assert [n for _, n, st in h.runlog.nodes if st == "start"] == EXECUTOR_IDS
    assert all(st in ("start", "done") for _, _, st in h.runlog.nodes) and all(r == "run-test" for r, _, _ in h.runlog.nodes)
    assert h.runlog.updates and "mermaid" in h.runlog.updates[0][1] and "flowchart" in h.runlog.updates[0][1]["mermaid"]


def test_by_ref_inputs_existing_update_and_agent_tool_results():
    """art:// inputs: the image diagram + document figures are fetched through the gateway and
    attached inline; ADOIT has candidates, the resolver says UPDATE with a match, the Architect
    reuses the adoit_id; the finalize agent DID call its tools (dict + JSON-string results), so the
    deterministic fallbacks are skipped; MCP results arrive as JSON strings (AF #3313)."""
    cands = [{"id": "{1111-aaaa}", "name": "Portal", "metaName": "C_APPLICATION_COMPONENT"},
             {"id": "{2222-bbbb}", "name": "Clinician", "metaName": "C_BUSINESS_ACTOR"}]
    resolved = {"decision": "UPDATE", "domain": "Clinical Apps", "base_model": "Clinic Portal v1",
                "matched": {"Portal": {"adoit_id": "{1111-aaaa}", "adoit_name": "Portal", "class": "ApplicationComponent"}},
                "rationale": "same portal"}
    spec = json.loads(json.dumps(SPEC_OK))
    spec["elements"][1]["id"] = "{1111-aaaa}"                    # the Architect reuses the existing id
    spec["elements"][2]["folder"] = "Kept"                       # an explicit folder is not overwritten
    for r in spec["relations"]:
        r["src"] = "{1111-aaaa}"
    render = {"xml_ref": "art://agent/x.xml", "svg_refs": ["art://agent/v.svg"], "views": {"v": {}}}
    agents = Agents(**{
        "ba-agent": ["```json\n" + json.dumps(BA_OK) + "\n```"],       # fenced JSON is accepted
        "resolve-agent": [resolved],
        "architect-agent": [spec, tool_call_response("done", [
            ("semantic_mcp-semantic_validate_model", {"illegal": ["x->y"], "warnings": []}),
            ("adoit_mcp-archimate_render", json.dumps(render))])]})
    tools = {
        "semantic_store_spec": lambda a: json.dumps({"spec_ref": f"art://s/{a['name']}"}),   # string result
        "adoit_search": lambda a: cands if a["name_like"] in ("Portal", "Clinician") else [],
        "storage_get": FakeResult(content=[image_block(b"diagram-bytes"), text_block("diagram.png")]),
        "storage_extract_figures": FakeResult(content=[
            image_block(b"fig-1", "image/jpeg"), text_block("figure 1 embedded in req.docx"),
            image_block(b"fig-2")]),                                # trailing image without a label
    }
    with harness(agents, tools) as h:
        out = run(h, {"diagram": "art://d1/diagram.png", "requirements": ["art://r1/req.docx"]})

    # BA message: attached image + instructions naming the storage tools + both figures
    msg = h.agents.runs_of("ba-agent")[0]
    t = text_of(msg)
    assert "The system diagram is the ATTACHED IMAGE" in t
    assert "A requirements document is provided: art://r1/req.docx" in t and "Call storage_read_document" in t
    assert "Attached: figure 1 embedded in req.docx" in t and "Attached: embedded figure" in t
    assert t.rstrip().endswith("Then produce the JSON system description.")
    imgs = data_contents(msg)
    assert len(imgs) == 3 and [c.media_type for c in imgs] == ["image/png", "image/jpeg", "image/png"]
    assert h.router.called("storage_get") == [{"ref": "art://d1/diagram.png"}]
    assert h.router.called("storage_extract_figures") == [{"ref": "art://r1/req.docx"}]
    ba = h.agents.agent("ba-agent")
    assert ba.tools[0].name == "storage" and ba.tools[0].opened == 1 and ba.tools[0].headers["Authorization"] == "Bearer ba-key"
    # resolver: candidates merged by id (each term found both) and passed in the prompt
    assert len(h.router.called("adoit_search")) == 4
    rprompt = h.agents.runs_of("resolve-agent")[0]
    assert "Existing ADOIT candidates" in rprompt and rprompt.count("{1111-aaaa}") == 1
    # architect design prompt carries the EXISTING block; summary reflects the UPDATE
    design = h.agents.runs_of("architect-agent")[0]
    assert "Decision: UPDATE in domain 'Clinical Apps'" in design and "{1111-aaaa}" in design
    s = out["summary"]
    assert s["decision"] == "UPDATE" and s["domain"] == "Clinical Apps" and s["base_model"] == "Clinic Portal v1"
    assert s["matched_existing"] == 1 and s["new_elements"] == 2 and s["resolve_rationale"] == "same portal"
    assert s["search_failed"] is False
    folders = {e["id"]: e["folder"] for e in out["spec"]["elements"]}
    assert folders == {"clinician": "Clinical Apps", "{1111-aaaa}": "Clinical Apps", "patient-record": "Kept"}
    # finalize used the agent's own tool results: no fallback validate/render calls, only the Excel render
    assert h.router.called("semantic_validate_model") == [] and h.router.called("archimate_render") == []
    assert out["xml_ref"] == "art://agent/x.xml" and out["svg_refs"] == ["art://agent/v.svg"] and s["views"] == 1
    assert out["semantic"]["illegal"] == ["x->y"] and s["semantic_illegal"] == 1
    assert h.router.called("adoit_excel_render") == [{"spec_ref": "art://s/visio-import.spec.json", "basename": "visio-import"}]
    assert s["ba_output_ref"] == "art://s/visio-import.ba_output.json"


def test_image_ref_without_image_content_fails_loud():
    """A gateway that flattens the image to text must not silently produce a blind BA run."""
    agents = Agents(**{"ba-agent": [BA_OK]})
    with harness(agents, {"storage_get": FakeResult(content=[text_block("flattened")])}) as h:
        raises(h, {"diagram": "art://d1/diagram.png"}, RuntimeError, "no image content for art://d1/diagram.png")
    assert h.runlog.nodes == [("run-test", "ba", "start"), ("run-test", "ba", "fail:RuntimeError")]
    assert h.agents.runs == []


def test_local_image_path_and_local_document():
    """Dev inputs by PATH: the image is loaded from disk and attached; a .md requirements document
    is read by the BA's local read_document tool (no figures to extract)."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with tempfile.TemporaryDirectory() as d, harness(agents) as h:
        png, md = os.path.join(d, "diagram.png"), os.path.join(d, "req.md")
        open(png, "wb").write(b"\x89PNG local")
        open(md, "w").write("# Requirements\n- the portal must be fast\n")
        run(h, {"diagram": png, "requirements": [md]})
    msg = h.agents.runs_of("ba-agent")[0]
    assert [c.media_type for c in data_contents(msg)] == ["image/png"]
    t = text_of(msg)
    assert "ATTACHED IMAGE" in t and f"A requirements document is provided: {md}" in t and "Call read_document" in t
    assert "Attached:" not in t
    assert h.router.called("storage_get") == [] and h.router.called("storage_extract_figures") == []


def test_ba_retry_resends_the_inputs_then_succeeds():
    incomplete = {**BA_OK, "relationships": [{"from": "Portal", "to": "Ghost", "type": "Serving", "intent": "x"}]}
    cases = [("this is not json", "not valid JSON"),
             ({"systemName": "X"}, "<root>: 'summary' is a required property"),
             (incomplete, "1 relationship endpoint(s) reference undeclared elements"),
             ({**BA_OK, "actors": [], "components": [], "data": []}, "no elements described")]
    for first, err in cases:
        agents = Agents(**{"ba-agent": [first, BA_OK], "architect-agent": [SPEC_OK, "done"]})
        tools = {"storage_get": FakeResult(content=[image_block(b"img"), text_block("d.png")])}
        with harness(agents, tools) as h:
            out = run(h, {"diagram": "art://d/diagram.png"})
        first_msg, retry = h.agents.runs_of("ba-agent")
        note = text_of(retry)
        assert f"Your previous answer was rejected: {err}" in note, note
        assert "Output the JSON object FIRST" in note
        assert data_contents(retry)[0].uri == data_contents(first_msg)[0].uri       # the image rides again
        assert out["summary"]["elements"] == 3


def test_ba_rejected_twice_raises():
    agents = Agents(**{"ba-agent": ["nope", "still nope"]})
    with harness(agents) as h:
        raises(h, "diagrams/x.vsdx", RuntimeError, "BA output rejected (incomplete after retry): not valid JSON")
    assert h.router.called("semantic_store_spec") == []     # nothing persisted before the gate


def test_resolver_output_rejected_falls_back_to_new():
    cands = [{"id": "{1}", "name": "Portal"}]
    for bad, fragment in [({"decision": "MAYBE", "domain": "d", "matched": {}}, "decision: 'MAYBE' is not one of"),
                          ("no json here", "no JSON"),
                          ({"matched": {"Portal": {}}}, "adoit_id")]:
        agents = Agents(**{"ba-agent": [BA_OK], "resolve-agent": [bad], "architect-agent": [SPEC_OK, "done"]})
        with harness(agents, {"adoit_search": cands}) as h:
            out = run(h, "diagrams/x.vsdx")
        s = out["summary"]
        assert s["decision"] == "NEW" and s["domain"] == "Clinic Portal" and s["base_model"] is None
        assert s["matched_existing"] == 0 and s["search_failed"] is False
        assert s["resolve_rationale"].startswith("resolver output rejected by the schema gate: ")
        assert fragment in s["resolve_rationale"], s["resolve_rationale"]
        assert "EXISTING ARCHITECTURE" not in h.agents.runs_of("architect-agent")[0]


def test_resolver_minimal_valid_output_gets_defaults():
    agents = Agents(**{"ba-agent": [BA_OK], "resolve-agent": [{"decision": "UPDATE", "domain": "Ops", "matched": {}}],
                       "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"adoit_search": [{"id": "{1}", "name": "Portal"}]}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["decision"] == "UPDATE" and s["domain"] == "Ops" and s["base_model"] is None
    assert s["resolve_rationale"] is None and s["matched_existing"] == 0
    assert "Decision: UPDATE in domain 'Ops'" in h.agents.runs_of("architect-agent")[0]   # UPDATE alone triggers the block
    assert all(e["folder"] == "Ops" for e in out["spec"]["elements"])


def test_search_failure_marks_new_as_unverified():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"adoit_search": ConnectionError("gateway down")}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["decision"] == "NEW" and s["search_failed"] is True
    assert "ADOIT search FAILED (ConnectionError: gateway down) — NEW is UNVERIFIED" in s["resolve_rationale"]
    assert "resolve-agent" not in [a.name for a in h.agents.made]


def test_search_tool_not_granted_is_a_failed_search():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"adoit_search": None}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["search_failed"] is True and "adoit_search not exposed to this identity" in s["resolve_rationale"]


def test_architect_invalid_then_valid_spec():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": ["I think...", {"name": "n", "id": "i"}, "done"]})
    with harness(agents) as h:
        raises(h, "diagrams/x.vsdx", RuntimeError, "Architect produced no spec")
    assert "not a valid engine spec" in h.agents.runs_of("architect-agent")[1]

    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": ["prose", SPEC_OK, "done"]})
    with harness(agents) as h:
        out = run(h, "diagrams/x.vsdx")
    assert out["summary"]["elements"] == 3 and len(h.agents.runs_of("architect-agent")) == 3


def test_finalize_partial_agent_results_use_fallbacks_per_tool():
    """Agent rendered (string result) but skipped validation -> only the validate fallback runs;
    a render result without xml_ref is not trusted -> render fallback runs."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, tool_call_response("done", [
        ("adoit_mcp-archimate_render", json.dumps({"xml_ref": "art://agent/x.xml", "views": {}})),
        ("semantic_mcp-semantic_validate_model", "not-json-at-all")])]})
    with harness(agents) as h:
        out = run(h, "diagrams/x.vsdx")
    assert len(h.router.called("semantic_validate_model")) == 1 and h.router.called("archimate_render") == []
    assert out["xml_ref"] == "art://agent/x.xml" and out["svg_refs"] == [] and out["summary"]["views"] == 0

    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, tool_call_response("done", [
        ("adoit_mcp-archimate_render", {"error": "render failed"})])]})
    with harness(agents, {"adoit_excel_render": None}) as h:
        try:
            run(h, "diagrams/x.vsdx")
        except RuntimeError as e:                    # excel tool missing -> fail loud (pick raises)
            assert "tool *adoit_excel_render not exposed by gateway" in str(e)
        else:
            raise AssertionError("expected the missing tool to fail the run")
    assert len(h.router.called("archimate_render")) == 1
    assert h.runlog.nodes[-1] == ("run-test", "architect_finalize", "fail:RuntimeError")


def test_run_workflow_bare_string_input_without_run_id_is_otel_only():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, run_id=None) as h:
        out = run(h, "diagrams/x.vsdx")
    assert out["request_id"] == "req-1"
    assert h.runlog.nodes == [] and h.runlog.updates == []
    assert h.agents.runs_of("ba-agent")[0] is not None


def test_run_workflow_without_outputs_raises():
    class NoOutput:
        async def run(self, inputs):
            return SimpleNamespace(get_outputs=lambda: [])
    with patch.object(W, "build_workflow", lambda cfg: NoOutput()):
        try:
            asyncio.run(W.run_workflow(make_cfg(run_id=None), "x.vsdx"))
        except RuntimeError as e:
            assert "workflow produced no output" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
