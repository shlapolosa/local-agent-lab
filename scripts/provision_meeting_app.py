"""Provision the identity of the opt-in Teams meeting app — and nothing it does not use.

ONE Entra app, and it must be the same app for all of these:
  * the BOT's identity (Azure Bot's msaAppId — what Bot Framework authenticates);
  * the RSC principal (the manifest's `webApplicationInfo.id`) — the meeting-scoped Graph grants an
    organiser gives by ADDING the app to a meeting; graph-mcp uses it to PROVE that opt-in;
  * the Teams SSO resource — the manifest's `webApplicationInfo.resource`, `api://<host>/<appId>`.
    Teams silently fetches a token for it whenever the app is added; without an identifier URI, an
    exposed scope and the two Teams clients pre-authorised, the add fails with a generic error
    (measured 6 Oct 2026). The tab uses the same token to know who is viewing.

Deliberately NOT: front-door `/api` roles, a LiteLLM team or a virtual key. The app is a substrate
service that records decisions and starts runs in-process, so it calls no gateway route.

Idempotent by display name (reuses the app, adds a fresh secret only with --new-secret), and
environment-aware like the other provisioning scripts (`LAB_IDENTITY_SUFFIX=-prod LAB_ENV_FILE=.env.azure`).
Writes MEETING_APP_ID (and MEETING_APP_SECRET when minted); prints key NAMES only.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_meeting_app.py <public host> [--new-secret]
"""
import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

NAME = "lab-meeting-app"
# Microsoft's own Teams clients — the apps that request the SSO token on the user's behalf.
TEAMS_CLIENTS = ("1fec8e78-bce4-4aaf-ab1b-5451cc387264",   # Teams desktop and mobile
                 "5e3ce6c0-2b1f-4285-8d4b-75ee78787346")   # Teams on the web


def sso(app: dict, host: str) -> dict:
    """The PATCH that makes Teams SSO work for this app — pure, so the shape is reviewable."""
    app_id = app["appId"]
    scopes = (app.get("api") or {}).get("oauth2PermissionScopes") or []
    scope = next((s for s in scopes if s["value"] == "access_as_user"), None) or {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{app_id}/access_as_user")), "value": "access_as_user",
        "type": "User", "isEnabled": True,
        "adminConsentDisplayName": "Use Meeting Notes as the signed-in user",
        "adminConsentDescription": "Lets Teams sign the user in to Meeting Notes (tab single sign-on).",
        "userConsentDisplayName": "Use Meeting Notes as you",
        "userConsentDescription": "Lets Teams sign you in to Meeting Notes."}
    return {"identifierUris": sorted(set(app.get("identifierUris") or []) | {f"api://{host}/{app_id}"}),
            "api": {"requestedAccessTokenVersion": 2,
                    "oauth2PermissionScopes": [s for s in scopes if s["value"] != "access_as_user"] + [scope],
                    "preAuthorizedApplications": [{"appId": c, "delegatedPermissionIds": [scope["id"]]}
                                                  for c in TEAMS_CLIENTS]}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host", help="the meeting app's public host, e.g. meeting-app-production-4b82.up.railway.app")
    ap.add_argument("--new-secret", action="store_true")
    a = ap.parse_args()
    from provision_visio_agents import _patch_env, app_name, ensure_sp, find_app, graph
    app = find_app(NAME) or graph("POST", "/applications", {"displayName": app_name(NAME),
                                                             "signInAudience": "AzureADMyOrg"})
    ensure_sp(app["appId"])
    patch = {"MEETING_APP_ID": app["appId"]}
    if a.new_secret:
        patch["MEETING_APP_SECRET"] = graph("POST", f"/applications/{app['id']}/addPassword", {
            "passwordCredential": {"displayName": "lab", "endDateTime": "2027-08-31T00:00:00Z"}})["secretText"]
    # The scope must exist before Teams clients can be pre-authorised for it: two PATCHes, in order.
    body = sso(graph("GET", f"/applications/{app['id']}?$select=appId,identifierUris,api"), a.host)
    graph("PATCH", f"/applications/{app['id']}", {"identifierUris": body["identifierUris"],
                                                  "api": {k: v for k, v in body["api"].items()
                                                          if k != "preAuthorizedApplications"}})
    graph("PATCH", f"/applications/{app['id']}", {"api": {"preAuthorizedApplications":
                                                          body["api"]["preAuthorizedApplications"]}})
    _patch_env(patch)
    print(f"{app_name(NAME)}: SSO resource api://{a.host}/{app['appId']}; .env updated: {', '.join(patch)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
