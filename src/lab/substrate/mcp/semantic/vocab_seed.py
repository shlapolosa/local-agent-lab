"""Seed the fabric's domain vocabulary from its MASTER — the file, never a copy in this repository.

The ontology is not in the governed corpus (nothing publishes it yet), so there is nothing to read there. It
arrives the way the licensed capability workbooks already do: a file the server materialises at start from an
`art://` ref, outside git. What is parsed is the master's own shape — a markdown table, which is exactly what the
corpus publisher consumes — so the bytes the fabric seeds from are the bytes an operator later publishes.

Two refusals rather than a partial answer: concepts without their relationships is a taxonomy pretending to be an
ontology, and a master whose edges name a concept it does not hold is a defect that must be seen, not skipped.
"""
from __future__ import annotations

from pathlib import Path

from lab.core.semantic.fabric.vocabulary import DomainScheme, build

__all__ = ["SCHEME", "CONCEPTS", "RELATIONSHIPS", "rows", "load"]

#: the scheme's name, and therefore its IRI base — one vocabulary the fabric owns, not one per source file
SCHEME = "cafe"
TITLE = "CAFÉ domain ontology"
CONCEPTS, RELATIONSHIPS = "ontology_concepts.md", "ontology_relationships.md"


def rows(text: str) -> list[dict]:
    """The first markdown table in `text`, as dicts keyed by its header. Cells are stripped; an empty cell is an
    empty string, because a master's blank means "not stated" and `None` would read as "unknown key"."""
    header: list[str] | None = None
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if header:                      # the table has ended; a master holds one table
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(set(c) <= {"-", ":"} and c for c in cells):
            continue                        # the ---|--- rule under the header
        out.append(dict(zip(header, cells)))
    return out


def _read(directory: str, name: str) -> list[dict] | None:
    path = Path(directory) / name
    return rows(path.read_text(encoding="utf-8")) if path.exists() else None


def load(directory: str, *, version: str = "") -> DomainScheme | None:
    """The scheme from the masters in `directory`, or None when the seed is absent — SAYING so, because a server
    that quietly serves no vocabulary is indistinguishable from one whose vocabulary matches nothing. The
    directory is INJECTED: this module reads no environment, so a test needs no monkeypatching and the setting
    has one home in `lab.platform.config`."""
    if not directory or not Path(directory).is_dir():
        print(f"[vocabulary] no ontology master directory ({directory or 'unset'}) — no domain scheme", flush=True)
        return None
    concepts = _read(directory, CONCEPTS)
    relations = _read(directory, RELATIONSHIPS)
    if concepts is None or relations is None:
        missing = CONCEPTS if concepts is None else RELATIONSHIPS
        print(f"[vocabulary] no ontology master {missing} in {directory} — no domain scheme", flush=True)
        return None
    scheme = build(name=SCHEME, title=TITLE, concepts=concepts, relationships=relations,
                   source=CONCEPTS, version=version)
    print(f"[vocabulary] seeded {SCHEME} {version or '(no version)'}: "
          f"{len(scheme.concepts)} concepts, {len(scheme.relationships)} relationships", flush=True)
    return scheme
