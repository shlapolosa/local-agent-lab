"""The fabric's grants ARE the design, so they are asserted against what the workloads actually call.

Preflight checks that the GATEWAY exposes a tool; nothing checked that the workload's IDENTITY is granted
it — so a publish host authenticating with an intake key was refused at preflight and no test could see
it. This reads both sides from source: every `REQUIRED_TOOLS` entry of a fabric workload must be granted to
the team its host authenticates as, PROMOTE must reach no workload, and only the intake may ask.

Offline: reads the provisioning script's grant tables. No tenant, no gateway.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from lab.platform.contracts import ALL_TOOLS, PROCESSES, PRODUCING_PROCESSES, ApprovalTools, SemanticTools, WorkflowTools  # noqa: E402
from lab.workloads.artifact_intake import host as intake_host  # noqa: E402
from lab.workloads.artifact_intake import workflow as intake  # noqa: E402
from lab.workloads.artifact_publish import host as publish_host  # noqa: E402
from lab.workloads.artifact_publish import workflow as publish  # noqa: E402
import provision_fabric_agents as P  # noqa: E402

GRANTS = {"fabric-intake": P.INTAKE_TOOLS, "fabric-publish": P.PUBLISH_TOOLS, "fabric-curator": P.CURATOR_TOOLS}
#: which team each host's identity belongs to (the script mints the key on that team)
TEAM_OF = {intake_host.CLASSIFIER_PREFIX: "fabric-intake", intake_host.SYNTHESIS_PREFIX: "fabric-intake",
           publish_host.AGENT_PREFIX: "fabric-publish"}


def _all(grant) -> set[str]:
    return {t for tools in grant.values() for t in tools}


def _needed(module) -> set[str]:
    return {r if isinstance(r, str) else r[0] for r in module.REQUIRED_TOOLS}


@pytest.mark.parametrize("name,grant", GRANTS.items())
def test_every_granted_tool_exists_and_no_grant_is_a_whole_server(name, grant):
    assert not sorted(_all(grant) - ALL_TOOLS), f"{name} grants tools that do not exist"
    assert all(tools for tools in grant.values()), f"{name} has an empty (server-wide) grant"


@pytest.mark.parametrize("module,prefix", [(intake, intake_host.CLASSIFIER_PREFIX), (publish, publish_host.AGENT_PREFIX)])
def test_every_tool_a_workload_requires_is_granted_to_the_identity_its_host_uses(module, prefix):
    """The defect this exists for: a host whose identity is on the wrong team passes every unit test and
    dies at preflight on the first live run."""
    granted = _all(GRANTS[TEAM_OF[prefix]])
    missing = sorted(_needed(module) - granted)
    assert not missing, f"{module.PROCESS} ({prefix}) requires ungranted tools: {missing}"


def test_promote_reaches_no_workload_and_the_curator_holds_it():
    for name in ("fabric-intake", "fabric-publish"):
        assert SemanticTools.promote not in _all(GRANTS[name]), name
    assert SemanticTools.promote in _all(GRANTS["fabric-curator"])
    assert set(GRANTS["fabric-curator"][SemanticTools.SERVER]) == set(SemanticTools.WRITE) | set(SemanticTools.READ)


def test_the_intake_may_ask_and_the_publish_may_only_read_the_gate():
    assert set(P.INTAKE_TOOLS[WorkflowTools.SERVER]) <= set(ApprovalTools.RAISE)
    assert set(P.PUBLISH_TOOLS[WorkflowTools.SERVER]) <= set(ApprovalTools.READ)
    for grant in GRANTS.values():
        assert ApprovalTools.decide not in _all(grant)


def test_the_substrate_identity_can_list_and_put_but_never_subscribe():
    """The projector writes pages and the reconciler lists drives with the curator key; neither may create a
    subscription (egress to a caller-supplied URL) — that stays with an operator holding the master key."""
    from lab.platform.contracts import CollabTools
    granted = set(GRANTS["fabric-curator"][CollabTools.SERVER])
    assert {CollabTools.list, CollabTools.item, CollabTools.put} <= granted
    assert not granted & set(CollabTools.SUBSCRIBE)


def test_the_intake_holds_no_collaboration_write():
    """Drafts are lab artifacts until a person approves them; the only content write the fabric makes is
    the projector's, with the curator key."""
    from lab.platform.contracts import CollabTools
    assert not set(P.INTAKE_TOOLS[CollabTools.SERVER]) & set(CollabTools.WRITE)


def test_the_producing_processes_are_every_process_but_the_fabrics_own():
    assert set(PRODUCING_PROCESSES) == set(PROCESSES) - {intake.PROCESS, publish.PROCESS}
