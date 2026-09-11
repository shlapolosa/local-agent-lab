"""Provision identity + governance for the Documentation Fabric's two workloads.

Same operating model as the meeting and visio processes: one LiteLLM team per business process, one
virtual key per agent, each key paired 1:1 with an Entra app registration. The GRANTS are the point:

  wf-fabric (artifact_intake)     semantic_mcp PIPELINE + READ (never PROMOTE) · storage_mcp read_artifact
                                  (the minutes it drafts from) · collab_mcp item (a title) · workflow_mcp
                                  -> approvals_ask ONLY: it asks, it never answers. No collaboration write:
                                  drafts are lab artifacts until a person approves them.
  wf-artifact-publish             its OWN tool-only identity (publish-agent): semantic_mcp PIPELINE + READ ·
                                  collab_mcp item · workflow_mcp approvals READ (the decision that released
                                  it) — never PROMOTE, never decide.
  fabric-curator                  the continuation runner's CHANNEL identity: semantic WRITE (PIPELINE +
                                  PROMOTE) + READ, so a person's answer to a fabric question is applied
                                  as rung-H assertions with the actor the channel authenticated. No model,
                                  no Entra app: a virtual key held by the substrate (`FABRIC_CURATOR_KEY`).

Idempotent: reuses apps found by display name and keys already in .env; teams are RECONCILED, never
merely reused (see provision_meeting_agents._reconcile for why).

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_fabric_agents.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab.platform.contracts import ApprovalTools, CollabTools, SemanticTools, StorageTools, WorkflowTools  # noqa: E402
from provision_meeting_agents import _grants, _key, _reconcile, _team  # noqa: E402


INTAKE_TOOLS = {
    SemanticTools.SERVER: list(SemanticTools.PIPELINE) + list(SemanticTools.READ),   # never PROMOTE
    StorageTools.SERVER: [StorageTools.read_artifact],       # the minutes a synthesis reads, by ref
    CollabTools.SERVER: [CollabTools.item],                  # a title and a version stamp; no write
    WorkflowTools.SERVER: list(ApprovalTools.RAISE),          # ask, never answer
}
PUBLISH_TOOLS = {
    SemanticTools.SERVER: INTAKE_TOOLS[SemanticTools.SERVER],
    CollabTools.SERVER: [CollabTools.item],
    WorkflowTools.SERVER: list(ApprovalTools.READ),           # reads the decision that released it; never decides
}
CURATOR_TOOLS = {
    SemanticTools.SERVER: list(SemanticTools.WRITE) + list(SemanticTools.READ),   # PIPELINE + PROMOTE: a channel
}


def _helpers():
    from provision_visio_agents import ensure_agent, ensure_sp, find_app, litellm, _patch_env
    return ensure_agent, ensure_sp, find_app, litellm, _patch_env


def main() -> int:
    ensure_agent, ensure_sp, find_app, litellm, _patch_env = _helpers()
    gw_app = find_app("lab-gateway")
    if not gw_app:
        raise SystemExit("lab-gateway app not found — run scripts/entra_provision.py first")
    gw_sp = ensure_sp(gw_app["appId"])

    classifier_id, classifier_secret = ensure_agent("classifier-agent", [], gw_sp)
    synthesis_id, synthesis_secret = ensure_agent("synthesis-agent", [], gw_sp)
    publish_id, publish_secret = ensure_agent("publish-agent", [], gw_sp)

    def team(env_key, alias, tools, **kw):
        existing = os.environ.get(env_key)
        return (_reconcile(litellm, existing, alias, tools) if existing
                else _team(litellm, alias, tools, **kw))

    intake_team = team("FABRIC_TEAM_ID", "fabric-intake", INTAKE_TOOLS)
    publish_team = team("FABRIC_PUBLISH_TEAM_ID", "fabric-publish", PUBLISH_TOOLS)
    publish_key = os.environ.get("PUBLISH_AGENT_KEY") or _key(litellm, "publish-agent", publish_team,
                                                                "Fabric publish (tool-only)", models=())
    curator_team = team("FABRIC_CURATOR_TEAM_ID", "fabric-curator", CURATOR_TOOLS, models=())
    curator_key = os.environ.get("FABRIC_CURATOR_KEY") or _key(litellm, "fabric-curator", curator_team,
                                                                "Fabric curator (continuation runner)", models=())

    classifier_key = os.environ.get("CLASSIFIER_AGENT_KEY") or _key(litellm, "classifier-agent", intake_team, "Fabric classification")
    synthesis_key = os.environ.get("SYNTHESIS_AGENT_KEY") or _key(litellm, "synthesis-agent", intake_team, "Fabric decision-record synthesis")

    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    mapping[classifier_id] = classifier_key
    mapping[synthesis_id] = synthesis_key
    mapping[publish_id] = publish_key
    patch = {
        "CLASSIFIER_AGENT_CLIENT_ID": classifier_id, "CLASSIFIER_AGENT_CLIENT_SECRET": classifier_secret,
        "CLASSIFIER_AGENT_KEY": classifier_key, "FABRIC_TEAM_ID": intake_team,
        "SYNTHESIS_AGENT_CLIENT_ID": synthesis_id, "SYNTHESIS_AGENT_CLIENT_SECRET": synthesis_secret,
        "SYNTHESIS_AGENT_KEY": synthesis_key, "FABRIC_PUBLISH_TEAM_ID": publish_team,
        "PUBLISH_AGENT_CLIENT_ID": publish_id, "PUBLISH_AGENT_CLIENT_SECRET": publish_secret,
        "PUBLISH_AGENT_KEY": publish_key,
        "FABRIC_CURATOR_TEAM_ID": curator_team, "FABRIC_CURATOR_KEY": curator_key,
        "ENTRA_CLIENT_TO_KEY": "'" + json.dumps(mapping) + "'",
    }
    _patch_env(patch)
    print("\n.env updated with:", ", ".join(k for k in patch if "SECRET" not in k and k != "ENTRA_CLIENT_TO_KEY"))
    for name, tools in (("fabric-intake", INTAKE_TOOLS), ("fabric-publish", PUBLISH_TOOLS),
                        ("fabric-curator", CURATOR_TOOLS)):
        print(f"  {name}:")
        for server, allowed in sorted(tools.items()):
            print(f"    {server}: {', '.join(allowed)}")
    print("\nNeither workload may decide an approval or promote an assertion; only a channel with a signed-in person may.")
    print("Restart the gateway via ./lab.sh so custom_auth reloads ENTRA_CLIENT_TO_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
