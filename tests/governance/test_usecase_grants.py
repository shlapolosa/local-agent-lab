"""What the use-case identities may and may not do.

The grants ARE the controls here, not prose about them. CR-20 says no work item or catalog entry is
created before architect approval, and the way that is made true is that no process before
provisioning is granted a write tool — a control expressed as an ACL cannot be reasoned around by a
model, where a control expressed as a branch can be.

Read from the provisioning script's own tables, so a grant that drifts from this file is caught
before it reaches a tenant rather than by a workload failing at its last step.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from lab.platform.contracts import (
    ALL_TOOLS,
    SERVERS,
    ApprovalTools,
    DecisionTools,
    ReferenceTools,
    USE_CASE_DESIGN,
    USE_CASE_INVESTMENT,
    USE_CASE_PROVISIONING,
    USE_CASE_SCREENING,
    VectorStores,
    WorkflowTools,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def provisioning():
    """The grant tables, imported without a tenant. They are declared at module scope precisely so
    they can be read like this."""
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "provision_usecase_agents", ROOT / "scripts" / "provision_usecase_agents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def granted(tables) -> set[str]:
    return {tool for tools in tables.values() for tool in tools}


# ---------------------------------------------------------------- every grant is real and narrow

def test_every_granted_tool_exists(provisioning):
    """A grant naming a tool the server does not expose grants nothing, and looks exactly like a
    broken server from the caller's side."""
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS,
                  provisioning.SUBMITTER_TOOLS):
        unknown = granted(table) - ALL_TOOLS
        assert not unknown, unknown


def test_every_grant_names_a_registered_server(provisioning):
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS,
                  provisioning.SUBMITTER_TOOLS):
        assert set(table) <= set(SERVERS)


def test_no_grant_is_server_wide(provisioning):
    """`mcp_servers` alone grants EVERY tool on a server, including ones added later. The per-tool
    ACL is what keeps a future tool from being granted by a decision nobody took."""
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS,
                  provisioning.SUBMITTER_TOOLS):
        for server, tools in table.items():
            assert tools, f"{server} is granted with no tool list"
            assert set(tools) <= SERVERS[server].names()


# ---------------------------------------------------------------- the gate cannot be self-answered

def test_a_workload_may_ask_a_human_but_never_answer_one(provisioning):
    """An agent approving its own run defeats the entire control. `approvals_decide` requires a
    signed-in person and is a separate grant no workload holds."""
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS):
        tools = set(table.get(WorkflowTools.SERVER, ()))
        assert tools == set(ApprovalTools.RAISE)
        assert not (tools & set(ApprovalTools.WRITE))


def test_no_workload_can_start_a_process_at_all(provisioning):
    """A workload starting a process would let it skip the gate that releases it. Only the
    submitter identity holds a submit tool, and only for the one process that has one."""
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS):
        assert not [t for t in granted(table) if t.endswith("_submit")]


def test_only_the_first_process_can_be_submitted_by_anyone(provisioning):
    submits = [t for t in granted(provisioning.SUBMITTER_TOOLS) if t.endswith("_submit")]
    assert submits == [USE_CASE_SCREENING.tool("submit")]
    for spec in (USE_CASE_DESIGN, USE_CASE_INVESTMENT, USE_CASE_PROVISIONING):
        assert spec.tool("submit") not in granted(provisioning.SUBMITTER_TOOLS)


# ---------------------------------------------------------------- CR-20, as an ACL

def test_the_delivery_identity_holds_no_derivation_tool(provisioning):
    """By the time it runs, every derivation is made and approved. Holding one would let a
    provisioning run recompute what an architect signed off."""
    tools = granted(provisioning.DELIVERY_TOOLS)
    assert not (tools & DecisionTools.names())
    assert not (tools & ReferenceTools.names())


def test_the_intake_identity_holds_no_audit_surface(provisioning):
    """`reference_consumers` spans RUNS — what else consumed this artifact version. That is an audit
    question, not a derivation one, and a workload has no business asking it."""
    tools = granted(provisioning.INTAKE_TOOLS)
    assert set(ReferenceTools.AUDIT).isdisjoint(tools)
    assert set(ReferenceTools.READ) <= tools


def test_the_intake_identity_can_complete_a_derivation(provisioning):
    """A run that could compute its exposure but not its obligations would produce a design package
    with a hole in it — so the derivation catalogue is granted whole or the grant is wrong."""
    assert DecisionTools.names() <= granted(provisioning.INTAKE_TOOLS)


# ---------------------------------------------------------------- the two halves stay apart

def test_neither_identity_holds_the_others_reason_for_existing(provisioning):
    intake = granted(provisioning.INTAKE_TOOLS)
    delivery = granted(provisioning.DELIVERY_TOOLS)
    assert DecisionTools.names() <= intake and not (DecisionTools.names() & delivery)


def test_no_identity_holds_a_collaboration_or_speech_tool(provisioning):
    """Nothing in this pipeline reads a meeting or a recording. A grant that crept in would be a
    capability nobody asked for and nobody would notice."""
    for table in (provisioning.INTAKE_TOOLS, provisioning.DELIVERY_TOOLS,
                  provisioning.SUBMITTER_TOOLS):
        assert "collab_mcp" not in table and "speech_mcp" not in table


# ---------------------------------------------------------------- relevance stores are a grant

def test_a_team_s_store_grant_is_never_left_open(provisioning):
    """LiteLLM reads an absent OR EMPTY `vector_stores` as every store. So the grant is always
    written, and "none" is spelled as a store that does not exist rather than as `[]`."""
    none = provisioning._grants({"reference_mcp": ["reference_pin"]})
    assert none["vector_stores"] and none["vector_stores"] != []
    assert not (set(none["vector_stores"]) & VectorStores.names()), "the sentinel is not a store"
    some = provisioning._grants({}, stores=[VectorStores.CAPABILITY_MAP_HEALTHCARE])
    assert some["vector_stores"] == [VectorStores.CAPABILITY_MAP_HEALTHCARE]


def test_every_store_a_team_is_granted_is_one_the_gateway_registers(provisioning):
    for name in ("INTAKE_STORES", "DELIVERY_STORES", "SUBMITTER_STORES"):
        assert set(getattr(provisioning, name, ())) <= VectorStores.names(), name
