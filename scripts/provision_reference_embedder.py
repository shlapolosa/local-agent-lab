"""Mint the ONE virtual key the reference corpus embeds with, and record it in .env.

The corpus (reference-mcp at search time, the publisher at index time) embeds THROUGH the gateway
like every other model call: the OpenAI upstream credential lives in the gateway's environment
(`OPENAI_UPSTREAM_API_KEY`, litellm-config.yaml `text-embedding-3-large`) and the corpus holds a
virtual key allowed that one model and nothing else — so embedding spend is metered to an identity,
and a leaked corpus credential buys embeddings, not chat. No Entra app registration: this is a
SERVICE credential, like `MCP_SHARED_SECRET`, not an agent that acts on anybody's behalf.

Idempotent: a team named in .env is reconciled (its model list re-applied), a key already named in
.env is KEPT — reissuing would orphan the one every deployed service holds.

Usage: set -a && source .env && set +a && .venv/bin/python scripts/provision_reference_embedder.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TEAM_ALIAS = "reference-corpus"
KEY_ALIAS = "reference-embedder"


def main() -> int:
    from provision_usecase_agents import NO_STORES
    from provision_visio_agents import _patch_env, litellm

    model = os.environ.get("REFERENCE_EMBED_MODEL", "")
    if not model:
        raise SystemExit("REFERENCE_EMBED_MODEL is not set — name the gateway's embedding model "
                         "(litellm-config.yaml model_list) before minting a key for it")
    # Zero tools, no stores: the key exists to call ONE model. `mcp_servers: []` grants no server
    # and the store sentinel is spelled rather than omitted (an absent grant is an open one).
    permission = {"mcp_servers": [], "mcp_tool_permissions": {}, "vector_stores": list(NO_STORES)}
    patch = {}

    team_id = os.environ.get("REFERENCE_TEAM_ID")
    if team_id:
        litellm("/team/update", {"team_id": team_id, "models": [model],
                                 "object_permission": permission})
        print(f"team {TEAM_ALIAS} reconciled ({team_id})")
    else:
        team_id = litellm("/team/new", {
            "team_alias": TEAM_ALIAS, "max_budget": 2.0, "budget_duration": "30d",
            "models": [model], "object_permission": permission})["team_id"]
        patch["REFERENCE_TEAM_ID"] = team_id
        print(f"team {TEAM_ALIAS} created ({team_id})")

    if os.environ.get("REFERENCE_EMBED_KEY"):
        # Kept, and RECONCILED: the model it may call follows REFERENCE_EMBED_MODEL, so switching
        # the embedding upstream is a config change and not a new credential to distribute.
        litellm("/key/update", {"key": os.environ["REFERENCE_EMBED_KEY"], "models": [model]})
        print(f"REFERENCE_EMBED_KEY already set — kept, allowed {model}")
    else:
        key = litellm("/key/generate", {
            "key_alias": KEY_ALIAS, "team_id": team_id, "models": [model],
            "max_budget": 2.0, "budget_duration": "30d", "rpm_limit": 120, "tpm_limit": 2_000_000,
            "metadata": {"role": "reference-embedder", "service": "reference-mcp + publisher"},
        })["key"]
        patch["REFERENCE_EMBED_KEY"] = key
        print(f"key {KEY_ALIAS} minted")

    if patch:
        _patch_env(patch)
        print(f".env patched: {sorted(patch)} — re-upload LAB_ENV so the cloud corpus embeds too")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
