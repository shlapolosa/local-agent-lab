"""Provision identity + governance for the architecture_modelling workload (ADR 2026-10-24).

One LiteLLM team, one virtual key paired 1:1 with an Entra app registration. The grant is the least
the workload needs:

  architecture-modelling   storage_mcp: read_document (the documents it models from)
                           semantic_mcp: store_spec (the envelope, by ref)
                           workflow_mcp: approvals_ask ONLY. It may ASK an architect and may NOT
                           answer: an agent approving its own model defeats the gate.

Idempotent: reuses the app found by display name and the team/key recorded in .env, and RECONCILES
both to the table below every time (see `provision_meeting_agents._reconcile` for why).

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_modelling_agents.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab.platform import config                                            # noqa: E402
from lab.platform.contracts import (ApprovalTools, SemanticTools, StorageTools,  # noqa: E402
                                    WorkflowTools)

#: Spelled from the CONTRACT, so a renamed tool breaks provisioning rather than silently granting nothing.
MODELLING_TOOLS = {
    StorageTools.SERVER: [StorageTools.read_document],
    SemanticTools.SERVER: [SemanticTools.store_spec],
    WorkflowTools.SERVER: list(ApprovalTools.RAISE),      # ask, never answer
}

AGENT_MODEL = config.MODELLING_AGENT_MODEL


def main() -> int:
    from provision_meeting_agents import _helpers, _key, _reconcile, _reconcile_key, _team
    ensure_agent, ensure_sp, find_app, litellm, _patch_env = _helpers()
    gw_app = find_app("lab-gateway")
    if not gw_app:
        raise SystemExit("lab-gateway app not found — run scripts/entra_provision.py first")
    gw_sp = ensure_sp(gw_app["appId"])
    app_id, secret = ensure_agent("architecture-modelling-agent", [], gw_sp)

    models = (AGENT_MODEL,)
    existing_team = os.environ.get("MODELLING_TEAM_ID")
    team = (_reconcile(litellm, existing_team, "architecture-modelling", MODELLING_TOOLS, models)
            if existing_team else
            _team(litellm, "architecture-modelling", MODELLING_TOOLS, models=models))
    existing_key = os.environ.get("MODELLING_AGENT_KEY")
    key = (_reconcile_key(litellm, existing_key, models) if existing_key
           else _key(litellm, "architecture-modelling-agent", team, "Architecture modelling",
                     models=models))

    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    mapping[app_id] = key
    patch = {"MODELLING_AGENT_CLIENT_ID": app_id, "MODELLING_AGENT_CLIENT_SECRET": secret,
             "MODELLING_AGENT_KEY": key, "MODELLING_TEAM_ID": team,
             "ENTRA_CLIENT_TO_KEY": "'" + json.dumps(mapping) + "'"}
    _patch_env(patch)
    print("\n.env updated with:", ", ".join(k for k in patch if "SECRET" not in k and k != "ENTRA_CLIENT_TO_KEY"))
    print("\nGrants written (created or reconciled): architecture-modelling")
    for server, allowed in sorted(MODELLING_TOOLS.items()):
        print(f"  {server}: {', '.join(allowed)}")
    print("Restart the gateway via ./lab.sh so custom_auth reloads ENTRA_CLIENT_TO_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
