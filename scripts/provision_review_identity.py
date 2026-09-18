"""Register the review app's own Entra WEB app so a PERSON signs in and the ledger names them.

Until now every decision in the approval ledger was self-asserted: `approvals.human_decision`
refuses a blank actor and cannot check a present one, and the actor came from a sidebar text box. So
"who released this EA-repository write" — the question the audit trail exists to answer — was
answered by whoever was at the keyboard.

This registers `lab-review-app`: a confidential web app with ID-token issuance, a redirect for every
place the app runs, and THREE APP ROLES — `Lab.Admin`, `Lab.Architect`, `Lab.Business`.

**Why its own registration, and its own roles.** `lab-gateway`'s roles (`ApiRoles`) are the REST
ingress's vocabulary: three values, each of which a governance test requires to map to an
`apipolicy` operation, so a role with no REST operation fails there as dead. These three are about
what a person may do in this app, not what a caller may do at the door, and the two vocabularies
should not be forced to agree.

**Assignment is a separate, deliberate act.** This creates the roles; it does not grant them. A
person gets one in Entra (Enterprise applications -> lab-review-app -> Users and groups), which is
the point: adding an approver is an identity-governance action with its own audit trail, not a code
change.

    set -a && source .env && set +a
    .venv/bin/python scripts/provision_review_identity.py

Idempotent. Re-run to add a redirect URI or a missing role. Prints the `.env` additions; the secret
is shown ONCE, as Graph only returns it at creation.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from lab.substrate.review import identity                            # noqa: E402  the role vocabulary

APP_NAME = "lab-review-app"
TENANT = os.environ.get("ENTRA_TENANT_ID") or "b911f4d4-de30-405f-96e9-bb1c773fe2ff"
G = "https://graph.microsoft.com/v1.0"
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
TOKEN_FILE = "var/run/graph_token.json"

#: Every place the app runs. BOTH, on one registration: a redirect that does not match the request
#: exactly is rejected by Entra, and the cloud URL is not knowable from a laptop.
REDIRECTS = sorted({
    (os.environ.get("REVIEW_APP_URL") or "http://127.0.0.1:8501").rstrip("/") + "/",
    "http://localhost:8501/",
})

#: What each role is FOR, in the words a person assigning it will read in the Entra portal. The
#: description is the only place that decision gets explained, so it is not an afterthought.
DESCRIPTIONS = {
    identity.ADMIN: ("Maintain the reference artifacts every assessment reads — upload a new master, "
                     "see it validated against the artifact's own schema, and stage it for an "
                     "operator to sign and release."),
    identity.ARCHITECT: ("Confirm that a design conforms: review the architecture, the bound "
                         "obligations and what the design still owes, then approve, request changes "
                         "or decline."),
    identity.BUSINESS: ("Authorise the build: review the business case and the costed model, then "
                        "approve, request changes or decline. Separate from conformance, because a "
                        "conformant design can still be declined on value."),
}


def _token() -> str:
    """Refresh the stored Graph token in place, as the sibling provisioning scripts do."""
    tok = json.load(open(TOKEN_FILE))
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
        "refresh_token": tok["refresh_token"],
        "scope": "Application.ReadWrite.All Directory.AccessAsUser.All offline_access"}).encode()
    tok.update(json.load(urllib.request.urlopen(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body, timeout=60)))
    json.dump(tok, open(TOKEN_FILE, "w"))
    return tok["access_token"]


def call(method: str, path: str, body=None):
    req = urllib.request.Request(
        G + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {ACCESS}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Graph {method} {path} -> {e.code}: {e.read()[:300]}")


def find(name: str):
    q = urllib.parse.quote(f"displayName eq '{name}'")
    hits = call("GET", f"/applications?$filter={q}")["value"]
    return hits[0] if hits else None


def role_def(value: str) -> dict:
    """One appRole. The id is a uuid5 of the role's name so a re-run produces the SAME id — Entra
    treats a changed id as a different role and would orphan every existing assignment."""
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{APP_NAME}/{value}")),
            "allowedMemberTypes": ["User"],          # people, not applications
            "displayName": value.split(".", 1)[-1], "value": value,
            "description": DESCRIPTIONS[value], "isEnabled": True}


def main() -> int:
    app = find(APP_NAME)
    web = {"redirectUris": REDIRECTS, "implicitGrantSettings": {"enableIdTokenIssuance": True}}
    if not app:
        app = call("POST", "/applications", {
            "displayName": APP_NAME, "signInAudience": "AzureADMyOrg", "web": web,
            "appRoles": [role_def(r) for r in identity.ROLES]})
        print(f"created {APP_NAME} with {len(identity.ROLES)} roles")
    else:
        have = {r["value"]: r for r in app.get("appRoles") or []}
        missing = [role_def(r) for r in identity.ROLES if r not in have]
        existing_web = app.get("web") or {}
        call("PATCH", f"/applications/{app['id']}", {
            "web": {**existing_web,
                    "redirectUris": sorted(set(existing_web.get("redirectUris") or []) | set(REDIRECTS)),
                    "implicitGrantSettings": {"enableIdTokenIssuance": True}},
            # ADD to the existing collection. A PATCH REPLACES `appRoles` wholesale, so sending only
            # the new ones would delete the others and un-assign every person who holds them.
            **({"appRoles": list(have.values()) + missing} if missing else {})})
        print(f"{APP_NAME} exists — redirects ensured"
              + (f", added {[r['value'] for r in missing]}" if missing else ", roles unchanged"))

    # A service principal is what a person is actually assigned a role ON; without it, sign-in and
    # the Users-and-groups blade both fail with errors that do not say this is missing.
    q = urllib.parse.quote(f"appId eq '{app['appId']}'")
    if not call("GET", f"/servicePrincipals?$filter={q}")["value"]:
        call("POST", "/servicePrincipals", {"appId": app["appId"]})
        print("created its service principal")

    secret = call("POST", f"/applications/{app['id']}/addPassword",
                  {"passwordCredential": {"displayName": "review-sso",
                                          "endDateTime": "2027-08-31T00:00:00Z"}})
    print("\nAdd to .env (the secret is shown ONCE — Graph returns it only at creation):\n")
    print(f"REVIEW_ENTRA_CLIENT_ID={app['appId']}")
    print(f"REVIEW_ENTRA_CLIENT_SECRET={secret['secretText']}")
    print(f"\nRedirect URIs registered: {', '.join(REDIRECTS)}")
    print(f"\nNow ASSIGN people: Entra portal -> Enterprise applications -> {APP_NAME} -> "
          f"Users and groups. Nobody holds a role until you do, and a signed-in person with no "
          f"role sees the app and can do nothing — which is the correct, and legible, default.")
    return 0


if __name__ == "__main__":
    ACCESS = _token()
    raise SystemExit(main())
