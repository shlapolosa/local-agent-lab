"""How inputs are shown to the modelling agent so it can cite them.

Each input gets a short key (S1, S2, ...): a model copies `S1` reliably and an `art://<uuid>/<name>`
ref much less so. Prose is numbered by paragraph (`[¶n]`), so a citation can say WHERE. The marker
is not part of the source text, so a quote that includes it will not ground, which is correct.
"""
from __future__ import annotations

import re
from typing import Sequence

from lab.core.modelling.provenance import Source

__all__ = ["keyed", "numbered"]

_BLANK = re.compile(r"\n\s*\n")


def numbered(text: str | None) -> str:
    """Prefix every paragraph (blank-line separated) with `[¶n] `, numbered from 1."""
    paras = [p.strip() for p in _BLANK.split(text or "") if p.strip()]
    return "\n\n".join(f"[¶{i}] {p}" for i, p in enumerate(paras, 1))


def keyed(sources: Sequence[Source]) -> dict[str, Source]:
    """`{"S1": first, "S2": second, ...}` in input order."""
    return {f"S{i}": s for i, s in enumerate(sources, 1)}
