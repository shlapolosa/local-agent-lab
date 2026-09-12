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

from lab.platform import config                                            # noqa: E402
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
    StorageTools.SERVER: [StorageTools.get, StorageTools.info, StorageTools.read_artifact],
    # Delivery: read ONE item to find the folder it sits in, and write beside it. Never a
    # subscription — CollabTools splits SUBSCRIBE from PUT precisely so a workload can hold the
    # second without the first, and a governance test refuses a grant that mixes them.
    CollabTools.SERVER: [CollabTools.item, CollabTools.put],
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


#: THE model this workload's agents run on, read where it is declared. Every team and key allowlist
#: below follows it, and an EXISTING one is reconciled to it.
AGENT_MODEL = config.MINUTES_AGENT_MODEL


def _grants(tools):
    """The `object_permission` for a per-tool ACL. `mcp_servers` alone would grant EVERY tool on the
    server, so the two travel together."""
    return {"mcp_servers": sorted(tools), "mcp_tool_permissions": tools}


def _team(litellm, alias, tools, budget=5.0, models=(AGENT_MODEL, "gpt-4.1")):
    """One team with a per-tool ACL."""
    return litellm("/team/new", {
        "team_alias": alias, "max_budget": budget, "budget_duration": "30d",
        "models": list(models), "object_permission": _grants(tools),
    })["team_id"]


def _reconcile(litellm, team_id, alias, tools, models=()):
    """Make an EXISTING team's grants AND model allowlist match the table above. Returns the team id.

    Because the tables below are the declaration and this script is what applies them — and it did
    not. `MINUTES_TOOLS` has named `collab_item` and `collab_put` since delivery was written, but the
    team was created before that and the id was in `.env`, so `_team` was never called again and the
    grant was never written. The workload then failed at the last step with `tool *collab_item not
    exposed by gateway`, having produced correct minutes, while this script printed "Grants written"
    and had written nothing.

    Declared once at creation and never reconciled is the same defect the image tag had. A table is
    only the truth if something applies it every time.
    """
    body = {"team_id": team_id, "object_permission": _grants(tools)}
    if models:
        # The models list is the SAME defect one level down, and it cost a second diagnosis on
        # 12 Sep 2026: with the model declaration moved off a capped upstream, a kept team and a kept
        # key both still allowed only the old model, so the host asking for the new one got a 403
        # where it used to get a 429. Empty means "leave it alone" — the connector team deliberately
        # allows no model at all and must not be handed one.
        body["models"] = list(models)
    litellm("/team/update", body)
    return team_id


def _reconcile_key(litellm, key, models):
    """An existing key's model allowlist follows the declaration too. A key kept because its id was
    already in `.env` used to keep the allowlist it was minted with: measured against the deployed
    gateway, the minutes key said `models=['kimi-k3']` long after the declaration had moved."""
    if models:
        litellm("/key/update", {"key": key, "models": list(models)})
    return key


def _key(litellm, alias, team_id, role, models=(AGENT_MODEL,)):
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

    # Every team is RECONCILED when it already exists, never merely reused: the tables above are the
    # declaration and this is what applies them. See `_reconcile` for what reusing them silently cost.
    def team(env_key, alias, tools, models=(AGENT_MODEL, "gpt-4.1"), **kw):
        existing = os.environ.get(env_key)
        return (_reconcile(litellm, existing, alias, tools, models) if existing
                else _team(litellm, alias, tools, models=models, **kw))

    transcript_team = team("MEETING_TEAM_ID", "meeting-transcript", TRANSCRIPT_TOOLS)
    minutes_team = team("MINUTES_TEAM_ID", "meeting-minutes", MINUTES_TOOLS)
    connector_team = team("CONNECTOR_TEAM_ID", "power-automate", CONNECTOR_TOOLS,
                          budget=1.0, models=())

    def key(env_key, alias, team_id, role, models=(AGENT_MODEL,)):
        existing = os.environ.get(env_key)
        return (_reconcile_key(litellm, existing, models) if existing
                else _key(litellm, alias, team_id, role, models=models))

    meeting_key = key("MEETING_AGENT_KEY", "meeting-agent", transcript_team, "Meeting transcription")
    minutes_key = key("MINUTES_AGENT_KEY", "minutes-agent", minutes_team, "Meeting minutes")
    connector_key = key("POWER_AUTOMATE_KEY", "power-automate", connector_team,
                        "Low-code connector", models=())

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
    print("\nGrants written (created or reconciled):")
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
