"""Give PRODUCTION its own identities by MIRRORING dev's (docs/decisions/2026-09-24-azure-production.md,
"Separating dev from prod"). Production's registry started as a copy of dev's, so every virtual key, the
master key and every Entra app it uses were dev's own. This makes each one production's:

  Entra   every app the production profile references (each *_CLIENT_ID value, each ENTRA_CLIENT_TO_KEY
          client) gets a twin `<name>-prod` with its own secret and the SAME granted role assignments —
          a grant on `lab-gateway` becomes the same role on `lab-gateway-prod` (created here with identical
          role ids, so a DEV token cannot validate on the prod gateway); a Microsoft Graph grant stays a
          Graph grant. Apps with a web redirect (SSO) get production's URL in place of dev's.
  LiteLLM every virtual key in the PRODUCTION registry (the copies) is re-minted with identical settings,
          found by the value dev holds (the registry stores sha256 of a key), and the copy is deleted.
          The deploy identity (lab-deployer) gets a zero-tool key so CD's quiet gate is answered.
          The master key is rotated; the OLD one becomes LITELLM_SALT_KEY, which LiteLLM encrypts stored
          config with — so nothing it already encrypted becomes unreadable.
  Profile .env.azure gets every replaced value (prod ids, secrets, keys, the audience, the client->key map).

DRY RUN by default: prints NAMES only. `--apply` changes the tenant, the prod registry and .env.azure.
Uses the signed-in Azure CLI (az) for Graph; needs the prod gateway reachable with the CURRENT master key.
Idempotent enough to re-run after a partial failure: an existing `-prod` app is reused (a new secret is
added), and a key already re-minted is recognised by its alias suffix.
"""
import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import aca  # noqa: E402

SUFFIX = "-prod"
GRAPH = "https://graph.microsoft.com/v1.0"
MS_GRAPH_APP = "00000003-0000-0000-c000-000000000000"
DEPLOYER_APP = "94aa0908-0cc8-4e17-aaa5-ba5df865abcb"      # lab-deployer (already production-only)
SECRET_END = "2027-09-24T00:00:00Z"


# ------------------------------------------------------------------ Graph (as the signed-in admin)
def _token(resource):
    return subprocess.run(["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken",
                           "-o", "tsv"], capture_output=True, text=True, check=True).stdout.strip()


_GT = {}


def graph(method, path, body=None):
    _GT.setdefault("t", _token("https://graph.microsoft.com"))
    req = urllib.request.Request(GRAPH + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {_GT['t']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def app_by_appid(app_id):
    v = graph("GET", "/applications?$filter=" + urllib.parse.quote(f"appId eq '{app_id}'"))["value"]
    return v[0] if v else None


def app_by_name(name):
    v = graph("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'"))["value"]
    return v[0] if v else None


def sp_of(app_id):
    v = graph("GET", "/servicePrincipals?$filter=" + urllib.parse.quote(f"appId eq '{app_id}'"))["value"]
    return v[0] if v else graph("POST", "/servicePrincipals", {"appId": app_id})


# ------------------------------------------------------------------ LiteLLM (prod admin plane)
def litellm(gw, key, method, path, body=None):
    req = urllib.request.Request(gw + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def sha(key):
    return hashlib.sha256(key.encode()).hexdigest()


# ------------------------------------------------------------------ the plan
def referenced_apps(prof):
    """{dev appId: [profile keys naming it]} — every Entra client production's profile references."""
    ids = {}
    for k, v in prof.items():
        if k.endswith("_CLIENT_ID") and re.fullmatch(r"[0-9a-f-]{36}", v or ""):
            ids.setdefault(v, []).append(k)
    for client in json.loads(prof.get("ENTRA_CLIENT_TO_KEY") or "{}"):
        ids.setdefault(client, [])
    ids.pop(DEPLOYER_APP, None)
    return ids


def key_vars(prof):
    """{profile key: dev virtual key} for every value that is a LiteLLM virtual key."""
    return {k: v for k, v in prof.items() if v.startswith("sk-") and k != "LITELLM_MASTER_KEY"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    prof = aca.profile()
    dev_gateway = app_by_name("lab-gateway")
    apps = referenced_apps(prof)
    keys = key_vars(prof)
    gw_url = prof["PUBLIC_GATEWAY_URL"].rstrip("/")
    master = prof["LITELLM_MASTER_KEY"]
    registry, page = [], 1
    while True:                                       # the endpoint caps the page size: read every page
        got = litellm(gw_url, master, "GET", f"/key/list?return_full_object=true&size=100&page={page}")
        registry += got["keys"]
        if page >= int(got.get("total_pages") or 1):
            break
        page += 1
    by_hash = {k["token"]: k for k in registry}

    print(f"Entra: lab-gateway -> lab-gateway{SUFFIX}; {len(apps)} client app(s) to mirror:")
    names = {}
    for app_id, vars_ in sorted(apps.items(), key=lambda kv: kv[0]):
        a = app_by_appid(app_id)
        names[app_id] = a["displayName"] if a else None
        print(f"  {names[app_id] or '(no such app: ' + app_id + ')'} -> {(names[app_id] or '?') + SUFFIX}"
              f"   [{', '.join(vars_) or 'client->key map only'}]")
    print(f"LiteLLM: {len(registry)} key(s) in the prod registry; {len(keys)} referenced by the profile:")
    for k, v in sorted(keys.items()):
        rec = by_hash.get(sha(v))
        print(f"  {k:32} {'re-mint ' + (rec.get('key_alias') or '?') if rec else 'NOT IN PROD REGISTRY'}")
    orphans = [r.get("key_alias") or r["token"][:8] for r in registry if r["token"] not in {sha(v) for v in keys.values()}]
    print(f"  plus {len(orphans)} key(s) no profile value names (also re-minted, then the copy deleted): "
          f"{', '.join(map(str, orphans))}")
    print("master key: rotated; the current one becomes LITELLM_SALT_KEY")
    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply.")
        return

    out = {}                                          # .env.azure patch

    # 1. the production gateway audience
    gw = app_by_name("lab-gateway" + SUFFIX)
    if not gw:
        gw = graph("POST", "/applications", {
            "displayName": "lab-gateway" + SUFFIX, "signInAudience": "AzureADMyOrg",
            "appRoles": [{k: r[k] for k in ("id", "allowedMemberTypes", "description", "displayName", "isEnabled", "value")}
                         for r in dev_gateway["appRoles"]],
        })
        graph("PATCH", f"/applications/{gw['id']}", {
            "identifierUris": [f"api://{gw['appId']}"],
            "api": {"oauth2PermissionScopes": [{**s, "id": str(__import__('uuid').uuid4())}
                                               for s in dev_gateway["api"]["oauth2PermissionScopes"]]}})
        print(f"created lab-gateway{SUFFIX} {gw['appId']}")
    gw_sp = sp_of(gw["appId"])
    dev_gw_sp = sp_of(dev_gateway["appId"])
    out["ENTRA_GATEWAY_AUDIENCE"] = f"api://{gw['appId']}"
    out["ENTRA_GATEWAY_APP_ID"] = gw["appId"]

    # 2. mirror every referenced client app
    twin = {}                                         # dev appId -> prod appId
    for app_id, vars_ in apps.items():
        dev = app_by_appid(app_id)
        if not dev:
            continue
        name = dev["displayName"] + SUFFIX
        prod = app_by_name(name)
        if not prod:
            body = {"displayName": name, "signInAudience": "AzureADMyOrg"}
            if dev.get("web", {}).get("redirectUris"):
                body["web"] = {"redirectUris": [_prod_url(u, prof) for u in dev["web"]["redirectUris"]]}
            prod = graph("POST", "/applications", body)
        secret = graph("POST", f"/applications/{prod['id']}/addPassword",
                       {"passwordCredential": {"displayName": "lab-prod", "endDateTime": SECRET_END}})["secretText"]
        sp = sp_of(prod["appId"])
        have = {(a["resourceId"], a["appRoleId"]) for a in graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignments")["value"]}
        for a in graph("GET", f"/servicePrincipals/{sp_of(app_id)['id']}/appRoleAssignments")["value"]:
            resource = gw_sp["id"] if a["resourceId"] == dev_gw_sp["id"] else a["resourceId"]
            if (resource, a["appRoleId"]) not in have:
                graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignments",
                      {"principalId": sp["id"], "resourceId": resource, "appRoleId": a["appRoleId"]})
        twin[app_id] = prod["appId"]
        for v in vars_:
            out[v] = prod["appId"]
            out[v.replace("_CLIENT_ID", "_CLIENT_SECRET")] = secret
        print(f"  {name} ready")

    # 2b. developer sign-in: pre-authorise the same clients dev's audience does, as their prod twins (the
    #     Azure CLI is Microsoft's own client and has no twin)
    gw = app_by_appid(gw["appId"])
    scope_ids = [s["id"] for s in gw["api"]["oauth2PermissionScopes"]]
    preauth = [{"appId": twin.get(p["appId"], p["appId"]), "delegatedPermissionIds": scope_ids}
               for p in dev_gateway["api"].get("preAuthorizedApplications", [])]
    graph("PATCH", f"/applications/{gw['id']}", {"api": {"preAuthorizedApplications": preauth}})

    # 3. the deploy identity asks the quiet gate: Workflow.Submit on the PROD audience
    dep_sp = sp_of(DEPLOYER_APP)
    submit = next(r["id"] for r in dev_gateway["appRoles"] if r["value"] == "Workflow.Submit")
    if (gw_sp["id"], submit) not in {(a["resourceId"], a["appRoleId"]) for a in
                                     graph("GET", f"/servicePrincipals/{dep_sp['id']}/appRoleAssignments")["value"]}:
        graph("POST", f"/servicePrincipals/{dep_sp['id']}/appRoleAssignments",
              {"principalId": dep_sp["id"], "resourceId": gw_sp["id"], "appRoleId": submit})

    # 4. re-mint every key in the prod registry, then delete the copy
    fields = ("key_alias", "team_id", "models", "max_budget", "budget_duration", "rpm_limit", "tpm_limit",
              "metadata", "object_permission", "user_id", "max_parallel_requests", "allowed_routes")
    new_by_hash = {}
    for rec in registry:
        body = {f: rec.get(f) for f in fields if rec.get(f) not in (None, [], {})}
        if body.get("key_alias"):
            body["key_alias"] = body["key_alias"] + SUFFIX
        new = litellm(gw_url, master, "POST", "/key/generate", body)["key"]
        new_by_hash[rec["token"]] = new
    litellm(gw_url, master, "POST", "/key/delete", {"keys": [r["token"] for r in registry]})
    for k, v in keys.items():
        if sha(v) in new_by_hash:
            out[k] = new_by_hash[sha(v)]
    team = litellm(gw_url, master, "POST", "/team/new", {"team_alias": "deploy", "models": [], "max_budget": 0.01,
                                                         "object_permission": {"mcp_servers": ["-"], "vector_stores": ["-"]}})
    deploy_key = litellm(gw_url, master, "POST", "/key/generate", {"key_alias": "lab-deployer", "team_id": team["team_id"],
                                                                   "models": [], "max_budget": 0.01})["key"]

    # 5. the client -> key map, production's only
    dev_map = json.loads(prof.get("ENTRA_CLIENT_TO_KEY") or "{}")
    prod_map = {twin[c]: new_by_hash[sha(k)] for c, k in dev_map.items() if c in twin and sha(k) in new_by_hash}
    prod_map[DEPLOYER_APP] = deploy_key
    out["ENTRA_CLIENT_TO_KEY"] = "'" + json.dumps(prod_map) + "'"

    # 6. the master key
    out["LITELLM_SALT_KEY"] = master
    out["LITELLM_MASTER_KEY"] = "sk-" + secrets.token_urlsafe(32)

    _patch(ROOT / aca.PROFILE_OVERLAY, out)
    print(f"\n.env.azure: {len(out)} value(s) replaced — {', '.join(sorted(out))}")
    print("next: python deploy/aca.py substrate up   (publishes them; the gateway restarts on the new audience and keys)")


def _prod_url(url, prof):
    """A dev redirect URL -> the same path on production's edge (review app, gateway UI)."""
    host = urllib.parse.urlsplit(url).netloc
    if "review" in host:
        return url.replace(f"https://{host}", prof["REVIEW_APP_URL"].rstrip("/"))
    return url.replace(f"https://{host}", prof["PUBLIC_GATEWAY_URL"].rstrip("/"))


def _patch(path, patch):
    lines = path.read_text().splitlines()
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.startswith("#") else None
        if k in patch:
            out.append(f"{k}={patch[k]}")
            seen.add(k)
        else:
            out.append(ln)
    out += [f"{k}={v}" for k, v in patch.items() if k not in seen]
    path.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
