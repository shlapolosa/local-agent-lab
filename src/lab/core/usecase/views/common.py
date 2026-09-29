"""What the CAFÉ views share: the impact statuses and their colours, and resolving retired ids.

Ported from the CAFÉ skills bundle's `cafe_common.py` (29 Sep 2026). What was left behind is what
does not belong in the domain core: reading the workbook (a view reads the corpus under the run's
pin, handed in as `data`) and driving a headless browser (a view is its HTML; a PNG is a later,
separate renderer — user decision 29 Sep 2026).

`data` keeps the bundle's shape, `{section: {"version": str, "tables": {table_id: [row, ...]}}}`,
with the sections the renderers name: `tech`, `real`, `ra`, `ontology`. The table ids ARE the
corpus's artifact ids — the workbook's marker rows name both — so a view reads published records
with no mapping in between.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Mapping

__all__ = ["EDGE", "FILL", "TAG", "ViewError", "esc", "norm_status", "retired_map", "script_json",
           "section"]

esc = _html.escape


class ViewError(ValueError):
    """The input cannot be drawn — an unknown status, a reference to nothing. Raised, never guessed."""


STATUS_ALIASES = {'missing': 'missing', 'gap': 'missing', 'red': 'missing',
                  'new': 'new', 'green': 'new',
                  'consumed': 'consumed', 'reused': 'consumed', 'existing': 'consumed',
                  'updated': 'updated', 'changed': 'updated', 'extended': 'updated', 'amber': 'updated'}
FILL = {'new': '#bfe6c6', 'consumed': '#ffd98c', 'updated': '#ffd98c', 'missing': '#f5b1b1'}
EDGE = {'new': '#1e7b34', 'consumed': '#a86b00', 'updated': '#a86b00', 'missing': '#b3261e'}
TAG = {'new': 'NEW', 'consumed': 'C', 'updated': 'U', 'missing': 'MISSING'}


def norm_status(s) -> str:
    v = STATUS_ALIASES.get(str(s or '').strip().lower())
    if not v:
        raise ViewError(f"unknown status '{s}' — use missing, new, consumed or updated")
    return v


def retired_map(rows, key='retired', to='resolves_to') -> dict:
    m = {}
    for r in rows or []:
        tgt = str(r.get(to) or '')
        mm = re.match(r'([A-Z]{2,4}\.\d{2}|[A-Z]{2,3}-\d{2}|cmp-[0-9a-f]{10})', tgt)
        m[str(r.get(key))] = mm.group(1) if mm else None
    return m


def section(version: str, tables: Mapping[str, list]) -> dict:
    """One `data` section, as the renderers read it."""
    return {"version": str(version or "unversioned"), "tables": {k: list(v or ()) for k, v in tables.items()}}


def script_json(value: Any) -> str:
    """JSON safe to place INSIDE a <script> element. The data carries model-written text (notes,
    definitions), and `</script>` in any of it would end the element and run what follows — so
    every `<`, `>` and `&` is escaped the way JSON allows and HTML does not parse."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
