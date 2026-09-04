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
    SCHEMA, TRACEPARENT, BA_OK, BA_NORMALISED, SPEC_OK, FakeResult, image_block, text_block, Agents, text_of, data_contents, tool_call_response, make_cfg, harness, run, raises, EXECUTOR_IDS)


# ------------------------------------------------------------------ tests
def test_fixtures_honour_the_contracts():
    from jsonschema import Draft7Validator
    assert W._schema_errors(Draft7Validator(SCHEMA), BA_OK) is None
    assert W._incomplete(BA_OK) is None
    # the whole gate, on a COPY: _ba_gate normalises provenance in place, so it never runs on the
    # shared fixture (a mutated fixture would silently change every later test's expectations)
    assert W._ba_gate(Draft7Validator(SCHEMA), json.loads(json.dumps(BA_OK))) is None
    assert W._ba_gate(Draft7Validator(SCHEMA), None) == "not valid JSON"


def test_json_mode_vsdx_path_end_to_end():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h:
        out = run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})

    # -- the output contract of stage_import
    assert out["request_id"] == "req-1" and out["status"] == "pending" and out["review_app"] == "http://review/req-1"
    assert out["xml_ref"] == "art://x/visio-import.archimate.xml"
    assert out["svg_refs"] == {"landscape": "art://x/a.svg", "detail": "art://x/b.svg"}
    # the repository's import files ride through OPAQUELY — the workload never learns what they are
    assert out["import_artifacts"] == [{"ref": "art://x/visio-import.xlsx",
                                        "label": "Download objects (5 objects)",
                                        "note": "matched by name", "media_type": ""}]
    assert out["semantic"] == {"illegal": [], "warnings": ["w1"]}
    s = out["summary"]
    assert s["elements"] == 3 and s["relations"] == 2 and s["views"] == 2
    assert s["semantic_illegal"] == 0 and s["semantic_warnings"] == 1
    assert s["decision"] == "NEW" and s["domain"] == "Clinic Portal" and s["base_model"] is None
    assert s["matched_existing"] == 0 and s["new_elements"] == 3 and s["search_failed"] is False
    assert s["resolve_rationale"] == "no related objects found in the EA repository"
    assert "import_objects" not in s         # what the import file holds is the REPOSITORY's business
    assert s["ba_output_ref"] == "art://store/visio-import.ba_output.json"
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
    assert suffixes == ["semantic_store_spec", "ea_search", "ea_search", "ea_search", "ea_search",
                        "semantic_store_spec", "semantic_validate_model", "archimate_render",
                        "ea_stage_import"], suffixes
    store_ba, store_spec = h.router.called("semantic_store_spec")
    assert store_ba == {"spec": BA_NORMALISED, "name": "visio-import.ba_output.json"}
    assert store_spec["name"] == "visio-import.spec.json" and store_spec["spec"]["standard_views"] is True
    assert [a["name_like"] for a in h.router.called("ea_search")] == ["Clinic Portal", "Clinician", "Portal", "Patient Record"]
    assert h.router.called("semantic_validate_model") == [{"spec_ref": "art://store/visio-import.spec.json"}]
    assert h.router.called("archimate_render") == [{"spec_ref": "art://store/visio-import.spec.json", "basename": "visio-import"}]
    # ONE call to the port: the model BY REF (+ the views already rendered), never an import artifact
    req = h.router.called("ea_stage_import")[0]
    assert req["model_name"] == "Clinic Portal" and req["requester"] == "architect-agent"
    assert req["spec_ref"] == "art://store/visio-import.spec.json" and req["summary"] == s
    assert "import_artifacts" not in req and req["xml_ref"] == out["xml_ref"]
    # -- BA (local path): local function tools, no addendum, the read instruction names read_vsdx
    ba = h.agents.agent("ba-agent")
    assert "read_vsdx" in ba.tools_by_name and "read_document" in ba.tools_by_name
    assert ba.credential == "ba-key" and ba.traceparent == TRACEPARENT
    assert "Call read_vsdx with exactly that source" in text_of(h.agents.runs_of("ba-agent")[0])
    assert "add_elements" not in ba.instructions
    # -- the Architect: design prompt has no EXISTING block (nothing matched); finalize prompt is by ref
    design, finalize = h.agents.runs_of("architect-agent")
    assert "EXISTING ARCHITECTURE" not in design and json.dumps(BA_NORMALISED) in design
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
    render = {"xml_ref": "art://agent/x.xml", "svg_refs": {"v": "art://agent/v.svg"}, "views": {"v": {}}}
    agents = Agents(**{
        "ba-agent": ["```json\n" + json.dumps(BA_OK) + "\n```"],       # fenced JSON is accepted
        "resolve-agent": [resolved],
        "architect-agent": [spec, tool_call_response("done", [
            ("semantic_mcp-semantic_validate_model", {"illegal": ["x->y"], "warnings": []}),
            ("ea_mcp-archimate_render", json.dumps(render))])]})
    tools = {
        "semantic_store_spec": lambda a: json.dumps({"spec_ref": f"art://s/{a['name']}"}),   # string result
        "ea_search": lambda a: cands if a["name_like"] in ("Portal", "Clinician") else [],
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
    assert len(h.router.called("ea_search")) == 4
    rprompt = h.agents.runs_of("resolve-agent")[0]
    assert "Existing EA repository candidates" in rprompt and rprompt.count("{1111-aaaa}") == 1
    # architect design prompt carries the EXISTING block; summary reflects the UPDATE
    design = h.agents.runs_of("architect-agent")[0]
    assert "Decision: UPDATE in domain 'Clinical Apps'" in design and "{1111-aaaa}" in design
    s = out["summary"]
    assert s["decision"] == "UPDATE" and s["domain"] == "Clinical Apps" and s["base_model"] == "Clinic Portal v1"
    assert s["matched_existing"] == 1 and s["new_elements"] == 2 and s["resolve_rationale"] == "same portal"
    assert s["search_failed"] is False
    folders = {e["id"]: e["folder"] for e in out["spec"]["elements"]}
    assert folders == {"clinician": "Clinical Apps", "{1111-aaaa}": "Clinical Apps", "patient-record": "Kept"}
    # finalize used the agent's own tool results: no fallback validate/render calls
    assert h.router.called("semantic_validate_model") == [] and h.router.called("archimate_render") == []
    assert out["xml_ref"] == "art://agent/x.xml" and out["svg_refs"] == {"v": "art://agent/v.svg"} and s["views"] == 1
    assert out["semantic"]["illegal"] == ["x->y"] and s["semantic_illegal"] == 1
    assert out["import_artifacts"][0]["ref"] == "art://x/visio-import.xlsx"   # the repository's, not ours
    assert s["ba_output_ref"] == "art://s/visio-import.ba_output.json"


# ------------------------------------------------------------------ vsdx dual representation
def test_vsdx_ref_attaches_the_rendered_page_beside_the_structured_parse():
    """A .vsdx gets BOTH representations: the parse the BA pulls with storage_read_vsdx, and the
    page rendered to an image by storage_render_vsdx and attached inline for vision."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    tools = {"storage_render_vsdx": FakeResult(content=[image_block(b"page-1-png"),
                                                        text_block("clinic.vsdx page 1 1600x900 image/png")])}
    with harness(agents, tools) as h:
        run(h, {"diagram": "art://d1/clinic.vsdx#Ward", "requirements": []})
    msg = h.agents.runs_of("ba-agent")[0]
    t = text_of(msg)
    assert "Call storage_read_vsdx with exactly that source" in t          # the parse: unchanged
    # `#Ward` means parse and picture cover the SAME single page — no qualification needed
    assert "ATTACHED IMAGE of the SAME diagram page" in t
    assert "deterministic parse wins" in t and "openQuestions" in t        # the reconciliation rule
    assert [c.media_type for c in data_contents(msg)] == ["image/png"]
    assert h.router.called("storage_render_vsdx") == [{"ref": "art://d1/clinic.vsdx#Ward"}]


def test_vsdx_run_degrades_to_structure_only_when_the_host_cannot_render():
    """No LibreOffice on the storage-mcp host -> the tool errors -> the run continues on the parse
    alone and SAYS so, rather than failing (the capability is optional by design)."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    tools = {"storage_render_vsdx": RuntimeError("LibreOffice (soffice) not found")}
    with harness(agents, tools) as h:
        out = run(h, {"diagram": "art://d1/clinic.vsdx", "requirements": []})
    assert out["status"] == "pending"
    msg = h.agents.runs_of("ba-agent")[0]
    t = text_of(msg)
    assert data_contents(msg) == []
    assert "ATTACHED IMAGE of the SAME diagram page" not in t
    assert "No rendered image of this diagram is available" in t
    assert h.router.called("storage_render_vsdx") == [{"ref": "art://d1/clinic.vsdx"}]


def test_vsdx_render_that_returns_no_image_is_treated_as_unavailable():
    """A gateway that flattened the image blocks to text must not claim an attached picture."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    tools = {"storage_render_vsdx": FakeResult(content=[text_block("flattened")])}
    with harness(agents, tools) as h:
        run(h, {"diagram": "art://d1/clinic.vsdx", "requirements": []})
    msg = h.agents.runs_of("ba-agent")[0]
    assert data_contents(msg) == [] and "No rendered image" in text_of(msg)


def test_a_whole_workbook_is_told_the_image_covers_ONE_page():
    """No `#page` fragment -> the parse covers EVERY page but only one is rendered. The message must
    say which, or the BA reconciles page 2's structure against page 1's picture."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    tools = {"storage_render_vsdx": FakeResult(content=[image_block(b"p1"),
                                                        text_block("clinic.vsdx page 1 1600x900 image/png")])}
    with harness(agents, tools) as h:
        run(h, {"diagram": "art://d1/clinic.vsdx", "requirements": []})
    t = text_of(h.agents.runs_of("ba-agent")[0])
    assert "clinic.vsdx page 1 1600x900 image/png ONLY" in t
    assert "the parse covers every page of this workbook" in t
    assert "SAME diagram page" not in t


def test_local_vsdx_path_renders_locally_when_the_host_can():
    """Dev inputs by PATH never touch the gateway: the same render runs in-process, if available,
    and returns the same (bytes, media_type, label) triple the governed tool does."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h, patch.object(
            W.I, "render_page", lambda src: (b"png-bytes", "image/png", "clinic.vsdx page Ward 800x600 image/png")):
        run(h, {"diagram": "diagrams/clinic.vsdx#Ward", "requirements": []})
    msg = h.agents.runs_of("ba-agent")[0]
    assert [c.media_type for c in data_contents(msg)] == ["image/png"]
    assert "ATTACHED IMAGE of the SAME diagram page" in text_of(msg)
    assert h.router.called("storage_render_vsdx") == []


def test_local_vsdx_path_without_libreoffice_stays_structure_only():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})

    def no_libreoffice(src):
        raise RuntimeError("LibreOffice (soffice) not found")

    with harness(agents) as h, patch.object(W.I, "render_page", no_libreoffice):
        run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})
    msg = h.agents.runs_of("ba-agent")[0]
    assert data_contents(msg) == [] and "No rendered image" in text_of(msg)


def test_the_reason_there_is_no_image_is_recorded_not_swallowed():
    """"no LibreOffice on the host", "the tool is not granted / the gateway was not restarted" and
    "the gateway flattened the image" are three different problems; each must be identifiable after
    the run, and none of them may fail it."""
    cases = {
        "no host capability": (RuntimeError("this storage-mcp host cannot render Visio: LibreOffice ..."),
                               "cannot render Visio"),
        "no grant":           (RuntimeError("tool *storage_render_vsdx not exposed by gateway (['x'])"),
                               "not exposed by gateway"),
    }
    for label, (err, fragment) in cases.items():
        agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
        with harness(agents, {"storage_render_vsdx": err}) as h:
            out = run(h, {"diagram": "art://d1/clinic.vsdx", "requirements": []})
        assert out["status"] == "pending", label            # never fails the run
        assert fragment in h.spans["ba"]["ba.render_error"], label
        assert h.spans["ba"]["ba.rendered"] is False, label
    # a gateway that dropped the image blocks is its own, distinguishable case
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"storage_render_vsdx": FakeResult(content=[text_block("flattened")])}) as h:
        run(h, {"diagram": "art://d1/clinic.vsdx", "requirements": []})
    assert "no image content" in h.spans["ba"]["ba.render_error"]


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
        with harness(agents, {"ea_search": cands}) as h:
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
    with harness(agents, {"ea_search": [{"id": "{1}", "name": "Portal"}]}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["decision"] == "UPDATE" and s["domain"] == "Ops" and s["base_model"] is None
    assert s["resolve_rationale"] is None and s["matched_existing"] == 0
    assert "Decision: UPDATE in domain 'Ops'" in h.agents.runs_of("architect-agent")[0]   # UPDATE alone triggers the block
    assert all(e["folder"] == "Ops" for e in out["spec"]["elements"])


def test_search_failure_marks_new_as_unverified():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"ea_search": ConnectionError("gateway down")}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["decision"] == "NEW" and s["search_failed"] is True
    assert "EA repository search FAILED (ConnectionError: gateway down) — NEW is UNVERIFIED" in s["resolve_rationale"]
    assert "resolve-agent" not in [a.name for a in h.agents.made]


def test_search_tool_not_granted_is_a_failed_search():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"ea_search": None}) as h:
        out = run(h, "diagrams/x.vsdx")
    s = out["summary"]
    assert s["search_failed"] is True and "ea_search not exposed to this identity" in s["resolve_rationale"]


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
        ("ea_mcp-archimate_render", json.dumps({"xml_ref": "art://agent/x.xml", "views": {}})),
        ("semantic_mcp-semantic_validate_model", "not-json-at-all")])]})
    with harness(agents) as h:
        out = run(h, "diagrams/x.vsdx")
    assert len(h.router.called("semantic_validate_model")) == 1 and h.router.called("archimate_render") == []
    assert out["xml_ref"] == "art://agent/x.xml" and out["svg_refs"] == {} and out["summary"]["views"] == 0

    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, tool_call_response("done", [
        ("ea_mcp-archimate_render", {"error": "render failed"})])]})
    # A tool the workload needs is NOT exposed (a missing grant, or the gateway running a different
    # version). This used to surface at the stage_import node — minutes and a whole BA turn later.
    # preflight refuses it before any node runs: no agent call, no tokens, and the message says why.
    with harness(agents, {"ea_stage_import": None}) as h:
        try:
            run(h, "diagrams/x.vsdx")
        except RuntimeError as e:
            assert "gateway does not expose ['ea_stage_import']" in str(e)
            assert "different versions" in str(e) or "grant" in str(e)
        else:
            raise AssertionError("expected the missing tool to fail the run")
    assert h.router.called("archimate_render") == [] and h.agents.runs_of("ba-agent") == []
    assert h.runlog.nodes == [], "no node may run when the contract cannot be satisfied"


def test_stage_import_keeps_the_rendered_refs_when_the_repository_returns_no_artifacts():
    """A write-capable EA tool writes over its own API after the approval and produces NO import
    artifacts. The run output must still carry what WE rendered — and an EMPTY import list."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, {"ea_stage_import": {"request_id": "req-9", "status": "pending",
                                              "artifacts": {}, "instructions": "written on approval"}}) as h:
        out = run(h, "diagrams/x.vsdx")
    assert out["request_id"] == "req-9" and out["review_app"] is None
    assert out["xml_ref"] == "art://x/visio-import.archimate.xml"
    assert out["svg_refs"] == {"landscape": "art://x/a.svg", "detail": "art://x/b.svg"}
    assert out["import_artifacts"] == []


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
    async def _ok(cfg):                      # preflight is covered by test_preflight.py
        return None
    with patch.object(W, "build_workflow", lambda cfg: NoOutput()), patch.object(W, "preflight", _ok):
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


# ------------------------------------------------------------------ per-element provenance
def _elements(obj):
    return [e for k in ("actors", "components", "data", "behaviors") for e in obj.get(k, [])]


def test_provenance_shorthand_is_normalised_to_the_object_form_before_the_architect_sees_it():
    """Every element reaches the Architect (and the persisted ba_output artifact) with the SAME
    provenance shape — the bare-string shorthand is expanded, the object form is left alone."""
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h:
        run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})
    stored, _ = h.router.called("semantic_store_spec")
    prov = {e["name"]: e["provenance"] for e in _elements(stored["spec"])}
    # the shorthand is expanded with the ONE source that representation can have come from
    assert prov == {"Clinician": {"source": "diagram", "representation": "structure"},
                    "Portal": {"source": "diagram", "representation": "structure"},
                    "Patient Record": {"source": "document", "representation": "document"}}
    assert BA_OK["actors"][0]["provenance"] == "structure"          # the fixture itself is untouched


def test_the_gate_rejects_an_element_with_no_provenance_and_retries_the_ba():
    """Absent -> named with the element, so the retry can act on it. (`provenance` is also in the
    schema's element.required — one home for the rule — but the gate's message is the usable one.)"""
    missing = json.loads(json.dumps(BA_OK))
    del missing["components"][0]["provenance"]
    agents = Agents(**{"ba-agent": [missing, BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h:
        run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})
    note = text_of(h.agents.runs_of("ba-agent")[1])
    assert "1 element(s) have no valid provenance: Portal (provenance is required" in note
    from jsonschema import Draft7Validator
    assert "'provenance' is a required property" in W._schema_errors(Draft7Validator(SCHEMA), missing)


def test_a_malformed_provenance_is_named_with_its_element_and_its_precise_reason():
    """Shaped-but-wrong -> the gate names the ELEMENT and the exact reason, so the retry can fix the
    actual mistake instead of guessing at a category."""
    wrong = json.loads(json.dumps(BA_OK))
    wrong["components"][0]["provenance"] = {"source": "visio", "representation": "structure"}
    agents = Agents(**{"ba-agent": [wrong, BA_OK], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents) as h:
        run(h, {"diagram": "diagrams/clinic.vsdx", "requirements": []})
    note = text_of(h.agents.runs_of("ba-agent")[1])
    assert "1 element(s) have no valid provenance: Portal (provenance.source 'visio' is not one of" in note


def test_a_half_filled_provenance_object_is_a_schema_error():
    from jsonschema import Draft7Validator
    half = json.loads(json.dumps(BA_OK))
    half["components"][0]["provenance"] = {"source": "diagram"}      # representation missing
    err = W._schema_errors(Draft7Validator(SCHEMA), half)
    assert err and "provenance" in err
