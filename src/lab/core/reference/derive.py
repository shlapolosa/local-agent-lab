"""Deriving an artifact's agent-readable form from its human-readable master.

DR-02: the two forms are the same artifact at the same version, and divergence is a defect rather
than a lag. That is only enforceable if the derivation is DETERMINISTIC — re-running it on
unchanged content must produce byte-identical output and identical ids, or a re-publish silently
invents a new version and every citation into the old one stops resolving.

Two kinds, because exact lookup and semantic retrieval are different problems:

* **Records** — the ~20 derivation artifacts (predicates, registers, matrices, price lines). Keyed
  on the artifact's declared NATURAL key, so a re-publish that corrects a typo in a body field
  keeps the row's id and every citation to it.
* **Passages** — the 5 explanatory artifacts. Split on headings FIRST and packed second, because a
  citation must point at something a person can find in the master. The anchor is therefore the
  heading path; a byte offset survives no edit at all.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from lab.core.semantic.ids import content_id

__all__ = [
    "DerivationError", "DerivedPassage", "DerivedRecord",
    "chunk", "content_digest", "passages", "records",
]

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
DEFAULT_TARGET_TOKENS = 500
DEFAULT_OVERLAP = 0.15


class DerivationError(ValueError):
    """The master could not be turned into an agent-readable form we would stand behind."""


@dataclass(frozen=True)
class DerivedPassage:
    text: str
    heading_path: tuple[str, ...]
    ordinal: int
    passage_id: str = ""

    @property
    def anchor(self) -> str:
        """What a citation points at, and what a person searches the master for."""
        return " > ".join(self.heading_path)


@dataclass(frozen=True)
class DerivedRecord:
    record_id: str
    key: Mapping[str, Any]
    body: Mapping[str, Any]


# ---------------------------------------------------------------- passages

def _sections(text: str) -> list[tuple[tuple[str, ...], str]]:
    """(heading path, body) per section, headings accumulating down the levels."""
    out: list[tuple[tuple[str, ...], str]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    path: tuple[str, ...] = ()

    def flush() -> None:
        joined = "\n".join(body).strip()
        if joined:
            out.append((path, joined))
        body.clear()

    for line in text.splitlines():
        heading = _HEADING.match(line)
        if not heading:
            body.append(line)
            continue
        flush()
        level = len(heading.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading.group(2)))
        path = tuple(title for _, title in stack)
    flush()
    return out


def _pack(body: str, target_tokens: int, overlap: float) -> list[str]:
    """Paragraphs packed to roughly `target_tokens`, with a tail of the previous chunk repeated.

    Whitespace-delimited words stand in for tokens: this decides chunk boundaries, not a budget
    anyone is billed for, and a real tokeniser would tie the derivation to a model version."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        words = len(paragraph.split())
        if current and size + words > target_tokens:
            chunks.append("\n\n".join(current))
            tail = " ".join(chunks[-1].split()[-max(1, int(target_tokens * overlap)):])
            current, size = ([tail] if overlap else []), len(tail.split())
        current.append(paragraph)
        size += words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk(text: str, *, target_tokens: int = DEFAULT_TARGET_TOKENS,
          overlap: float = DEFAULT_OVERLAP) -> list[DerivedPassage]:
    """Split a master into passages. Structural first, packed second, never across a heading."""
    if not (text or "").strip():
        raise DerivationError("the master is empty — an artifact that derives no passages would "
                              "pass any 'is it indexed' check the moment one was relaxed")
    out: list[DerivedPassage] = []
    for path, body in _sections(text):
        for piece in _pack(body, target_tokens, overlap):
            out.append(DerivedPassage(text=piece, heading_path=path, ordinal=len(out)))
    if not out:
        raise DerivationError("the master holds headings but no body text to index")
    return out


def passages(artifact_id: str, text: str, **kwargs: Any) -> list[DerivedPassage]:
    """Passages with stable ids.

    The id is content-addressed on the artifact, the anchor and the TEXT — not on the ordinal, so
    inserting a new section leaves every existing passage's id alone and citations into untouched
    parts of the artifact keep resolving across a re-publish."""
    return [
        DerivedPassage(text=p.text, heading_path=p.heading_path, ordinal=p.ordinal,
                       passage_id=content_id("psg-", artifact_id, p.anchor, p.text))
        for p in chunk(text, **kwargs)
    ]


# ---------------------------------------------------------------- records

def records(artifact_id: str, rows: Sequence[Mapping[str, Any]], *,
            key_fields: Sequence[str]) -> list[DerivedRecord]:
    """Rows keyed on the artifact's declared natural key, body kept verbatim.

    Keying on the natural key rather than the whole row is what lets a correction to a body field
    keep the row's identity — otherwise fixing a typo orphans every citation to it. Two rows
    sharing a key refuse: an exact lookup that silently returned one of them would be worse than a
    failed one, which is the whole reason this side of the corpus is not semantic."""
    out: list[DerivedRecord] = []
    seen: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        missing = [f for f in key_fields if not str(row.get(f, "")).strip()]
        if missing:
            raise DerivationError(f"{artifact_id}: a row is missing its key field(s) {missing}; "
                                  f"row keys are {sorted(row)}")
        key = {f: row[f] for f in key_fields}
        record_id = content_id("rec-", artifact_id, _canonical(key))
        if record_id in seen:
            raise DerivationError(
                f"{artifact_id}: two rows share the natural key {key} — an exact lookup cannot "
                f"choose between them, and returning either silently is worse than failing")
        seen[record_id] = row
        out.append(DerivedRecord(record_id=record_id, key=key, body=row))
    return out


# ---------------------------------------------------------------- the digest

def _canonical(value: Any) -> str:
    """One byte-form per value, whatever order a dict happened to be built in."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def content_digest(entries: Sequence[Any]) -> str:
    """A digest over the derived content, for the signed manifest.

    Order-sensitive across entries on purpose: a price sheet's line order is part of what was
    signed, and two artifacts holding the same rows in a different order are not the same artifact.
    """
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(_canonical(entry).encode("utf-8"))
        digest.update(b"\x1e")           # a record separator, so concatenation cannot collide
    return digest.hexdigest()
