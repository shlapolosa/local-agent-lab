"""Mirror each production identity's TEAM into an Entra app role APIM enforces: `Grant.<team>`.

LiteLLM grants tools to a team and admits an identity by mapping its client id to a key in that team
(`ENTRA_CLIENT_TO_KEY`). APIM has no teams, so production carries the same fact as an app role on
lab-gateway-prod, and deploy/apim.py's MCP policy reads the team's tools from deploy/grants.py. This
walks LiteLLM's own path — client -> mapped key -> the key's team — so an identity gets exactly the
team it has today. Only teams deploy/grants.py declares become roles; a stale assignment is revoked.
Idempotent; appends to `appRoles` (a PATCH replaces the collection).

    python scripts/grant_team_roles.py [--app lab-gateway-prod] [--profile .env.azure]
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import grants  # noqa: E402


def graph(method, path, body=None) -> dict:
    cmd = ["az", "rest", "--method", method, "--url", f"https://graph.microsoft.com/v1.0{path}",
           "--headers", "Content-Type=application/json"] + (["--body", json.dumps(body)] if body else [])
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else {}


def profile(path: str) -> dict:
    env = {}
    for line in open(path):
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.rstrip("\n"))
        if m:
            env[m.group(1)] = m.group(2).strip("'\"")
    return env


def team_of(gateway: str, master: str, key: str) -> str:
    """The team alias LiteLLM puts this key in (its team id resolved to the alias both targets use)."""
    hdr = {"Authorization": f"Bearer {master}"}
    info = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{gateway}/key/info?key={key}", headers=hdr), timeout=60))["info"]
    team = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{gateway}/team/info?team_id={info['team_id']}", headers=hdr), timeout=60))
    return team["team_info"]["team_alias"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", default="lab-gateway-prod")
    p.add_argument("--profile", default=".env.azure")
    args = p.parse_args()
    env = profile(args.profile)
    gateway = env["PUBLIC_GATEWAY_URL"].rstrip("/")
    mapping = json.loads(env["ENTRA_CLIENT_TO_KEY"])

    wanted: dict[str, str] = {}                       # service principal id -> team
    names: dict[str, str] = {}
    for client, key in mapping.items():
        team = team_of(gateway, env["LITELLM_MASTER_KEY"], key)
        if team not in grants.TEAMS:
            continue                                  # a team with no MCP grant (deploy, reference-corpus)
        found = graph("GET", f"/servicePrincipals?$filter=appId eq '{client}'&$select=id,displayName")["value"]
        if found:
            wanted[found[0]["id"]], names[found[0]["id"]] = team, found[0]["displayName"]

    app = graph("GET", f"/applications?$filter=displayName eq '{args.app}'")["value"][0]
    roles = app["appRoles"]
    have = {r["value"] for r in roles}
    new = [{"id": str(uuid.uuid4()), "value": grants.role(t), "displayName": grants.role(t), "isEnabled": True,
            "allowedMemberTypes": ["Application"], "description": f"The {t} team's MCP grant (deploy/grants.py)"}
           for t in sorted(set(wanted.values())) if grants.role(t) not in have]
    if new:
        roles = roles + new
        graph("PATCH", f"/applications/{app['id']}", {"appRoles": roles})
        print(f"{args.app}: added {', '.join(r['value'] for r in new)}")
    by_value = {r["value"]: r["id"] for r in roles}
    by_id = {r["id"]: r["value"] for r in roles}

    sp = graph("GET", f"/servicePrincipals?$filter=appId eq '{app['appId']}'")["value"][0]
    assigned = graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo?$top=999")["value"]
    held = {(a["principalId"], by_id.get(a["appRoleId"], "")) for a in assigned}
    for a in assigned:
        value = by_id.get(a["appRoleId"], "")
        if value.startswith(grants.role("")) and wanted.get(a["principalId"]) != value[len(grants.role("")):]:
            graph("DELETE", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo/{a['id']}")
            print(f"revoked {value} <- {a['principalDisplayName']}")
    for pid, team in sorted(wanted.items(), key=lambda kv: names[kv[0]]):
        if (pid, grants.role(team)) not in held:
            graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo",
                  {"principalId": pid, "resourceId": sp["id"], "appRoleId": by_value[grants.role(team)]})
            print(f"granted {grants.role(team)} -> {names[pid]}")
    print(f"{len(wanted)} identities carry a team role")


if __name__ == "__main__":
    main()
