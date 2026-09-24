"""Which MCP tools each TEAM may call — one registry over the provisioning scripts' own tables.

The tables are declared where each process is provisioned (`scripts/provision_*_agents.py`) and spelled
from the contract. Development applies them to LiteLLM teams; production's APIM renders them into
policy (deploy/apim.py). This module only COLLECTS them under the team alias both targets use, so a
grant is written once and read by both — never copied.

A value of None means EVERY tool on that server: LiteLLM's reading of a server granted with no tool
list. Only the visio team holds one (ea_mcp and storage_mcp, from before per-tool ACLs existed).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

import provision_fabric_agents as fabric  # noqa: E402
import provision_meeting_agents as meeting  # noqa: E402
import provision_usecase_agents as usecase  # noqa: E402
from lab.platform.contracts import EATools, SemanticTools, StorageTools  # noqa: E402

#: The visio-conversion team's grant (applied by scripts/provision_visio_agents.py, which reads the
#: environment at import and so cannot be imported here).
VISIO_TOOLS: dict[str, list[str] | None] = {
    EATools.SERVER: None,
    StorageTools.SERVER: None,
    # semantic-mcp carries the fabric's WRITE tools: a modelling agent gets the read side only
    SemanticTools.SERVER: list(SemanticTools.READ),
}

TEAMS: dict[str, dict[str, list[str] | None]] = {
    "visio-conversion": VISIO_TOOLS,
    "usecase-intake": usecase.INTAKE_TOOLS,
    "usecase-delivery": usecase.DELIVERY_TOOLS,
    "usecase-submitter": usecase.SUBMITTER_TOOLS,
    "usecase-evals": usecase.EVALS_TOOLS,
    "meeting-transcript": meeting.TRANSCRIPT_TOOLS,
    "meeting-minutes": meeting.MINUTES_TOOLS,
    "power-automate": meeting.CONNECTOR_TOOLS,
    "fabric-intake": fabric.INTAKE_TOOLS,
    "fabric-publish": fabric.PUBLISH_TOOLS,
    "fabric-bot": fabric.BOT_TOOLS,
    "fabric-curator": fabric.CURATOR_TOOLS,
}


#: The callers that hold a KEY rather than an Entra identity — the variable that carries it, and its team.
#: In dev each is a LiteLLM virtual key; in production an APIM subscription on the team's product.
KEY_CALLERS: dict[str, str] = {
    "FABRIC_CURATOR_KEY": "fabric-curator",       # the fabric's substrate services (projector, reconciler)
    "FABRIC_BOT_KEY": "fabric-bot",               # the fabric's Copilot Studio agent
    "POWER_AUTOMATE_KEY": "power-automate",       # the meeting flows' connector
    "USECASE_SUBMITTER_KEY": "usecase-submitter",  # the use-case Copilot Studio agent
    "EVAL_AGENT_KEY": "usecase-evals",            # the coverage evals and adjudication (an operator harness)
    "REFERENCE_EMBED_KEY": "reference-corpus",    # the corpus publisher's embeddings
}

#: The models a key-holding team may call; a team absent here calls none. The embedder's is the
#: profile's REFERENCE_EMBED_MODEL, so it is supplied where the profile is read (deploy/apim.py).
KEY_MODELS: dict[str, tuple[str, ...]] = {
    "usecase-evals": tuple(usecase.EVALS_MODELS),
}


def role(team: str) -> str:
    """The Entra app role on the production gateway that carries `team`'s grant."""
    return f"Grant.{team}"


def for_server(server: str) -> dict[str, list[str] | None]:
    """team -> the tools it may call on `server` (None = all), for the teams granted that server."""
    return {team: tools[server] for team, tools in TEAMS.items() if server in tools}
