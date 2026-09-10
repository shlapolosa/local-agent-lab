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
from typing import Any, Iterable, Mapping
from pathlib import Path

__all__ = ["SEED_DIR", "artifact", "guardrails", "live_guardrails", "names"]

SEED_DIR = Path(__file__).parent / "seed"

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


def live_only(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """The guardrails in these rows that still fire, whatever supplied them.

    A DOMAIN rule, applied at the point of use rather than at one source. It used to be folded into
    `live_guardrails()` and so protected only the packaged seed — the governed corpus publishes all
    26 guardrails (a retired identifier is never reused, and the retired ones must stay resolvable
    for old citations), so a run deriving from the corpus evaluated G11 and G12 and refused on a
    condition no live guardrail asks. The seeded path was unaffected, which is exactly why no test
    saw it.
    """
    return [dict(g) for g in rows if not str(g.get("rule", "")).startswith("RETIRED")]


def live_guardrails() -> list[dict]:
    """The guardrails that still fire. A retired identifier is never reused, so the retired ones
    stay in the corpus to keep old citations resolvable — but they must never enter a control set.
    """
    return live_only(guardrails())
