"""The registered skills' SKILL.md, composed into a system prompt — ONE reader for every workload.

A skill is registered in LiteLLM (`scripts/register_skill.sh`) and consumed by composing the same local
file into the agent's instructions: one source of truth, and no team-scoped injection to depend on."""
from __future__ import annotations

from lab.platform import config

SKILLS = config.REPO_ROOT / "skills"


def strip_frontmatter(md: str) -> str:
    """The body of a SKILL.md — the YAML frontmatter is for the registry, not the model."""
    if md.lstrip().startswith("---"):
        return md.split("---", 2)[2].strip()
    return md


def text(name: str) -> str:
    """The prompt text of the skill directory `skills/<name>`."""
    return strip_frontmatter((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))


__all__ = ["SKILLS", "strip_frontmatter", "text"]
