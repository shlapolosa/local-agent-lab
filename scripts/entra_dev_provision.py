"""Extend the Entra setup for DEVELOPER (interactive) access:
  - lab-gateway app gains a delegated scope `access_as_user` (users consume the gateway)
  - new PUBLIC client app `lab-developers` (device-code capable) pre-authorized for that scope
Prints the .env additions. Refreshes the Graph token from var/run/graph_token.json automatically.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TENANT = "b911f4d4-de30-405f-96e9-bb1c773fe2ff"
G = "https://graph.microsoft.com/v1.0"
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

tok = json.load(open("var/run/graph_token.json"))
def refresh():
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
                                   "refresh_token": tok["refresh_token"],
                                   "scope": "Application.ReadWrite.All Directory.AccessAsUser.All offline_access"}).encode()
    r = json.load(urllib.request.urlopen(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body, timeout=60))
    tok.update(r); json.dump(tok, open("var/run/graph_token.json", "w"))
refresh()
H = {"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json"}

def call(method, path, body=None):
    req = urllib.request.Request(G + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Graph {method} {path} -> {e.code}: {e.read()[:300]}")

def find(name):
    r = call("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'"))
    return r["value"][0] if r["value"] else None

gw = find("lab-gateway"); assert gw, "run entra_provision.py first"
SCOPE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "lab-gateway/access_as_user"))
api = gw.get("api") or {}
scopes = api.get("oauth2PermissionScopes", [])
if not any(s["value"] == "access_as_user" for s in scopes):
    scopes.append({"id": SCOPE_ID, "value": "access_as_user", "type": "User",
                   "adminConsentDisplayName": "Access the lab gateway", "adminConsentDescription": "Consume models through the lab gateway",
                   "userConsentDisplayName": "Access the lab gateway", "userConsentDescription": "Consume models through the lab gateway",
                   "isEnabled": True})
    call("PATCH", f"/applications/{gw['id']}", {"api": {**api, "oauth2PermissionScopes": scopes}})
    print("scope access_as_user added to lab-gateway")
else:
    SCOPE_ID = next(s["id"] for s in scopes if s["value"] == "access_as_user")
    print("scope exists")

dev = find("lab-developers")
if not dev:
    dev = call("POST", "/applications", {
        "displayName": "lab-developers", "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "publicClient": {"redirectUris": ["https://login.microsoftonline.com/common/oauth2/nativeclient"]},
        "requiredResourceAccess": [{"resourceAppId": gw["appId"],
                                    "resourceAccess": [{"id": SCOPE_ID, "type": "Scope"}]}]})
    print("created lab-developers (public client)")
else:
    print("lab-developers exists")
# pre-authorize the dev client on the gateway app (no consent prompt for users)
gw = call("GET", f"/applications/{gw['id']}")
api = gw.get("api") or {}
pre = api.get("preAuthorizedApplications", [])
if not any(p["appId"] == dev["appId"] for p in pre):
    pre.append({"appId": dev["appId"], "delegatedPermissionIds": [SCOPE_ID]})
    call("PATCH", f"/applications/{gw['id']}", {"api": {**api, "preAuthorizedApplications": pre}})
    print("lab-developers pre-authorized for access_as_user")

print("\nAdd to .env:")
print(f"DEV_CLIENT_ID={dev['appId']}")
