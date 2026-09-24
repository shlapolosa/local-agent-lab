"""Give production's gateway app the `Models.Use` role and grant it to the agents that call models.

APIM admits a model call on a production token carrying `Models.Use` (deploy/apim.py). LiteLLM needed
no role: its custom_auth admitted any client listed in `ENTRA_CLIENT_TO_KEY` and mapped it to a key. So
the callers are exactly that mapping, read from the production profile — minus a client whose roles
are ONLY front-door roles (the Power Automate connector, the deploy gate): it reaches `/api`, never a
model, and a grant it holds is revoked. Idempotent.

The role is APPENDED: a PATCH replaces the whole `appRoles` collection, and sending only the new role
would un-grant every existing agent (CLAUDE.md, provision_connector_identity).

    python scripts/grant_models_role.py [--app lab-gateway-prod] [--profile .env.azure]
"""
import argparse
import json
import re
import subprocess
import uuid

ROLE = "Models.Use"
#: The front door's vocabulary (lab.platform.contracts.ApiRoles): holding only these is not an agent.
FRONT_DOOR = {"Workflow.Submit", "Approvals.Read", "Approvals.Decide"}


def graph(method, path, body=None) -> dict:
    cmd = ["az", "rest", "--method", method, "--url", f"https://graph.microsoft.com/v1.0{path}",
           "--headers", "Content-Type=application/json"] + (["--body", json.dumps(body)] if body else [])
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else {}


def mapped_clients(profile: str) -> set[str]:
    for line in open(profile):
        m = re.match(r"^ENTRA_CLIENT_TO_KEY=(.*)$", line.rstrip("\n"))
        if m:
            return set(json.loads(m.group(1).strip("'\"")))
    raise SystemExit(f"{profile} has no ENTRA_CLIENT_TO_KEY")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", default="lab-gateway-prod")
    p.add_argument("--profile", default=".env.azure")
    args = p.parse_args()
    app = graph("GET", f"/applications?$filter=displayName eq '{args.app}'")["value"][0]
    roles = app["appRoles"]
    role = next((r for r in roles if r["value"] == ROLE), None)
    if role is None:
        role = {"id": str(uuid.uuid4()), "value": ROLE, "displayName": ROLE, "isEnabled": True,
                "allowedMemberTypes": ["Application"],
                "description": "Call the models this gateway serves (production: APIM)"}
        graph("PATCH", f"/applications/{app['id']}", {"appRoles": roles + [role]})
        roles = roles + [role]
        print(f"{args.app}: added {ROLE}")
    sp = graph("GET", f"/servicePrincipals?$filter=appId eq '{app['appId']}'")["value"][0]
    assigned = graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo?$top=999")["value"]
    value = {r["id"]: r["value"] for r in roles}
    held: dict[str, set] = {}
    for a in assigned:
        held.setdefault(a["principalId"], set()).add(value.get(a["appRoleId"], ""))

    callers = {}
    for client in mapped_clients(args.profile):
        found = graph("GET", f"/servicePrincipals?$filter=appId eq '{client}'&$select=id,displayName")["value"]
        if not found:
            print(f"skipped a mapped client with no service principal in this tenant")
            continue
        pid, name = found[0]["id"], found[0]["displayName"]
        others = held.get(pid, set()) - {ROLE}
        if others and others <= FRONT_DOOR:
            continue
        callers[pid] = name

    for a in assigned:
        if a["appRoleId"] == role["id"] and a["principalId"] not in callers:
            graph("DELETE", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo/{a['id']}")
            print(f"revoked {ROLE} <- {a['principalDisplayName']}")
    for pid, name in sorted(callers.items(), key=lambda kv: kv[1]):
        if ROLE not in held.get(pid, set()):
            graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo",
                  {"principalId": pid, "resourceId": sp["id"], "appRoleId": role["id"]})
            print(f"granted {ROLE} -> {name}")
    print(f"{ROLE}: held by {len(callers)} agents")


if __name__ == "__main__":
    main()
