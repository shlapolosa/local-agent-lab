"""The two agents of the Visio->ArchiMate workflow, as Microsoft Agent Framework ChatAgents
pointed at the lab gateway. Each agent is pure structured-output (text -> JSON); in-agent
tool-calling is unreliable through the gateway (see CLAUDE.md / the spike), so all tool I/O runs
in the workflow's deterministic nodes, not here.

Instructions are composed from the greenfield prompts + method + the registered visio-reader
skill (single source of truth: the same SKILL.md registered in LiteLLM). The credential is the
agent's own Entra identity (MSAL JWT) or its durable virtual key — governance is identical either
way; spend attributes to the per-agent key.
"""
import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1] / ".claude" / "skills"
MODEL = os.environ.get("VISIO_AGENT_MODEL", "kimi-k3")


def _read(rel: str) -> str:
    return (HERE / rel).read_text()


def _strip_frontmatter(md: str) -> str:
    if md.lstrip().startswith("---"):
        return md.split("---", 2)[2].strip()
    return md


def ba_instructions() -> str:
    skill = _strip_frontmatter((SKILLS / "visio-reader" / "SKILL.md").read_text())
    return "\n\n".join([
        _read("prompts/ba.md"),
        "## Conversion method\n\n" + _read("references/method.md"),
        "## Visio-reading skill\n\n" + skill,
    ])


def architect_instructions() -> str:
    return "\n\n".join([
        _read("prompts/architect.md"),
        "## Conversion method\n\n" + _read("references/method.md"),
    ])


def make_agent(name: str, instructions: str, credential: str,
               traceparent: dict | None = None) -> Agent:
    """One ChatAgent -> gateway /v1 with the agent's own credential. `traceparent` (a dict of
    W3C headers) is sent as default_headers so the gateway's LLM spans join the run's trace."""
    client = OpenAIChatClient(
        model=MODEL, api_key=credential,
        base_url=os.environ["GATEWAY_URL"].rstrip("/") + "/v1",
        default_headers=dict(traceparent or {}))
    return Agent(client=client, name=name, instructions=instructions)
