"""The human-readable master of a governed artifact, and reading it back.

DR-02 says the master and the agent-readable form are the same artifact at the same version, and
`derived_from = master_sha256` says the second was derived from the first. That is only TRUE if the
derivation actually happens — if a publisher hashed one file and independently emitted another, the
link would be an assertion, and an assertion is exactly what DR-02 refuses to accept ("divergence
is a defect, not a lag").

So the master is the source and this module is the round trip. `render` writes a markdown document
a person can open; `parse` reads it back into the same rows. The publisher hashes the master, parses
it, and derives records or passages from what came back — so the chain from master to index is
mechanical rather than promised, and `test_a_master_round_trips` is what keeps it that way.

Markdown because the master has to be readable by whoever owns the artifact — a risk officer opening
the criticality taxonomy should see a table, not JSON — and because a citation's `master_ref` points
here, so this is what a reviewer actually sees when they follow one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ["Master", "MasterError", "parse", "render"]

_META = re.compile(r"^\*\*(?P<key>[A-Za-z ]+):\*\*\s*(?P<value>.*)$")
_PIPE_ESCAPE = "&#124;"


class MasterError(ValueError):
    """The master is not a document this module can read back into rows."""


@dataclass(frozen=True)
class Master:
    title: str
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    meta: Mapping[str, str] = field(default_factory=dict)
    prose: str = ""

    @property
    def is_table(self) -> bool:
        return bool(self.headers)


def _cell(value: Any) -> str:
    """One cell, readable.

    A pipe would end the column, so it is escaped rather than dropped — a guardrail predicate
    legitimately contains `∨`, and one day one will contain `|`. A list is joined rather than
    repr'd: `['S2', 'S6']` in a document a risk officer opens is the machine leaking through, and
    the master exists to be read.
    """
    if value is None:
        text = ""
    elif isinstance(value, (list, tuple)):
        text = ", ".join(_cell(v) for v in value)
    else:
        text = str(value)
    return re.sub(r"\s*\n\s*", " ", text).replace("|", _PIPE_ESCAPE)


def render(*, title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]],
           meta: Mapping[str, str] | None = None, prose: str = "") -> str:
    """A markdown master: a title, the metadata a reader needs, and the rows as a table."""
    if not title.strip():
        raise MasterError("a master needs a title — it is what a citation opens")
    out = [f"# {title}", ""]
    for key, value in (meta or {}).items():
        out.append(f"**{key}:** {_cell(value)}")
    if meta:
        out.append("")
    if prose.strip():
        out += [prose.strip(), ""]
    if headers:
        out.append("| " + " | ".join(_cell(h) for h in headers) + " |")
        out.append("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            padded = list(row) + [""] * (len(headers) - len(row))
            out.append("| " + " | ".join(_cell(c) for c in padded[:len(headers)]) + " |")
        out.append("")
    return "\n".join(out)


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip().replace(_PIPE_ESCAPE, "|") for c in body.split("|")]


def parse(text: str) -> Master:
    """Read a master back. The inverse of `render` for everything `render` writes."""
    lines = (text or "").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise MasterError("a master starts with a level-1 heading naming the artifact")
    title = lines[0][2:].strip()

    meta: dict[str, str] = {}
    prose: list[str] = []
    headers: list[str] = []
    rows: list[tuple[str, ...]] = []
    in_table = False

    for line in lines[1:]:
        stripped = line.strip()
        matched = _META.match(stripped)
        if matched and not in_table:
            meta[matched.group("key")] = matched.group("value").replace(_PIPE_ESCAPE, "|")
            continue
        if stripped.startswith("|"):
            cells = _split_row(stripped)
            if all(set(c) <= set("-: ") and c for c in cells):
                in_table = True                      # the separator row
                continue
            (rows.append(tuple(cells)) if headers else headers.extend(cells))
            continue
        if stripped and not in_table:
            prose.append(stripped)

    return Master(title=title, headers=tuple(headers), rows=tuple(rows), meta=meta,
                  prose="\n".join(prose).strip())
