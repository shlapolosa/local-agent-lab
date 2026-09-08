"""Provision identity + governance for the four use-case intake workloads.

Two teams, split by GRANT PROFILE rather than by process. The four specs are one business
capability cut at its human gates, so four teams would duplicate one set of grants four times and
make the security boundary harder to read, not easier. What actually differs is what each half may
DO — and that is exactly the line the teams are drawn on:

  usecase-intake      screening + design. Reads the governed corpus and the derivations, reads the
                      capability map and the ontology, persists its own records. On workflow_mcp it
                      holds `approvals_ask` ONLY: it may ASK a human a question and may not answer
                      one, because an agent approving its own run defeats the gate entirely.
  usecase-delivery    investment + provisioning. The write path. It never asks a question it could
                      then answer either, and it holds NOTHING on decision_mcp or reference_mcp:
                      by the time it runs, every derivation is already made and approved.

CR-20 ("no work item or catalog entry created before architect approval") is enforced HERE, as a
grant. No process before provisioning is given a write tool at all, so there is no branch anybody
could take the wrong way — a control expressed as an ACL cannot be reasoned around by a model.

Creates the Entra apps, the teams with those per-tool ACLs, and the keys; then patches .env with
USECASE_AGENT_*, USECASE_DELIVERY_*, the team ids and the appId->key entries. Idempotent: reuses
apps found by display name and RECONCILES the grants of a team that already exists.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_usecase_agents.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab.platform.contracts import (ApprovalTools, DecisionTools, ReferenceTools,  # noqa: E402
                                    SemanticTools, StorageTools, USE_CASE_SCREENING,
                                    WorkflowTools)


def _helpers():
    """The visio script's Graph + LiteLLM helpers. Imported LAZILY because that module reads the
    environment at import, and the grant tables below must stay readable — and testable — without a
    tenant."""
    from provision_visio_agents import ensure_agent, ensure_sp, find_app, litellm, _patch_env
    return ensure_agent, ensure_sp, find_app, litellm, _patch_env


# The grants, spelled from the CONTRACT so a renamed tool breaks provisioning rather than silently
# granting nothing — a key with no grant sees zero tools, which looks exactly like a broken server.
INTAKE_TOOLS = {
    StorageTools.SERVER: [StorageTools.get, StorageTools.info, StorageTools.read_document,
                          StorageTools.read_artifact],
    # `store_spec` is how a workload with no store credential persists anything at all; the other
    # two are for loading a derived model into the semantic layer. `concepts` and `ontologies` are
    # the CORPORA the screening exercises read.
    SemanticTools.SERVER: [SemanticTools.store_spec, SemanticTools.concepts,
                           SemanticTools.ontologies, SemanticTools.describe],
    # The deterministic derivations. Read-only, and the whole catalogue: a run that could compute
    # its exposure but not its obligations would produce a design package with a hole in it.
    DecisionTools.SERVER: sorted(DecisionTools.names()),
    # The governed corpus, READ side only. `consumers` is the reverse index and spans runs — an
    # audit question, not a derivation one, so it is deliberately absent here.
    ReferenceTools.SERVER: list(ReferenceTools.READ),
    WorkflowTools.SERVER: list(ApprovalTools.RAISE),      # ask, never answer
}

DELIVERY_TOOLS = {
    StorageTools.SERVER: [StorageTools.get, StorageTools.info, StorageTools.read_artifact],
    SemanticTools.SERVER: [SemanticTools.store_spec],
    WorkflowTools.SERVER: list(ApprovalTools.RAISE),
}

#: What a caller outside the lab may start. `verbs_for`, not VERBS: three of the four processes are
#: continuations with no submit tool, and a grant naming one would name a tool the server does not
#: expose. Nothing to grant is not the same as granting nothing — the first is a typo the gateway
#: cannot report, the second looks like a broken server.
SUBMITTER_TOOLS = {
    WorkflowTools.SERVER: [USE_CASE_SCREENING.tool(v)
                           for v in WorkflowTools.verbs_for(USE_CASE_SCREENING)]
                          + list(ApprovalTools.READ) + list(ApprovalTools.WRITE),
}


def _grants(tools):
    """The `object_permission` for a per-tool ACL. `mcp_servers` alone would grant EVERY tool on the
    server, including ones added later, so the two always travel together."""
    return {"mcp_servers": sorted(tools), "mcp_tool_permissions": tools}


def _team(litellm, alias, tools, budget=5.0, models=("kimi-k3", "glm-flash")):
    return litellm("/team/new", {
        "team_alias": alias, "max_budget": budget, "budget_duration": "30d",
        "models": list(models), "object_permission": _grants(tools),
    })["team_id"]


def _reconcile(litellm, team_id, alias, tools):
    """Make an EXISTING team's grants match the table above.

    Never merely reused: the tables are the declaration and this is what applies them. The meeting
    script learned this the expensive way — a team created before `collab_put` was granted kept the
    old ACL because its id was already in `.env`, and the workload failed at its last step having
    produced correct minutes, while provisioning printed "Grants written" and had written nothing.
    """
    litellm("/team/update", {"team_id": team_id, "object_permission": _grants(tools)})
    return team_id


def _key(litellm, alias, team_id, role, models=("kimi-k3",)):
    return litellm("/key/generate", {
        "key_alias": alias, "team_id": team_id, "models": list(models),
        "max_budget": 5.0, "budget_duration": "30d", "rpm_limit": 60, "tpm_limit": 240000,
        "metadata": {"role": role, "entra_app_registration": alias},
    })["key"]


def main() -> int:
    ensure_agent, ensure_sp, find_app, litellm, _patch_env = _helpers()
    gw_app = find_app("lab-gateway")
    if not gw_app:
        raise SystemExit("lab-gateway app not found — run scripts/entra_provision.py first")
    gw_sp = ensure_sp(gw_app["appId"])

    # One app registration per grant profile. The nine screening agents share the intake identity
    # today; `host._credential_for(service)` is the seam that gives each bounded context its own
    # when the six registrations land, and nothing above it changes when they do.
    intake_id, intake_secret = ensure_agent("usecase-agent", [], gw_sp)
    delivery_id, delivery_secret = ensure_agent("usecase-delivery-agent", [], gw_sp)

    def team(env_key, alias, tools, **kw):
        existing = os.environ.get(env_key)
        return (_reconcile(litellm, existing, alias, tools) if existing
                else _team(litellm, alias, tools, **kw))

    intake_team = team("USECASE_TEAM_ID", "usecase-intake", INTAKE_TOOLS)
    delivery_team = team("USECASE_DELIVERY_TEAM_ID", "usecase-delivery", DELIVERY_TOOLS)
    submitter_team = team("USECASE_SUBMITTER_TEAM_ID", "usecase-submitter", SUBMITTER_TOOLS,
                          budget=1.0, models=())

    patch = {"USECASE_TEAM_ID": intake_team,
             "USECASE_DELIVERY_TEAM_ID": delivery_team,
             "USECASE_SUBMITTER_TEAM_ID": submitter_team,
             "USECASE_AGENT_CLIENT_ID": intake_id, "USECASE_AGENT_CLIENT_SECRET": intake_secret,
             "USECASE_DELIVERY_CLIENT_ID": delivery_id,
             "USECASE_DELIVERY_CLIENT_SECRET": delivery_secret}

    keys = {}
    for env_key, alias, team_id, role in (
            ("USECASE_AGENT_KEY", "usecase-agent", intake_team, "screening and design"),
            ("USECASE_DELIVERY_KEY", "usecase-delivery-agent", delivery_team,
             "investment and provisioning")):
        if os.environ.get(env_key):
            print(f"{env_key} already set — keeping it")
            continue
        patch[env_key] = keys[alias] = _key(litellm, alias, team_id, role)

    # appId -> virtual key, so the gateway's custom auth maps an Entra JWT back to the same key and
    # a run authenticates either way with identical budgets, ACLs and spend.
    mapping = json.loads(os.environ.get("ENTRA_CLIENT_TO_KEY") or "{}")
    for app_id, alias in ((intake_id, "usecase-agent"), (delivery_id, "usecase-delivery-agent")):
        if alias in keys:
            mapping[app_id] = keys[alias]
    if mapping:
        patch["ENTRA_CLIENT_TO_KEY"] = f"'{json.dumps(mapping)}'"

    _patch_env(patch)
    print("\nGrants written:")
    for alias, tools in (("usecase-intake", INTAKE_TOOLS), ("usecase-delivery", DELIVERY_TOOLS),
                         ("usecase-submitter", SUBMITTER_TOOLS)):
        print(f"  {alias}")
        for server, granted in sorted(tools.items()):
            print(f"    {server}: {', '.join(sorted(granted))}")
    print("\nRestart the gateway so custom_auth reloads ENTRA_CLIENT_TO_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
