"""A licensed capability WORKBOOK as a publishable master.

The BA Guild reference models arrive as `.xlsx` — the human-readable signed master IS the workbook
(what a citation opens), and the agent-readable form is derived from it by the same parser the
semantic layer uses (`lab.core.semantic.reference.baguild`), so the two cannot disagree about what
a row says. Nothing derived from a workbook is ever committed: the repository is public and the
models are licensed, so a workbook reaches the publisher by `art://` reference through the
private artifact store and leaves it as signed rows in the corpus.

The natural key is `(id, parent, level)` rather than `id` alone, and that is the whole design:
JSONB containment on the key is how an EXACT read asks the questions screening asks —
`{"parent": <id>}` for a node's children, `{"level": "1"}` for the top of the map — without a
second index or a second verb. `parent` is `-` for a root because a lookup cannot contain a
NULL. `path` is the full label path, which is what a relevance passage is made of.
"""
from __future__ import annotations

import io
from typing import Any

from lab.core.reference.master import Master
from lab.core.semantic.reference.baguild import parse

__all__ = ["HEADERS", "KEY_FIELDS", "ROOT", "TEXT_FIELDS", "capability_table"]

#: The published columns, in the order a person reads them in the master.
HEADERS = ("id", "parent", "level", "label", "path", "definition", "tier")
KEY_FIELDS = ("id", "parent", "level")
#: What a relevance passage says for one capability: where it sits, and what it means.
TEXT_FIELDS = ("path", "definition")
ROOT = "-"


def capability_table(source: bytes, *, scheme: str, title: str) -> Master:
    """The workbook's capability map as a table — one row per capability, hierarchy made explicit.

    Only the `capability` concepts: value streams, stakeholders and information concepts are other
    kinds the same workbook carries, and an artifact publishes ONE record type."""
    parsed = parse(io.BytesIO(source), scheme, title)
    concepts: dict[str, dict[str, Any]] = parsed.concepts
    rows: list[tuple[str, ...]] = []
    for concept in concepts.values():
        if concept.get("kind") != "capability":
            continue
        rows.append((concept["id"], concept.get("parent") or ROOT, str(concept["level"]),
                     concept["label"], " > ".join(_path(concepts, concept)),
                     concept.get("definition") or "",
                     "" if concept.get("tier") is None else str(concept["tier"])))
    return Master(title=title, headers=HEADERS, rows=tuple(rows),
                  meta={"Artifact": scheme, "Source": parsed.source or "workbook",
                        "Rendered": "derived from the workbook by lab.core.reference.workbook"})


def _path(concepts: dict[str, dict[str, Any]], concept: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    node: dict[str, Any] | None = concept
    while node is not None and node["id"] not in seen:
        seen.add(node["id"])
        labels.append(node["label"])
        node = concepts.get(node.get("parent") or "")
    return list(reversed(labels))
