"""Provision identity + governance for the Visio->ArchiMate workflow's two agents.

One team per business process, one virtual key per agent, each key paired 1:1 with an Entra app
registration (the docx operating model). Creates:

  Entra (Microsoft Graph, token auto-refreshed from .lab/graph_token.json):
    - app `ba-agent`        (client-credentials) granted lab-gateway role EA.Model
    - app `architect-agent` (client-credentials) granted EA.Model + Tools.ADOIT
  LiteLLM (master key, admin plane):
    - team `visio-conversion` (budget; MCP grant adoit_mcp + semantic_mcp for the process)
    - virtual keys `ba-agent`, `architect-agent` (kimi-k3; per-agent budget/rpm/tpm)

Then patches .env: BA_AGENT_CLIENT_ID/SECRET, ARCHITECT_AGENT_CLIENT_ID/SECRET, VISIO_TEAM_ID,
BA_AGENT_KEY, ARCHITECT_AGENT_KEY, and adds both appId->key entries to ENTRA_CLIENT_TO_KEY
(single-quoted JSON, so .env sourcing stays intact). Idempotent: reuses apps found by display
name and keys already recorded in .env; re-running adds a fresh secret only.

Usage: set -a && source .env && set +a && .venv/bin/python gateway/provision_visio_agents.py
"""
import json
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

TENANT = os.environ["ENTRA_TENANT_ID"]
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_CLIENT = "14d82eec-204b-4c2f-b7e8-296a70dab67e"   # Microsoft Graph public client (device-code)
GW = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000")
MASTER = os.environ["LITELLM_MASTER_KEY"]
ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
TOKF = ROOT / ".lab" / "graph_token.json"

# --- Graph token (auto-refresh) ---
_tok = json.load(open(TOKF))


def _refresh():
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": GRAPH_CLIENT,
        "refresh_token": _tok["refresh_token"],
        "scope": "Application.ReadWrite.All AppRoleAssignment.ReadWrite.All Directory.AccessAsUser.All offline_access",
    }).encode()
    r = json.load(urllib.request.urlopen(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body, timeout=60))
    _tok.update(r)
    json.dump(_tok, open(TOKF, "w"))


_refresh()


def graph(method, path, body=None):
    req = urllib.request.Request(
        GRAPH + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_tok['access_token']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r) if r.status != 204 else {}


def find_app(name):
    r = graph("GET", "/applications?$filter=" + urllib.parse.quote(f"displayName eq '{name}'"))
    return r["value"][0] if r["value"] else None


def ensure_sp(app_id):
    r = graph("GET", "/servicePrincipals?$filter=" + urllib.parse.quote(f"appId eq '{app_id}'"))
    return r["value"][0] if r["value"] else graph("POST", "/servicePrincipals", {"appId": app_id})


def role_id(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lab-gateway/{value}"))


def ensure_agent(name, role_values, gw_sp):
    app = find_app(name)
    if not app:
        app = graph("POST", "/applications",
                    {"displayName": name, "signInAudience": "AzureADMyOrg"})
        print(f"created {name}")
    else:
        print(f"{name} exists (adding a fresh secret)")
    sec = graph("POST", f"/applications/{app['id']}/addPassword",
                {"passwordCredential": {"displayName": "lab", "endDateTime": "2027-08-31T00:00:00Z"}})
    sp = ensure_sp(app["appId"])
    existing = {a["appRoleId"] for a in
                graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignments")["value"]}
    for rv in role_values:
        rid = role_id(rv)
        if rid not in existing:
            graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignments",
                  {"principalId": sp["id"], "resourceId": gw_sp["id"], "appRoleId": rid})
            print(f"  granted {rv} to {name}")
    return app["appId"], sec["secretText"]


# --- LiteLLM admin plane ---
def litellm(path, body):
    req = urllib.request.Request(
        GW + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    gw_app = find_app("lab-gateway")
    if not gw_app:
        raise SystemExit("lab-gateway app not found — run gateway/entra_provision.py first")
    gw_sp = ensure_sp(gw_app["appId"])

    ba_id, ba_secret = ensure_agent("ba-agent", ["EA.Model"], gw_sp)
    ar_id, ar_secret = ensure_agent("architect-agent", ["EA.Model", "Tools.ADOIT"], gw_sp)

    # team (reuse if VISIO_TEAM_ID already set)
    team_id = os.environ.get("VISIO_TEAM_ID")
    if not team_id:
        team = litellm("/team/new", {
            "team_alias": "visio-conversion", "max_budget": 5.0, "budget_duration": "30d",
            "models": ["kimi-k3", "gpt-oss-120b", "glm-flash"],
            "object_permission": {"mcp_servers": ["adoit_mcp", "semantic_mcp", "storage_mcp"]},
        })
        team_id = team["team_id"]
        print("created team visio-conversion:", team_id)
    else:
        print("reusing team:", team_id)

    def make_key(alias, role):
        return litellm("/key/generate", {
            "key_alias": alias, "team_id": team_id, "models": ["kimi-k3"],
            "max_budget": 2.0, "budget_duration": "30d", "rpm_limit": 30, "tpm_limit": 60000,
            "metadata": {"role": role, "entra_app_registration": alias},
        })["key"]

    ba_key = os.environ.get("BA_AGENT_KEY") or make_key("ba-agent", "Business Analyst")
    ar_key = os.environ.get("ARCHITECT_AGENT_KEY") or make_key("architect-agent", "Architect")

    # merge appId->key mapping
    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY", "{}"))
    mapping[ba_id] = ba_key
    mapping[ar_id] = ar_key

    patch = {
        "BA_AGENT_CLIENT_ID": ba_id, "BA_AGENT_CLIENT_SECRET": ba_secret,
        "ARCHITECT_AGENT_CLIENT_ID": ar_id, "ARCHITECT_AGENT_CLIENT_SECRET": ar_secret,
        "VISIO_TEAM_ID": team_id, "BA_AGENT_KEY": ba_key, "ARCHITECT_AGENT_KEY": ar_key,
        "ENTRA_CLIENT_TO_KEY": "'" + json.dumps(mapping) + "'",   # single-quoted for .env sourcing
    }
    _patch_env(patch)
    print("\n.env updated with:", ", ".join(patch))
    print("Restart the gateway via ./lab.sh so custom_auth reloads ENTRA_CLIENT_TO_KEY.")


def _patch_env(patch: dict):
    lines = ENV.read_text().splitlines()
    keys = set(patch)
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.lstrip().startswith("#") else None
        if k in keys:
            out.append(f"{k}={patch[k]}")
            seen.add(k)
        else:
            out.append(ln)
    for k in patch:
        if k not in seen:
            out.append(f"{k}={patch[k]}")
    ENV.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
