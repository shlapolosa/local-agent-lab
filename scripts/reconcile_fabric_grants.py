"""Re-apply the fabric teams' MCP grants WITHOUT touching any Entra registration or secret.

`provision_fabric_agents.py` creates the fabric's agents and, as a side effect of `ensure_agent`, adds a
fresh client secret to each on every run. When all that changed is a GRANT table (a new tool such as
`semantic_vocab_resolve`, the curator's `storage_read_artifact`), re-running it would rotate three
credentials for nothing. This applies only the teams' tool grants, from the same tables.

Usage: set -a && source .env && set +a && GATEWAY_URL=$PUBLIC_GATEWAY_URL \\
       .venv/bin/python scripts/reconcile_fabric_grants.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    from provision_fabric_agents import BOT_TOOLS, CURATOR_TOOLS, INTAKE_TOOLS, PUBLISH_TOOLS
    from provision_meeting_agents import _reconcile
    from provision_visio_agents import litellm

    teams = (("FABRIC_TEAM_ID", "fabric-intake", INTAKE_TOOLS),
             ("FABRIC_PUBLISH_TEAM_ID", "fabric-publish", PUBLISH_TOOLS),
             ("FABRIC_CURATOR_TEAM_ID", "fabric-curator", CURATOR_TOOLS),
             ("FABRIC_BOT_TEAM_ID", "fabric-bot", BOT_TOOLS))
    missing = [env for env, _, _ in teams if not os.environ.get(env)]
    if missing:
        sys.exit(f"not provisioned yet ({', '.join(missing)}) — run scripts/provision_fabric_agents.py once")
    for env, alias, tools in teams:
        _reconcile(litellm, os.environ[env], alias, tools)
        print(f"{alias}: " + "; ".join(f"{server}: {len(allowed)} tools" for server, allowed in sorted(tools.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
