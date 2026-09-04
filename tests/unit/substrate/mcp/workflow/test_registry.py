"""src/lab/platform/contracts.py — the PROCESS REGISTRY half of the contract: `ProcessSpec` (a business
process declared once: address, prose, typed input contract, published outputs), `InputField.coerce`
(the ONE input validator every surface shares) and `WorkflowTools`, whose tool names are DERIVED from
the registry so registering a process is one entry, not a code change.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/workflow/test_registry.py"""
import pytest

from lab.platform import contracts as C
from lab.substrate.mcp.workflow.server import ANNOTATION
from lab.platform import workflows
from lab.platform.contracts import (PROCESSES, VISIO_TO_ARCHIMATE, ApprovalTools, InputField,
                                    InputKind, ProcessSpec, WorkflowTools)

FAKE = ProcessSpec(
    name="fake_process", group="wf-fake", title="Fake", description="A process used only by tests.",
    inputs=(InputField("primary", InputKind.REF, "the one required ref"),
            InputField("extras", InputKind.REF_LIST, "more refs", required=False),
            InputField("optional_one", InputKind.REF, "an optional single ref", required=False)),
    outputs=("xml_ref",))


# ------------------------------------------------------------------ the catalogue is derived
def test_workflow_catalogue_is_generated_three_tools_per_registered_process():
    assert WorkflowTools.SERVER == "workflow_mcp" and WorkflowTools.VERBS == ("submit", "status", "result")
    generated = WorkflowTools.names() - ApprovalTools.names()    # the fixed approval gate rides along
    assert generated == {f"{p}_{v}" for p in PROCESSES for v in WorkflowTools.VERBS}
    assert len(generated) == 3 * len(PROCESSES)
    assert "visio_to_archimate_submit" in WorkflowTools.names()
    assert "workflow_mcp" not in WorkflowTools.names()          # SERVER is the alias, not a tool


def test_the_approval_gate_is_a_second_catalogue_on_the_same_alias_with_three_grants():
    """A run PAUSES for a human, so the approval tools sit on workflow-mcp — but READ, RAISE and the
    human-gated WRITE are separate GRANTS (`mcp_tool_permissions`), never one blanket permission.

    RAISE is the third: a workload cannot import the substrate, so asking a person a question has to
    be a governed tool. A workload gets RAISE and never WRITE — it may ask, never answer its own
    question, which is the entire control."""
    assert ApprovalTools.SERVER == WorkflowTools.SERVER
    assert ApprovalTools.names() == {"approvals_list", "approvals_get", "approvals_ask",
                                     "approvals_decide"}
    assert ApprovalTools.names() < WorkflowTools.names()         # reachable under the one alias
    grants = (set(ApprovalTools.READ), set(ApprovalTools.RAISE), set(ApprovalTools.WRITE))
    assert set.union(*grants) == ApprovalTools.names()           # every tool belongs to a grant
    assert all(a & b == set() for i, a in enumerate(grants) for b in grants[i + 1:]), \
        "grants must be disjoint, or granting one quietly grants another"
    assert ApprovalTools.RAISE == (ApprovalTools.ask,)           # asking is not answering
    assert ApprovalTools.WRITE == (ApprovalTools.decide,)        # exactly one tool writes a decision
    assert C.SERVERS.get("approvals_mcp") is None                # NOT a server of its own
    assert ApprovalTools.gateway(ApprovalTools.decide) == "workflow_mcp-approvals_decide"


def test_workflow_tools_join_the_server_registry_and_the_gateway_naming():
    assert C.SERVERS["workflow_mcp"] is WorkflowTools
    assert WorkflowTools.names() <= C.ALL_TOOLS
    assert WorkflowTools.gateway("visio_to_archimate_status") == "workflow_mcp-visio_to_archimate_status"
    with pytest.raises(ValueError, match="not a workflow_mcp tool"):
        WorkflowTools.gateway("storage_get")
    every = [n for cls in C.SERVERS.values() for n in cls.names()]
    assert len(every) == len(set(every)), "tool names must be globally unique across servers"


def test_process_spec_tool_names_and_field_lookup():
    assert VISIO_TO_ARCHIMATE.tool("submit") == "visio_to_archimate_submit"
    with pytest.raises(ValueError, match="not one of"):
        VISIO_TO_ARCHIMATE.tool("cancel")
    assert VISIO_TO_ARCHIMATE.field("diagram").kind is InputKind.REF
    assert VISIO_TO_ARCHIMATE.field("requirements").required is False
    with pytest.raises(ValueError, match="no input 'nope'"):
        VISIO_TO_ARCHIMATE.field("nope")


def test_every_registered_process_has_a_consumer_group_that_actually_consumes():
    """A process whose group is not in workflows.GROUPS would accept submissions no host ever reads."""
    assert {p.group for p in PROCESSES.values()} <= set(workflows.GROUPS)
    assert VISIO_TO_ARCHIMATE.group == "wf-visio" and VISIO_TO_ARCHIMATE.name == "visio_to_archimate"
    for spec in PROCESSES.values():                      # every spec is usable as a tool surface
        assert spec.title and spec.description and spec.inputs and spec.outputs
        assert all(f.description for f in spec.inputs)


# ------------------------------------------------------------------ the input contract
def test_validate_accepts_refs_paths_and_page_fragments():
    assert VISIO_TO_ARCHIMATE.validate({"diagram": "art://3f2a/malaffi.vsdx#Shafafiya"}) == \
        {"diagram": "art://3f2a/malaffi.vsdx#Shafafiya", "requirements": []}
    out = VISIO_TO_ARCHIMATE.validate({"diagram": " art://a/b.vsdx ",
                                       "requirements": ["art://c/d.docx", " art://e/f.pdf "]})
    assert out == {"diagram": "art://a/b.vsdx", "requirements": ["art://c/d.docx", "art://e/f.pdf"]}
    assert VISIO_TO_ARCHIMATE.validate({"diagram": "/tmp/local.vsdx"})["diagram"] == "/tmp/local.vsdx"
    assert VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "requirements": None})["requirements"] == []


def test_validate_rejects_bad_input():
    with pytest.raises(ValueError, match="diagram is required"):
        VISIO_TO_ARCHIMATE.validate({})
    with pytest.raises(ValueError, match="diagram must be a non-empty reference"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "   "})       # whitespace is not a reference
    with pytest.raises(ValueError, match="malformed artifact ref"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://onlyid"})
    with pytest.raises(ValueError, match="is not an art:// reference"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "https://example.com/d.vsdx"})
    with pytest.raises(ValueError, match="requirements must be a list"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "requirements": "art://c/d.docx"})
    with pytest.raises(ValueError, match="requirements must be a list"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "requirements": {"a": 1}})
    with pytest.raises(ValueError, match="requirements must be a non-empty reference"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "requirements": [""]})
    with pytest.raises(ValueError, match="requirements must be a non-empty reference"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "requirements": [7]})
    with pytest.raises(ValueError, match=r"unknown input\(s\) \['page'\]"):
        VISIO_TO_ARCHIMATE.validate({"diagram": "art://a/b.vsdx", "page": "P1"})


def test_optional_fields_of_a_second_process_shape():
    """The registry is open for extension: a spec with a different field mix validates the same way."""
    assert FAKE.validate({"primary": "art://a/b.png"}) == {"primary": "art://a/b.png", "extras": []}
    assert "optional_one" not in FAKE.validate({"primary": "art://a/b.png"})   # absent optional REF is omitted
    assert FAKE.validate({"primary": "art://a/b.png", "optional_one": "art://c/d.png",
                          "extras": ["art://e/f.png"]}) == {
        "primary": "art://a/b.png", "extras": ["art://e/f.png"], "optional_one": "art://c/d.png"}
    with pytest.raises(ValueError, match="primary is required"):
        FAKE.validate({"extras": []})
    assert FAKE.tool("result") == "fake_process_result"


def test_input_field_coerce_is_the_one_validator():
    f = InputField("d", InputKind.REF, "x")
    assert f.coerce("art://a/b.vsdx") == "art://a/b.vsdx"
    assert InputField("d", InputKind.REF, "x", required=False).coerce(None) is None
    assert InputField("r", InputKind.REF_LIST, "x", required=False).coerce([]) == []
    # The kinds are pinned deliberately: adding one changes every generated tool schema, so it is a
    # decision rather than a drift. REF/REF_LIST carry content by reference; HANDLE, IDENTITY and
    # MAPPING exist so a low-code trigger can start a run in ONE call and a human's answer can reach
    # the run that needs it. Each must also have an ANNOTATION below, or the schema generator raises.
    assert list(InputKind) == [InputKind.REF, InputKind.REF_LIST, InputKind.HANDLE,
                               InputKind.IDENTITY, InputKind.MAPPING]
    assert set(ANNOTATION) == set(InputKind), "every kind needs a generated-schema annotation"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
