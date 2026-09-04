"""src/lab/workloads/visio_to_archimate/workflow.py — BA_MODE=tools and ARCHITECT_MODE=tools through the real
graph: the scripted fake agents BUILD their output by calling the accumulator tools the workflow hands
them (ba_tools.make_tools / architect_tools.make_tools), so the document/spec is assembled by code and
must pass the SAME gates as the JSON path; the retry keeps the accumulator (adds, never restarts).
Offline: fakes from tests/unit/workloads/visio_to_archimate/test_workflow_run.py; no gateway, no LLM, no Redis.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_workflow_tools_mode.py   (also pytest-compatible)"""


from lab.workloads.visio_to_archimate import workflow as W
from lab.workloads import ids
from fixtures.workflow import (  # noqa: E402
    BA_OK, SPEC_OK, Agents, FakeResult, harness, image_block, raises, run, text_block, text_of)

# provenance is required per element in BOTH modes; the shorthand is accepted and expanded.
BA_ITEMS = [{"group": "actors", "name": "Clinician", "role": "Reads records", "layer": "Business",
             "aspect": "active", "candidateType": "BusinessActor", "provenance": "structure"},
            {"group": "components", "name": "Portal", "role": "Web front end", "layer": "Application",
             "aspect": "active", "candidateType": "ApplicationComponent",
             "provenance": {"source": "diagram", "representation": "structure"}},
            {"group": "data", "name": "Patient Record", "role": "The clinical record", "layer": "Application",
             "aspect": "passive", "candidateType": "DataObject",
             "provenance": {"source": "document", "representation": "document"}}]
BA_RELS = [{"from": "Portal", "to": "Clinician", "type": "Serving", "intent": "portal serves clinician"},
           {"from": "Portal", "to": "Patient Record", "type": "Access", "intent": "portal reads record"}]


def ba_fill(tools, msg, *, call_finish=True):
    """A BA turn that builds the whole description through the accumulator tools."""
    assert tools["set_system"]("Clinic Portal", "Clinicians use a web portal to read patient records.")["ok"]
    r = tools["add_elements"](BA_ITEMS)
    assert not r["rejected"] and r["total_elements"] == 3, r
    r = tools["add_relationships"](BA_RELS)
    assert not r["rejected"] and r["total_relationships"] == 2, r
    tools["note_questions"](["Is the record store on-prem?"])
    if call_finish:
        assert tools["finish"]()["ok"]
    return "done"


def arch_fill(tools, msg, *, call_finish=True):
    assert tools["set_model"]("Clinic Portal")["ok"]
    r = tools["add_elements"](SPEC_OK["elements"])
    assert not r["rejected"] and r["total_elements"] == 3, r
    r = tools["add_relations"]([{"type": "Serving", "src": "portal", "tgt": "clinician"},
                                {"type": "Access", "src": "portal", "tgt": "patient-record", "accessType": "Read"}])
    assert not r["rejected"] and r["total_relations"] == 2, r
    assert tools["add_view"]("ctx", "Context", ["clinician", "portal"])["ok"]
    if call_finish:
        assert tools["finish"]()["ok"]
    return "done"


def nothing(tools, msg):
    return "done"


# ------------------------------------------------------------------ BA_MODE=tools
def test_ba_tools_mode_builds_the_description_through_the_accumulator():
    agents = Agents(**{"ba-agent": [ba_fill], "architect-agent": [SPEC_OK, "done"]})
    with harness(agents, env={"BA_MODE": "tools"}) as h:
        out = run(h, "diagrams/x.vsdx")
    ba = h.agents.agent("ba-agent")
    assert W.A.ba_tools_addendum().strip() in ba.instructions           # the tools addendum is appended
    assert {"set_system", "add_elements", "add_relationships", "note_questions", "finish", "read_vsdx"} <= set(ba.tools_by_name)
    stored = h.router.called("semantic_store_spec")[0]["spec"]          # what the gate let through
    assert stored["systemName"] == "Clinic Portal" and stored["openQuestions"] == ["Is the record store on-prem?"]
    assert [e["name"] for g in ("actors", "components", "data") for e in stored[g]] == ["Clinician", "Portal", "Patient Record"]
    assert stored["relationships"][0]["from"] == "Portal"
    assert out["summary"]["elements"] == 3 and out["summary"]["ba_output_ref"] == "art://store/visio-import.ba_output.json"


def test_ba_tools_mode_retry_keeps_the_accumulator_and_resends_inputs():
    """First turn adds nothing (and never calls finish -> the node finishes for it); the retry note
    names the gap and re-attaches the diagram; the second turn adds the missing content WITHOUT
    calling finish either, and the document still passes the gate."""
    agents = Agents(**{"ba-agent": [nothing, lambda t, m: ba_fill(t, m, call_finish=False)],
                       "architect-agent": [SPEC_OK, "done"]})
    tools = {"storage_get": FakeResult(content=[image_block(b"img"), text_block("d.png")])}
    with harness(agents, tools, env={"BA_MODE": "tools"}) as h:
        out = run(h, "art://d/diagram.png")
    first, retry = h.agents.runs_of("ba-agent")
    note = text_of(retry)
    assert "Your description is incomplete:" in note and "add_elements / add_relationships" in note
    assert "systemName" in note                                           # the gate's actual complaint
    assert retry.contents[0].uri == first.contents[0].uri                 # diagram image re-sent
    ba = h.agents.agent("ba-agent")
    assert ba.tools[0].name == "storage" and "add_elements" in ba.tools_by_name   # storage MCP + accumulator tools
    assert out["summary"]["elements"] == 3


def test_ba_tools_mode_rejected_after_retry_raises():
    agents = Agents(**{"ba-agent": [nothing, nothing]})
    with harness(agents, env={"BA_MODE": "Tools "}) as h:              # env value is normalised
        raises(h, "diagrams/x.vsdx", RuntimeError, "BA output rejected (incomplete after retry)")
    assert h.router.called("semantic_store_spec") == []


# ------------------------------------------------------------------ ARCHITECT_MODE=tools
def test_architect_tools_mode_builds_a_legal_spec_by_construction():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [arch_fill, "done"]})
    with harness(agents, env={"ARCHITECT_MODE": "tools"}) as h:
        out = run(h, "diagrams/x.vsdx")
    design_agent = h.agents.agent("architect-agent")
    assert W.A.architect_tools_addendum().strip() in design_agent.instructions
    assert {"set_model", "add_elements", "add_relations", "add_view", "finish"} == set(design_agent.tools_by_name)
    spec, s = out["spec"], out["summary"]
    assert spec["name"] == "Clinic Portal" and spec["id"] == "clinic-portal" and spec["standard_views"] is True
    assert [e["id"] for e in spec["elements"]] == ["clinician", "portal", "patient-record"]
    assert all(e["folder"] == "Clinic Portal" for e in spec["elements"])
    assert [r["id"] for r in spec["relations"]] == [ids.rid(r["src"], r["type"], r["tgt"]) for r in spec["relations"]]
    assert spec["relations"][1]["accessType"] == "Read" and spec["views"][0]["id"] == "ctx"
    assert s["relation_repairs"] == 0 and s["repair_notes"] == []        # legal at emission, nothing to repair
    assert s["elements"] == 3 and s["relations"] == 2
    # the finalize agent is the plain JSON-mode architect (tools = the gateway MCP)
    assert h.agents.made[-1].tools[0].name == "ea-tools"


def test_architect_tools_mode_second_chance_then_failure():
    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [nothing, lambda t, m: arch_fill(t, m, call_finish=False), "done"]})
    with harness(agents, env={"ARCHITECT_MODE": "tools"}) as h:
        out = run(h, "diagrams/x.vsdx")
    prompts = h.agents.runs_of("architect-agent")
    assert "BA system description:" in prompts[0] and prompts[1].startswith("Your model has no elements")
    assert out["summary"]["elements"] == 3

    agents = Agents(**{"ba-agent": [BA_OK], "architect-agent": [nothing, nothing]})
    with harness(agents, env={"ARCHITECT_MODE": "tools"}) as h:
        raises(h, "diagrams/x.vsdx", RuntimeError, "Architect (tools mode) produced no spec")
    assert h.runlog.nodes[-1] == ("run-test", "architect_design", "fail:RuntimeError")
    assert len(h.router.called("semantic_store_spec")) == 1              # BA output stored, spec never


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
