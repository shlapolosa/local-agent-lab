"""The published CAFÉ artifacts, as committed seed data.

Extracted from the framework's own artifact set by `scripts/extract_cafe_seed.py` and committed as
reviewed JSON, because a governed artifact must be diffable and signable. The extractor is a
generator run by hand; nothing here reads the HTML or the requirements docx at runtime.

This module is the read side and nothing more: it loads, it caches, and it answers the two
questions the domain asks of the corpus. Publication, versioning and signing belong to the
reference layer (`lab.core.reference`), which serves the same content under a version pin. This is
the local, always-available copy the deterministic algorithms are tested against.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

__all__ = ["SEED_DIR", "NAMED_CONDITIONS", "artifact", "guardrails", "live_guardrails", "names"]

SEED_DIR = Path(__file__).parent / "seed"

#: Prose terms in the published predicates that a facet vector cannot answer, so the CALLER must.
#: Step 19 knows what a step invokes, reads and delegates to; the facet schema does not record it.
#: Declared here rather than discovered, so a new condition arriving with a framework release is a
#: visible change rather than a guardrail that silently stops firing — the test that compares this
#: set against the corpus is what makes that true.
NAMED_CONDITIONS = frozenset({
    "step invokes any registered tool",
    "the step runs without an interactive user at trigger time",
    "step executes generated or supplied code",
    "step reads any grounding source",
    "the step delegates to another agent",
    "step invokes a downstream service",
    "the step reasons over or emits a named concept",
    "the step can conclude that nothing is wrong",
    "step reads any grounding source, tool output or agent response — any content the enterprise "
    "did not author",
})


@lru_cache(maxsize=None)
def artifact(name: str) -> dict:
    """One seed artifact by filename stem. Raises rather than returning {} — a missing governed
    artifact must fail closed, never look like an empty one."""
    path = SEED_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no seed artifact {name!r} in {SEED_DIR}; have {names()}")
    return json.loads(path.read_text(encoding="utf-8"))


def names() -> list[str]:
    return sorted(p.stem for p in SEED_DIR.glob("*.json"))


def guardrails() -> list[dict]:
    """Every guardrail the framework publishes, retired ones included."""
    return list(artifact("guardrails")["guardrails"])


def live_guardrails() -> list[dict]:
    """The guardrails that still fire. A retired identifier is never reused, so the retired ones
    stay in the corpus to keep old citations resolvable — but they must never enter a control set.
    """
    return [g for g in guardrails() if not g.get("rule", "").startswith("RETIRED")]
