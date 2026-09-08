"""Bootstrap the lab's agent registry on the LiteLLM gateway (Agent 365 analogue).

One team per business process, one virtual key per agent. Master key is used ONLY
here (admin plane); agents get their scoped virtual keys and never see it.

Two entry points, because they have opposite safety properties:

    python scripts/bootstrap_registry.py               # CREATE the ea-modelling team + agent key
    python scripts/bootstrap_registry.py developers    # RECONCILE the developers team (idempotent)

The first is run ONCE: `/team/new` and `/key/generate` create every time, so re-running mints
duplicates — store the printed key in .env and do not run it again. The second is safe to re-run and
is meant to be: it reconciles the `developers` team's model allowlist to whatever
`config/litellm-config.yaml` says, and reconciling is the whole point (see below).

Usage: set -a && source .env && set +a && .venv/bin/python scripts/bootstrap_registry.py [developers]
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

GW = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000")
MASTER = os.environ["LITELLM_MASTER_KEY"]
CONFIG = Path(__file__).resolve().parents[1] / "config" / "litellm-config.yaml"


def call(path, body):
    req = urllib.request.Request(
        GW + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def developer_models() -> list[str]:
    """The developer allowlist, READ FROM THE CONFIG rather than repeated here.

    The same list already exists in `litellm_settings.default_internal_user_params.models`, and a
    second copy would be a second thing to forget: the aliases were added to the config and the
    team kept its old list, so `/model` stayed wrong until the team was reconciled by hand.
    """
    import yaml
    cfg = yaml.safe_load(CONFIG.read_text())
    return list(cfg["litellm_settings"]["default_internal_user_params"]["models"])


def reconcile_developers_team() -> None:
    """Make the `developers` team's model allowlist match the config. Idempotent.

    WHY THIS EXISTS AT ALL. A JIT developer key is created with no `models` of its own, so what a
    signed-in developer can see and call is the TEAM's list — and that list lived only in the Neon
    database, created by hand and committed nowhere. Rebuild the database and it silently comes back
    narrower than the config says, with the only symptom being models missing from `/model`, which
    is exactly how this was found (measured 8 Sep 2026: the config listed 12, the team listed 7, and
    a developer identity saw 7).

    Reconcile rather than create, because the team already exists in every deployment that has one:
    `/team/new` would mint a second `developers` team and the JIT keys would keep pointing at the
    first.
    """
    models = developer_models()
    team_id = os.environ.get("DEVELOPERS_TEAM_ID")
    if not team_id:
        team = call("/team/new", {"team_alias": "developers", "models": models})
        print(f"team developers CREATED: {team['team_id']}")
        print("   store it as DEVELOPERS_TEAM_ID in .env — custom_auth needs it for JIT keys")
        return
    call("/team/update", {"team_id": team_id, "models": models})
    print(f"team developers reconciled: {team_id}")
    print(f"   {len(models)} models from {CONFIG.name}: {', '.join(models)}")


def bootstrap_ea_modelling() -> None:
    """CREATES a team and a key — run once, then store the key in .env."""
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "developers":
        reconcile_developers_team()
    else:
        bootstrap_ea_modelling()
