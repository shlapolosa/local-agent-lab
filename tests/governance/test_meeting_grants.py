"""The grants for the meeting pipeline ARE the design, so they are asserted, not just written down.

Two of them are the whole human-in-the-loop control, and both are the kind of thing that gets
widened by accident a year later — a server-level grant added "to unblock something", and nobody
notices it also handed over the ability to answer. An over-broad grant has already bitten this lab
once, which is why `mcp_tool_permissions` exists at all.

Offline: reads the provisioning script's grant tables. No tenant, no gateway.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/governance/test_meeting_grants.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

from lab.platform.contracts import (ALL_TOOLS, ApprovalTools, MEETING_TO_TRANSCRIPT,  # noqa: E402
                                    TRANSCRIPT_TO_MINUTES, WorkflowTools)
import provision_meeting_agents as P  # noqa: E402

GRANTS = {"meeting-transcript": P.TRANSCRIPT_TOOLS, "meeting-minutes": P.MINUTES_TOOLS,
          "power-automate": P.CONNECTOR_TOOLS}


def _all(grant) -> set[str]:
    return {t for tools in grant.values() for t in tools}


@pytest.mark.parametrize("name,grant", GRANTS.items())
def test_every_granted_tool_actually_exists(name, grant):
    """A typo grants nothing, and a key with no grant sees ZERO tools — which looks exactly like a
    broken server. Spelling them from the contract is what turns that into a build failure."""
    unknown = sorted(_all(grant) - ALL_TOOLS)
    assert not unknown, f"{name} grants tools that do not exist: {unknown}"


@pytest.mark.parametrize("name,grant", GRANTS.items())
def test_every_grant_is_per_tool_never_a_whole_server(name, grant):
    """A server-level grant hands over every tool on it, including any added later."""
    assert all(tools for tools in grant.values()), f"{name} has an empty (server-wide) grant"


# ------------------------------------------------------------------ the two that are the control
def test_a_workload_may_ask_a_human_but_never_answer():
    """The entire gate. An agent approving its own run defeats it, so RAISE and WRITE are separate
    grants and the workload holds only the first."""
    granted = P.TRANSCRIPT_TOOLS[WorkflowTools.SERVER]
    assert ApprovalTools.ask in granted
    assert ApprovalTools.decide not in granted
    assert not set(granted) & set(ApprovalTools.WRITE)


def test_the_minutes_workload_neither_asks_nor_answers():
    """It is started by the continuation runner and has no business with the gate at all."""
    assert WorkflowTools.SERVER not in P.MINUTES_TOOLS


def test_the_connector_may_relay_an_answer_but_not_start_the_minutes_run():
    """A human starting transcript_to_minutes directly would bypass the speaker mapping entirely —
    the transcript would be attributed by nobody."""
    granted = set(P.CONNECTOR_TOOLS[WorkflowTools.SERVER])
    assert ApprovalTools.decide in granted, "it must be able to relay a signed-in person's answer"
    assert TRANSCRIPT_TO_MINUTES.tool("submit") not in granted
    assert MEETING_TO_TRANSCRIPT.tool("submit") in granted, "but it does start the pipeline"


def test_the_connector_cannot_ask_a_question_of_its_own():
    """Asking is a workload's step. A low-code flow inventing approvals would put questions in front
    of people that no run is waiting on."""
    assert ApprovalTools.ask not in set(P.CONNECTOR_TOOLS[WorkflowTools.SERVER])


# ------------------------------------------------------------------ least privilege
def test_neither_workload_can_reach_the_others_capabilities():
    """The transcription side holds the collaboration and speech credentials' reach; the minutes
    side holds the semantic write. Neither needs the other's, and swapping them would let one
    process do the whole thing unobserved."""
    transcript, minutes = set(P.TRANSCRIPT_TOOLS), set(P.MINUTES_TOOLS)
    assert "semantic_mcp" not in transcript and "speech_mcp" not in minutes
    assert "collab_mcp" not in minutes


def test_no_grant_includes_the_collaboration_subscription_writes():
    """A subscription is egress to a caller-supplied URL and a durable object that outlives the run.
    It must never reach a workload's own agents."""
    from lab.platform.contracts import CollabTools
    for name, grant in GRANTS.items():
        assert not set(grant.get(CollabTools.SERVER, [])) & set(CollabTools.WRITE), name


if __name__ == "__main__":
    import sys as _s
    _s.exit(pytest.main([__file__, "-q"]))
