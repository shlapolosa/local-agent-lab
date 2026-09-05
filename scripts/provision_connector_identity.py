"""Provision the REST front door's authorisation: the /api app roles on `lab-gateway`, and an app
registration for the Power Automate connector that holds them.

WHY A CONNECTOR NEEDS ITS OWN IDENTITY. A flow watching for a saved meeting recording calls
`POST /api/processes/meeting_to_transcript/runs` and, when the organiser answers, records their
decision. Those are two different powers and the flow should hold exactly them — not a virtual key,
which authenticates but carries no roles and so cannot be authorised per operation at all. The roles
come from `lab.platform.contracts.ApiRoles` and the operation they gate from
`lab.substrate.apipolicy`, so this script cannot invent a role the gateway does not check or miss one
it does.

Roles are ADDED to the gateway app, never replaced: EA.Model and Tools.ADOIT already exist and
PATCHing `appRoles` overwrites the whole collection, which would silently un-grant every agent.

Idempotent by display name, like `entra_provision.py`. Needs var/run/graph_token.json (device-code
sign-in) and ENTRA_TENANT_ID. Prints the .env lines to add — including the ENTRA_CLIENT_TO_KEY entry,
without which the gateway authenticates the connector and then has no virtual key to meter it on.

Usage: .venv/bin/python scripts/provision_connector_identity.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from lab.platform.contracts import ApiRoles                             # noqa: E402
from lab.substrate import apipolicy                                     # noqa: E402

G = "https://graph.microsoft.com/v1.0"
TENANT = os.environ.get("ENTRA_TENANT_ID") or sys.exit("ENTRA_TENANT_ID is not set (source .env)")
CONNECTOR = "power-automate-connector"
GATEWAY = "lab-gateway"
SECRET_EXPIRY = "2027-08-31T00:00:00Z"

# What the connector is granted, and deliberately not more. It may start work and record a human's
# answer; it may NOT raise a question (that is a workload's `approvals_ask`, over MCP). Starting the
# minutes run directly is not on this list either — and could not be, because that refusal is
# `ProcessSpec.external`, which no role can override.
CONNECTOR_ROLES = (ApiRoles.SUBMIT, ApiRoles.READ, ApiRoles.DECIDE)


TOKEN_PATH = "var/run/graph_token.json"
# The Azure CLI's own public client — the device-code sign-in that minted the file used it, so the
# refresh token is bound to it. Same constant as scripts/entra_dev_provision.py.
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
GRAPH_SCOPE = "Application.ReadWrite.All Directory.AccessAsUser.All offline_access"


def _token() -> str:
    """A live Graph access token, refreshed in place. The stored access token lasts about an hour and
    these scripts are run days apart, so reading it without refreshing fails with an expiry error that
    reads like a permissions problem."""
    try:
        tok = json.load(open(TOKEN_PATH))
    except OSError:
        sys.exit(f"{TOKEN_PATH} missing — run the device-code sign-in first "
                 "(see scripts/entra_provision.py)")
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
                                   "refresh_token": tok["refresh_token"],
                                   "scope": GRAPH_SCOPE}).encode()
    try:
        with urllib.request.urlopen(
                f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body,
                timeout=60) as r:
            tok.update(json.load(r))
    except urllib.error.HTTPError as e:
        sys.exit(f"Graph token refresh failed ({e.code}): {e.read()[:300]}\n"
                 "The refresh token has expired too — sign in again with the device-code flow.")
    json.dump(tok, open(TOKEN_PATH, "w"))
    return tok["access_token"]


TOKEN = _token()


def call(method, path, body=None):
    req = urllib.request.Request(G + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Graph {method} {path} -> {e.code}: {e.read()[:400]}")


def find_app(name):
    r = call("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'"))
    return r["value"][0] if r["value"] else None


def ensure_sp(app_id):
    r = call("GET", "/servicePrincipals?$filter=" + urllib.parse.quote(f"appId eq '{app_id}'"))
    return r["value"][0] if r["value"] else call("POST", "/servicePrincipals", {"appId": app_id})


def role_def(value: str) -> dict:
    """One app-role definition. The id is a uuid5 of the role's name, exactly as `entra_provision.py`
    does it, so re-running this script produces the SAME id and Entra treats it as the same role
    rather than creating a duplicate that existing assignments do not point at."""
    described = next((o.description for o in apipolicy.OPERATIONS if o.role == value), value)
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{GATEWAY}/{value}")), "value": value,
            "displayName": value, "description": f"Front door /api: {described}",
            "allowedMemberTypes": ["Application"], "isEnabled": True}


def main() -> int:
    gw = find_app(GATEWAY) or sys.exit(f"{GATEWAY} does not exist — run scripts/entra_provision.py first")
    have = {r["value"]: r for r in gw.get("appRoles") or []}
    wanted = [role_def(v) for v in ApiRoles.ALL]
    missing = [r for r in wanted if r["value"] not in have]
    if missing:
        # ADD to the existing collection. A PATCH replaces `appRoles` wholesale, so sending only the
        # new ones would delete EA.Model and Tools.ADOIT and un-grant every agent that holds them.
        call("PATCH", f"/applications/{gw['id']}", {"appRoles": list(have.values()) + missing})
        gw = call("GET", f"/applications/{gw['id']}")
        print(f"added app roles to {GATEWAY}: {', '.join(r['value'] for r in missing)}")
    else:
        print(f"{GATEWAY} already exposes {', '.join(ApiRoles.ALL)}")
    gw_sp = ensure_sp(gw["appId"])
    by_value = {r["value"]: r for r in gw["appRoles"]}

    app = find_app(CONNECTOR)
    if not app:
        app = call("POST", "/applications", {"displayName": CONNECTOR, "signInAudience": "AzureADMyOrg"})
        print(f"created {CONNECTOR}")
    else:
        print(f"{CONNECTOR} exists (a NEW secret will be added)")
    sec = call("POST", f"/applications/{app['id']}/addPassword",
               {"passwordCredential": {"displayName": "lab", "endDateTime": SECRET_EXPIRY}})
    sp = ensure_sp(app["appId"])

    granted = {a["appRoleId"] for a in call("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignments")["value"]}
    for value in CONNECTOR_ROLES:
        role = by_value[value]
        if role["id"] not in granted:
            call("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignments",
                 {"principalId": sp["id"], "resourceId": gw_sp["id"], "appRoleId": role["id"]})
            print(f"granted {value}")

    audience = (gw.get("identifierUris") or [f"api://{gw['appId']}"])[0]
    print("\nAdd to .env:")
    print(f"CONNECTOR_CLIENT_ID={app['appId']}")
    print(f"CONNECTOR_CLIENT_SECRET={sec['secretText']}")
    print("\nAnd add this app to ENTRA_CLIENT_TO_KEY (single-quoted JSON, one entry per app "
          "registration) — without it the gateway validates the token and then refuses, because "
          "there is no virtual key to meter the call on:")
    print(f"  \"{app['appId']}\": \"$POWER_AUTOMATE_KEY\"")
    print(f"\nThe flow acquires its token from:\n"
          f"  POST https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token\n"
          f"  grant_type=client_credentials&scope={audience}/.default"
          f"&client_id=<CONNECTOR_CLIENT_ID>&client_secret=<CONNECTOR_CLIENT_SECRET>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
