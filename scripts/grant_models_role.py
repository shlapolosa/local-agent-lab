"""Give production's gateway app the `Models.Use` role and grant it to the agents that call models.

APIM admits a model call on a production token carrying `Models.Use` (deploy/apim.py). Under LiteLLM a
model call needed only a mapped virtual key, so no role existed. An identity holding a role on
lab-gateway-prod BEYOND the front-door roles is an agent, and agents call models. A caller holding only
`/api` roles (the deploy gate, the Power Automate connector) never calls a model and does not get it —
a grant it does hold is revoked. Idempotent.

The role is APPENDED: a PATCH replaces the whole `appRoles` collection, and sending only the new role
would un-grant every existing agent (CLAUDE.md, provision_connector_identity).

    python scripts/grant_models_role.py [--app lab-gateway-prod]
"""
import argparse
import json
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", default="lab-gateway-prod")
    name = p.parse_args().app
    app = graph("GET", f"/applications?$filter=displayName eq '{name}'")["value"][0]
    roles = app["appRoles"]
    role = next((r for r in roles if r["value"] == ROLE), None)
    if role is None:
        role = {"id": str(uuid.uuid4()), "value": ROLE, "displayName": ROLE, "isEnabled": True,
                "allowedMemberTypes": ["Application"],
                "description": "Call the models this gateway serves (production: APIM)"}
        graph("PATCH", f"/applications/{app['id']}", {"appRoles": roles + [role]})
        roles = roles + [role]
        print(f"{name}: added {ROLE}")
    sp = graph("GET", f"/servicePrincipals?$filter=appId eq '{app['appId']}'")["value"][0]
    assigned = graph("GET", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo?$top=999")["value"]
    value = {r["id"]: r["value"] for r in roles}
    held: dict[str, set] = {}
    for a in assigned:
        held.setdefault(a["principalId"], set()).add(value.get(a["appRoleId"], ""))
    names = {a["principalId"]: a["principalDisplayName"] for a in assigned}
    agents = {pid for pid, vals in held.items() if vals - FRONT_DOOR - {ROLE}}
    for a in assigned:
        if a["appRoleId"] == role["id"] and a["principalId"] not in agents:
            graph("DELETE", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo/{a['id']}")
            print(f"revoked {ROLE} <- {a['principalDisplayName']} (front door only)")
    for pid in sorted(agents, key=names.__getitem__):
        if ROLE not in held[pid]:
            graph("POST", f"/servicePrincipals/{sp['id']}/appRoleAssignedTo",
                  {"principalId": pid, "resourceId": sp["id"], "appRoleId": role["id"]})
            print(f"granted {ROLE} -> {names[pid]}")
    print(f"{ROLE}: held by {', '.join(sorted(names[p] for p in agents))}")


if __name__ == "__main__":
    main()
