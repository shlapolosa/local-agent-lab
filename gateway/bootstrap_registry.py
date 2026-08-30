"""Bootstrap the lab's agent registry on the LiteLLM gateway (Agent 365 analogue).

One team per business process, one virtual key per agent. Master key is used ONLY
here (admin plane); agents get their scoped virtual keys and never see it.
Idempotent-ish: re-running creates new keys — run once, store keys in .env.

Usage: set -a && source .env && set +a && .venv/bin/python gateway/bootstrap_registry.py
"""
import json
import os
import urllib.request

GW = "http://127.0.0.1:4000"
MASTER = os.environ["LITELLM_MASTER_KEY"]


def call(path, body):
    req = urllib.request.Request(
        GW + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# --- team: EA modelling process (rollup unit for spend/tokens/tools) ---
team = call("/team/new", {
    "team_alias": "ea-modelling",
    "max_budget": 5.0,            # USD per month across the whole process
    "budget_duration": "30d",
    "models": ["gpt-oss-120b", "glm-flash"],
})
team_id = team["team_id"]
print("team ea-modelling:", team_id)

# --- virtual key: the EA Modeling Agent (1:1 with future Entra app reg + A2A card) ---
key = call("/key/generate", {
    "key_alias": "ea-modeling-agent",
    "team_id": team_id,
    "models": ["gpt-oss-120b", "glm-flash"],
    "max_budget": 2.0,            # USD, per-agent slice of the team budget
    "budget_duration": "30d",
    "rpm_limit": 30,
    "tpm_limit": 60000,
    "metadata": {"role": "EA Modeling Agent",
                 "entra_app_registration": "pending",
                 "a2a_card": "pending"},
})
print("virtual key (store as EA_AGENT_KEY in .env):", key["key"])
