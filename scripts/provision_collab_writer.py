"""Provision the collaboration WRITE identity — a second app registration that may put files back.

WHY A SECOND APP AND NOT MORE PERMISSIONS ON THE FIRST. The read identity is called
`lab-collab-reader` and holds exactly six read grants; its name is a claim about its posture and the
grant list is the proof. Adding `Files.ReadWrite.All` to it would make every read path — listing
drives, fetching a recording, reading a transcript — run under a credential that can also overwrite
anything it can see, and nothing would record that this happened. Two registrations keep the claim
true: the reader stays provably read-only, and the writer is a credential that only the one service
performing a write ever holds.

That is the same reasoning the lab already applies to grants (ApprovalTools READ / RAISE / WRITE,
CollabTools READ / SUBSCRIBE / PUT). This is that split pushed one level down, into the provider
credential itself.

Grants `Files.ReadWrite.All` — the least-privileged permission that satisfies the `uploads`
capability (`graph_probe.PERMISSIONS`). Writing into a SharePoint site rather than a personal drive
would additionally want `Sites.ReadWrite.All` or, better, `Sites.Selected` plus a per-site grant.

Idempotent by display name. Needs var/run/graph_token.json (device-code sign-in) and ENTRA_TENANT_ID.
Prints the .env lines to add; the secret is shown once and stored nowhere.

Usage: .venv/bin/python scripts/provision_collab_writer.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from lab.substrate.mcp.graph import graph_probe                     # noqa: E402

G = "https://graph.microsoft.com/v1.0"
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"               # Microsoft Graph's own app
TENANT = os.environ.get("ENTRA_TENANT_ID") or sys.exit("ENTRA_TENANT_ID is not set (source .env)")
WRITER = "lab-collab-writer"
SECRET_EXPIRY = "2027-08-31T00:00:00Z"
TOKEN_PATH = "var/run/graph_token.json"
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"               # the Azure CLI public client
GRAPH_SCOPE = "Application.ReadWrite.All Directory.AccessAsUser.All offline_access"

# The capability this identity exists for, and therefore the permission it asks for. Taken from the
# probe's own table so the credential and the refusal-explainer cannot drift apart.
NEEDED = graph_probe.PERMISSIONS["uploads"][0]


def _token() -> str:
    """A live Graph access token, refreshed in place — the stored one lasts about an hour."""
    try:
        tok = json.load(open(TOKEN_PATH))
    except OSError:
        sys.exit(f"{TOKEN_PATH} missing — run the device-code sign-in first (scripts/entra_provision.py)")
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
                                   "refresh_token": tok["refresh_token"], "scope": GRAPH_SCOPE}).encode()
    try:
        with urllib.request.urlopen(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
                                    data=body, timeout=60) as r:
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


def main() -> int:
    graph_sp = call("GET", "/servicePrincipals?$filter=" +
                    urllib.parse.quote(f"appId eq '{GRAPH_APP_ID}'"))["value"][0]
    role = next((r for r in graph_sp["appRoles"] if r["value"] == NEEDED), None)
    if role is None:
        sys.exit(f"Microsoft Graph does not expose an application permission called {NEEDED}")

    app = find_app(WRITER)
    if not app:
        app = call("POST", "/applications", {"displayName": WRITER, "signInAudience": "AzureADMyOrg"})
        print(f"created {WRITER}")
    else:
        print(f"{WRITER} exists (a NEW secret will be added)")
    sec = call("POST", f"/applications/{app['id']}/addPassword",
               {"passwordCredential": {"displayName": "lab", "endDateTime": SECRET_EXPIRY}})
    sp = ensure_sp(app["appId"])

    granted = {a["appRoleId"] for a in
               call("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignments")["value"]}
    if role["id"] not in granted:
        call("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignments",
             {"principalId": sp["id"], "resourceId": graph_sp["id"], "appRoleId": role["id"]})
        print(f"granted {NEEDED}")
    else:
        print(f"{NEEDED} already granted")

    print("\nAdd to .env:")
    print(f"GRAPH_WRITER_CLIENT_ID={app['appId']}")
    print(f"GRAPH_WRITER_CLIENT_SECRET={sec['secretText']}")
    print("\nADMIN CONSENT is required for an application permission — grant it in the portal "
          f"(Entra ID -> App registrations -> {WRITER} -> API permissions -> Grant admin consent) "
          "if this tenant does not consent automatically.")
    print("\nThe read identity is untouched: `lab-collab-reader` still holds only its six read "
          "grants, which is what keeps its name true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
