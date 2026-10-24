"""How inputs are shown to the modelling agent so it can cite them.

Each input gets a short key (S1, S2, ...): a model copies `S1` reliably and an `art://<uuid>/<name>`
ref much less so. Prose is numbered by paragraph (`[¶n]`), so a citation can say WHERE. The marker
is not part of the source text, so a quote that includes it will not ground, which is correct.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

from lab.core.modelling.provenance import Source

__all__ = ["keyed", "message", "numbered"]

_BLANK = re.compile(r"\n\s*\n")


def numbered(text: str | None) -> str:
    """Prefix every paragraph (blank-line separated) with `[¶n] `, numbered from 1."""
    paras = [p.strip() for p in _BLANK.split(text or "") if p.strip()]
    return "\n\n".join(f"[¶{i}] {p}" for i, p in enumerate(paras, 1))


def keyed(sources: Sequence[Source]) -> dict[str, Source]:
    """`{"S1": first, "S2": second, ...}` in input order."""
    return {f"S{i}": s for i, s in enumerate(sources, 1)}


def message(sources: Mapping[str, Source]) -> str:
    """The agent's message: every input under its key. A source with no text (an image) is named,
    and its pixels travel as an attachment beside this message."""
    parts = [f"## {key} — {s.name}\n\n" + (numbered(s.text) if s.text is not None
                                           else "(attached as an image; read it with vision)")
             for key, s in sources.items()]
    return ("# Inputs\n\n" + "\n\n".join(parts)
            + "\n\nModel the architecture these inputs describe, as one JSON object.")
