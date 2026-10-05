"""Provision the identity of the opt-in Teams meeting app (docs plan: "the meeting pipeline as an
opt-in Teams meeting app").

ONE Entra app, three jobs, and they must be the SAME app:
  * the BOT's identity (Azure Bot's msaAppId — what Bot Framework authenticates);
  * the RSC principal (the manifest's `webApplicationInfo.id`) — the meeting-scoped Graph grants
    (`OnlineMeetingRecording.Read.Chat`, …) an organiser gives by ADDING the app to a meeting are
    granted to exactly this app id, so graph-mcp reads with its credential and nothing tenant-wide;
  * the CALLER of the front door `/api` — it starts a run and records the organiser's answer, so it
    holds `Workflow.Submit`, `Approvals.Read`, `Approvals.Decide` on lab-gateway, the same three
    powers as the Power Automate connector it replaces, and a virtual key so the call is metered.

Its LiteLLM team carries the connector's grants and NO model: the app decides nothing itself.

Idempotent by display name (reuses the app, adds a fresh secret), and environment-aware exactly like
the other provisioning scripts: `LAB_IDENTITY_SUFFIX=-prod LAB_ENV_FILE=.env.azure` makes the
production twin. Writes MEETING_APP_ID / MEETING_APP_SECRET / MEETING_APP_KEY / MEETING_APP_TEAM_ID
and the ENTRA_CLIENT_TO_KEY entry; prints key NAMES only.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_meeting_app.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab.platform.contracts import ApiRoles                                  # noqa: E402
from provision_meeting_agents import CONNECTOR_TOOLS, _helpers, _key, _reconcile, _team  # noqa: E402

NAME = "lab-meeting-app"
ROLES = (ApiRoles.SUBMIT, ApiRoles.READ, ApiRoles.DECIDE)


def main() -> int:
    ensure_agent, ensure_sp, find_app, litellm, _patch_env = _helpers()
    gw_app = find_app("lab-gateway") or sys.exit("lab-gateway not found — run scripts/entra_provision.py")
    app_id, secret = ensure_agent(NAME, list(ROLES), ensure_sp(gw_app["appId"]))

    team = os.environ.get("MEETING_APP_TEAM_ID")
    team = (_reconcile(litellm, team, "meeting-app", CONNECTOR_TOOLS) if team
            else _team(litellm, "meeting-app", CONNECTOR_TOOLS, budget=1.0, models=()))
    key = os.environ.get("MEETING_APP_KEY") or _key(litellm, "meeting-app", team, "Teams meeting app",
                                                    models=())

    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    mapping[app_id] = key
    patch = {"MEETING_APP_ID": app_id, "MEETING_APP_SECRET": secret, "MEETING_APP_KEY": key,
             "MEETING_APP_TEAM_ID": team, "ENTRA_CLIENT_TO_KEY": "'" + json.dumps(mapping) + "'"}
    _patch_env(patch)
    print(".env updated:", ", ".join(patch))
    print(f"{NAME} holds {', '.join(ROLES)}; team meeting-app holds the connector's tools, no model.")
    print("Restart the gateway so custom_auth reloads ENTRA_CLIENT_TO_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
