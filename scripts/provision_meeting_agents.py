"""Provision identity + governance for the two meeting workloads and the Power Automate connector.

The same operating model as the visio process: one LiteLLM team per business process, one virtual
key per agent, each key paired 1:1 with an Entra app registration. What differs is the GRANTS, and
they are the interesting part — each identity gets the least it can do its job with, and the two
that must never overlap are enforced here rather than in prose:

  wf-meeting-transcript   collab_mcp (read + fetch)  · speech_mcp · storage_mcp
                          workflow_mcp -> approvals_ask ONLY. It may ASK a human a question and it
                          may NOT answer one: an agent approving its own run defeats the gate.
  wf-meeting-minutes      storage_mcp · semantic_mcp. NOTHING on workflow_mcp — it neither asks nor
                          answers; it is started by the continuation runner.
  power-automate          the meeting process's submit/status/result, plus approvals list/get/decide
                          so a flow can relay a signed-in person's answer. Deliberately NOT
                          approvals_ask, and deliberately NOT transcript_to_minutes_submit — a human
                          starting the minutes run directly would bypass the speaker-mapping gate.

Creates the Entra apps, the teams with those per-tool ACLs, and the keys; then patches .env with
MEETING_AGENT_*, MINUTES_AGENT_*, the team ids and the appId->key entries. Idempotent: reuses apps
found by display name and keys already recorded in .env.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_meeting_agents.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab.platform.contracts import (ApprovalTools, CollabTools, MEETING_TO_TRANSCRIPT,  # noqa: E402
                                    SemanticTools, SpeechTools, StorageTools, WorkflowTools)


def _helpers():
    """The visio script's Graph + LiteLLM helpers — one place that knows how to mint an app, attach
    a secret and assign an app role. Imported LAZILY because that module reads the environment at
    import, and the GRANT TABLES above must stay readable (and testable) without a tenant."""
    from provision_visio_agents import ensure_agent, ensure_sp, find_app, litellm, _patch_env
    return ensure_agent, ensure_sp, find_app, litellm, _patch_env

# The grants, spelled from the CONTRACT so a renamed tool breaks provisioning rather than silently
# granting nothing (a key with no grant sees zero tools, which looks exactly like a broken server).
TRANSCRIPT_TOOLS = {
    CollabTools.SERVER: [CollabTools.fetch, CollabTools.item, CollabTools.meetings,
                         CollabTools.recordings, CollabTools.capabilities],
    SpeechTools.SERVER: [SpeechTools.transcribe, SpeechTools.capabilities],
    StorageTools.SERVER: [StorageTools.get, StorageTools.info, StorageTools.read_document],
    WorkflowTools.SERVER: list(ApprovalTools.RAISE),      # ask, never answer
}
MINUTES_TOOLS = {
    StorageTools.SERVER: [StorageTools.get, StorageTools.info, StorageTools.read_document],
    SemanticTools.SERVER: [SemanticTools.store_spec, SemanticTools.load_model,
                           SemanticTools.validate_model],
}
CONNECTOR_TOOLS = {
    # `verbs_for`, not VERBS: a continuation-only process has no submit tool, and a grant that named
    # one would name a tool the server does not expose. Nothing to grant is not the same as granting
    # nothing — the first is a typo the gateway cannot report, the second looks like a broken server.
    WorkflowTools.SERVER: [MEETING_TO_TRANSCRIPT.tool(v)
                           for v in WorkflowTools.verbs_for(MEETING_TO_TRANSCRIPT)]
                          + list(ApprovalTools.READ) + list(ApprovalTools.WRITE),
}


def _team(litellm, alias, tools, budget=5.0, models=("kimi-k3", "glm-flash")):
    """One team with a per-tool ACL. `mcp_servers` alone would grant every tool on the server."""
    return litellm("/team/new", {
        "team_alias": alias, "max_budget": budget, "budget_duration": "30d",
        "models": list(models),
        "object_permission": {"mcp_servers": sorted(tools), "mcp_tool_permissions": tools},
    })["team_id"]


def _key(litellm, alias, team_id, role, models=("kimi-k3",)):
    return litellm("/key/generate", {
        "key_alias": alias, "team_id": team_id, "models": list(models),
        "max_budget": 2.0, "budget_duration": "30d", "rpm_limit": 60, "tpm_limit": 240000,
        "metadata": {"role": role, "entra_app_registration": alias},
    })["key"]


def main() -> int:
    ensure_agent, ensure_sp, find_app, litellm, _patch_env = _helpers()
    gw_app = find_app("lab-gateway")
    if not gw_app:
        raise SystemExit("lab-gateway app not found — run scripts/entra_provision.py first")
    gw_sp = ensure_sp(gw_app["appId"])

    # The transcript workload calls no model of its own (every step is deterministic), but it still
    # needs an identity: the gateway authorises TOOLS by key, not just LLM calls.
    meeting_id, meeting_secret = ensure_agent("meeting-agent", [], gw_sp)
    minutes_id, minutes_secret = ensure_agent("minutes-agent", [], gw_sp)

    transcript_team = os.environ.get("MEETING_TEAM_ID") or _team(litellm, "meeting-transcript", TRANSCRIPT_TOOLS)
    minutes_team = os.environ.get("MINUTES_TEAM_ID") or _team(litellm, "meeting-minutes", MINUTES_TOOLS)
    connector_team = os.environ.get("CONNECTOR_TEAM_ID") or _team(litellm, "power-automate", CONNECTOR_TOOLS, budget=1.0, models=())

    meeting_key = os.environ.get("MEETING_AGENT_KEY") or _key(litellm, "meeting-agent", transcript_team, "Meeting transcription")
    minutes_key = os.environ.get("MINUTES_AGENT_KEY") or _key(litellm, "minutes-agent", minutes_team, "Meeting minutes")
    connector_key = os.environ.get("POWER_AUTOMATE_KEY") or _key(litellm, "power-automate", connector_team, "Low-code connector", models=())

    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    mapping[meeting_id] = meeting_key
    mapping[minutes_id] = minutes_key

    patch = {
        "MEETING_AGENT_CLIENT_ID": meeting_id, "MEETING_AGENT_CLIENT_SECRET": meeting_secret,
        "MEETING_AGENT_KEY": meeting_key, "MEETING_TEAM_ID": transcript_team,
        "MINUTES_AGENT_CLIENT_ID": minutes_id, "MINUTES_AGENT_CLIENT_SECRET": minutes_secret,
        "MINUTES_AGENT_KEY": minutes_key, "MINUTES_TEAM_ID": minutes_team,
        "POWER_AUTOMATE_KEY": connector_key, "CONNECTOR_TEAM_ID": connector_team,
        "ENTRA_CLIENT_TO_KEY": "'" + json.dumps(mapping) + "'",
    }
    _patch_env(patch)
    print("\n.env updated with:", ", ".join(k for k in patch if "SECRET" not in k and k != "ENTRA_CLIENT_TO_KEY"))
    print("\nGrants written:")
    for name, tools in (("meeting-transcript", TRANSCRIPT_TOOLS), ("meeting-minutes", MINUTES_TOOLS),
                        ("power-automate", CONNECTOR_TOOLS)):
        print(f"  {name}:")
        for server, allowed in sorted(tools.items()):
            print(f"    {server}: {', '.join(allowed)}")
    print("\nThe connector deliberately has NO approvals_ask and NO transcript_to_minutes_submit:")
    print("  a flow may relay a person's answer, and may not start the minutes run itself.")
    print("Restart the gateway via ./lab.sh so custom_auth reloads ENTRA_CLIENT_TO_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
