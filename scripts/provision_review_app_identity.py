"""Give the review app an identity at the gateway, so it reaches the lab through the seam (TO-BE).

The review app used to read Redis, the artifact store and the corpus in-process — a peer of the
service layer. It now calls `/api` and gateway MCP like any other client. That needs:

  1. Its OWN Entra registration, `review-app-api` (REVIEW_API_CLIENT_ID / _SECRET), holding app roles on
     `lab-gateway`: Workflow.Submit (submit, uploads, the run board), Approvals.Read (the queue,
     artifacts), Approvals.Decide (record the signed-in person's answer). NOT the human sign-in
     registration (REVIEW_ENTRA_*): setting that switches the password gate to SSO, so the two stay apart.
     Created once; re-runs reconcile the role assignments and never add a secret.
  2. A virtual key the gateway maps that registration to (ENTRA_CLIENT_TO_KEY): every call is metered
     on a key, and the key's team carries the ONE MCP grant the app needs — reference_mcp, for the
     Submit form's intake groups. No vector stores (sentinel), no other server.

The app RELAYS the signed-in person as `actor`: the human is authenticated by the app and the app by
Entra (user decision 24 Oct 2026). A person calling `/api` directly with their own delegated token is
also accepted when they hold the role — that is the connector's path, not this app's. Idempotent: a team/key already named in .env is reconciled, never reissued.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_review_app_identity.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.platform.contracts import ReferenceTools  # noqa: E402

APP_NAME = "review-app-api"
TEAM_ALIAS = "review-app"
KEY_ALIAS = "review-app"
#: The ONE MCP grant: pin + lookup on the corpus, for the Submit form's intake groups and the roadmap.
#: Collected by deploy/grants.py, so production's APIM renders the same table.
REVIEW_TOOLS = {ReferenceTools.SERVER: [ReferenceTools.pin, ReferenceTools.lookup]}


def main() -> int:
    from lab.platform.contracts import ApiRoles
    from provision_meeting_agents import _grants
    from provision_usecase_agents import NO_STORES
    from provision_visio_agents import _patch_env, ensure_agent, ensure_sp, find_app, graph, litellm, role_id

    gw = find_app("lab-gateway") or sys.exit("lab-gateway does not exist — run scripts/entra_provision.py")
    have = {r["value"] for r in gw.get("appRoles") or []}
    if not set(ApiRoles.ALL) <= have:
        sys.exit("lab-gateway lacks the /api roles — run scripts/provision_connector_identity.py first")
    gw_sp = ensure_sp(gw["appId"])
    roles = (ApiRoles.SUBMIT, ApiRoles.READ, ApiRoles.DECIDE)
    patch = {}
    client_id = os.environ.get("REVIEW_API_CLIENT_ID")
    if not client_id:
        # creates the app, ONE secret, and the role assignments (the visio agents' own helper)
        client_id, secret = ensure_agent(APP_NAME, roles, gw_sp)
        # written NOW: a secret is shown once, and a failure in a later step must not lose it
        _patch_env({"REVIEW_API_CLIENT_ID": client_id, "REVIEW_API_CLIENT_SECRET": secret})
        print(".env patched: ['REVIEW_API_CLIENT_ID', 'REVIEW_API_CLIENT_SECRET']")
    else:
        sp = ensure_sp(client_id)
        granted = {a["appRoleId"] for a in graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignments")["value"]}
        for value in roles:
            if role_id(value) not in granted:
                graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignments",
                      {"principalId": sp["id"], "resourceId": gw_sp["id"], "appRoleId": role_id(value)})
                print(f"granted {value}")

    permission = {**_grants(REVIEW_TOOLS), "vector_stores": list(NO_STORES)}
    team_id = os.environ.get("REVIEW_TEAM_ID")
    if team_id:
        litellm("/team/update", {"team_id": team_id, "models": [], "object_permission": permission})
        print(f"team {TEAM_ALIAS} reconciled ({team_id})")
    else:
        team_id = litellm("/team/new", {"team_alias": TEAM_ALIAS, "max_budget": 1.0, "budget_duration": "30d",
                                        "models": [], "object_permission": permission})["team_id"]
        patch["REVIEW_TEAM_ID"] = team_id
        print(f"team {TEAM_ALIAS} created ({team_id})")

    key = os.environ.get("REVIEW_APP_KEY")
    if not key:
        key = litellm("/key/generate", {"key_alias": KEY_ALIAS, "team_id": team_id, "models": [],
                                        "max_budget": 1.0, "budget_duration": "30d", "rpm_limit": 240,
                                        "metadata": {"role": "review-app", "entra_app": client_id}})["key"]
        patch["REVIEW_APP_KEY"] = key
        print(f"key {KEY_ALIAS} minted")

    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY") or "{}")
    if mapping.get(client_id) != key:
        mapping[client_id] = key
        patch["ENTRA_CLIENT_TO_KEY"] = f"'{json.dumps(mapping)}'"   # single-quoted for .env sourcing
    if patch:
        _patch_env(patch)
        print(f".env patched: {sorted(patch)} — restart the gateway (custom_auth reloads the map) "
              "and re-upload LAB_ENV for the cloud")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
