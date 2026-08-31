"""Provision the lab's Entra ID identities via Microsoft Graph — the Agent 365 pattern:
one app registration per agent, application permissions (app roles) on the gateway app.

Creates (idempotently, by display name):
  lab-gateway            app exposing api://lab-gateway with app roles EA.Model, Tools.ADOIT
  ea-modeling-agent      app + client secret, granted EA.Model + Tools.ADOIT (admin-consented
                         via appRoleAssignment on the service principals)

Needs .lab/graph_token.json from the device-code sign-in. Prints the .env lines to add.
Usage: .venv/bin/python gateway/entra_provision.py
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

TENANT = "b911f4d4-de30-405f-96e9-bb1c773fe2ff"
G = "https://graph.microsoft.com/v1.0"
TOKEN = json.load(open(".lab/graph_token.json"))["access_token"]


def call(method, path, body=None):
    req = urllib.request.Request(G + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Graph {method} {path} -> {e.code}: {e.read()[:300]}")


def find_app(name):
    r = call("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'"))
    return r["value"][0] if r["value"] else None


def ensure_sp(app_id):
    r = call("GET", "/servicePrincipals?$filter=" + urllib.parse.quote(f"appId eq '{app_id}'"))
    return r["value"][0] if r["value"] else call("POST", "/servicePrincipals", {"appId": app_id})


ROLES = [
    {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "lab-gateway/EA.Model")), "value": "EA.Model",
     "displayName": "EA modelling", "description": "Generate/validate architecture models",
     "allowedMemberTypes": ["Application"], "isEnabled": True},
    {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "lab-gateway/Tools.ADOIT")), "value": "Tools.ADOIT",
     "displayName": "ADOIT tools", "description": "Use the ADOIT MCP tools",
     "allowedMemberTypes": ["Application"], "isEnabled": True},
]

# --- gateway app (the audience) ---
gw = find_app("lab-gateway")
if not gw:
    gw = call("POST", "/applications", {"displayName": "lab-gateway",
                                        "signInAudience": "AzureADMyOrg", "appRoles": ROLES})
    call("PATCH", f"/applications/{gw['id']}", {"identifierUris": [f"api://{gw['appId']}"]})
    gw = call("GET", f"/applications/{gw['id']}")
    print("created lab-gateway")
else:
    print("lab-gateway exists")
gw_sp = ensure_sp(gw["appId"])
audience = gw.get("identifierUris") and gw["identifierUris"][0] or f"api://{gw['appId']}"

# --- agent app + secret ---
ag = find_app("ea-modeling-agent")
secret = None
if not ag:
    ag = call("POST", "/applications", {"displayName": "ea-modeling-agent", "signInAudience": "AzureADMyOrg"})
    print("created ea-modeling-agent")
else:
    print("ea-modeling-agent exists (a NEW secret will be added)")
sec = call("POST", f"/applications/{ag['id']}/addPassword",
           {"passwordCredential": {"displayName": "lab", "endDateTime": "2027-08-31T00:00:00Z"}})
secret = sec["secretText"]
ag_sp = ensure_sp(ag["appId"])

# --- grant app roles (this IS the admin consent for application permissions) ---
existing = {a["appRoleId"] for a in call("GET", f"/servicePrincipals/{ag_sp['id']}/appRoleAssignments")["value"]}
for role in ROLES:
    if role["id"] not in existing:
        call("POST", f"/servicePrincipals/{ag_sp['id']}/appRoleAssignments",
             {"principalId": ag_sp["id"], "resourceId": gw_sp["id"], "appRoleId": role["id"]})
        print(f"granted {role['value']}")

print("\nAdd to .env:")
print(f"ENTRA_TENANT_ID={TENANT}")
print(f"ENTRA_GATEWAY_AUDIENCE={audience}")
print(f"ENTRA_GATEWAY_APP_ID={gw['appId']}")
print(f"EA_AGENT_CLIENT_ID={ag['appId']}")
print(f"EA_AGENT_CLIENT_SECRET={secret}")
