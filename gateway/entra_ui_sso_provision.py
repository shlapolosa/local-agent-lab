"""Register the Entra confidential WEB app for LiteLLM UI SSO — lets developers sign in with
their Entra identity at the gateway UI and self-serve a durable per-user key (no CLI, no az).
Redirect: <PROXY_BASE_URL>/sso/callback. Prints the .env additions (client id + secret).
Refreshes the Graph token from .lab/graph_token.json.
"""
import json, urllib.error, urllib.parse, urllib.request

TENANT = "b911f4d4-de30-405f-96e9-bb1c773fe2ff"; G = "https://graph.microsoft.com/v1.0"
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
import os
PROXY_BASE_URL = os.environ.get("PROXY_BASE_URL", "http://127.0.0.1:4000")
REDIRECT = PROXY_BASE_URL.rstrip("/") + "/sso/callback"

tok = json.load(open(".lab/graph_token.json"))
body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
    "refresh_token": tok["refresh_token"],
    "scope": "Application.ReadWrite.All Directory.AccessAsUser.All offline_access"}).encode()
tok.update(json.load(urllib.request.urlopen(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body, timeout=60)))
json.dump(tok, open(".lab/graph_token.json", "w"))
H = {"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json"}

def call(m, p, b=None):
    req = urllib.request.Request(G + p, method=m, data=json.dumps(b).encode() if b is not None else None, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e: raise SystemExit(f"Graph {m} {p} -> {e.code}: {e.read()[:300]}")

def find(name):
    r = call("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'")); return r["value"][0] if r["value"] else None

app = find("lab-gateway-ui")
if not app:
    app = call("POST", "/applications", {"displayName": "lab-gateway-ui", "signInAudience": "AzureADMyOrg",
        "web": {"redirectUris": [REDIRECT], "implicitGrantSettings": {"enableIdTokenIssuance": True}}})
    print("created lab-gateway-ui")
else:
    web = app.get("web") or {}
    uris = set(web.get("redirectUris", [])) | {REDIRECT}
    call("PATCH", f"/applications/{app['id']}", {"web": {**web, "redirectUris": sorted(uris)}})
    print("lab-gateway-ui exists (redirect ensured)")
sec = call("POST", f"/applications/{app['id']}/addPassword",
           {"passwordCredential": {"displayName": "ui-sso", "endDateTime": "2027-08-31T00:00:00Z"}})
# ensure a service principal exists (needed for sign-in)
sp = call("GET", "/servicePrincipals?$filter=" + urllib.parse.quote(f"appId eq '{app['appId']}'"))
if not sp["value"]:
    call("POST", "/servicePrincipals", {"appId": app["appId"]})
print(f"\nAdd to .env:")
print(f"MICROSOFT_CLIENT_ID={app['appId']}")
print(f"MICROSOFT_CLIENT_SECRET={sec['secretText']}")
print(f"MICROSOFT_TENANT={TENANT}")
print(f"PROXY_BASE_URL={PROXY_BASE_URL}")
print(f"redirect registered: {REDIRECT}")
