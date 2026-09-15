"""Finding a run somebody else started — ONE implementation, two surfaces.

A caller who did not submit a run has only the process name and what they remember about the use
case. The REST front door and the governed tool must answer that question identically, so the
filter, the field selection and the cap live here rather than once per surface.

Cheap by construction: one Redis read of the request stream's own order, filtered on what a run SAYS
about itself — its declared outputs, its subject, its status. Never on anything it would have to
open; a search that fetched every stored record would be a different feature wearing this one's name.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from lab.platform import workflows
from lab.platform.contracts import ProcessSpec

__all__ = ["MAX_LIMIT", "SCANNED", "search"]

MAX_LIMIT = 100
#: How far back the scan reads before filtering. The stream is capped and a use-case run is minutes
#: long, so this is weeks of history for the processes a person searches.
SCANNED = 200
#: Carried on every row, before the process's own outputs. `summary` and `trace_id` are deliberately
#: absent: one is a nested object nobody reads in a list, the other is for a trace viewer, not a
#: person looking for their use case.
HEAD = ("request_id", "status", "created_at", "finished_at")
SKIP = ("summary", "trace_id")


def rows(spec: ProcessSpec, *, q: str = "", limit: int = 20, client=None) -> list[dict]:
    """The runs of one process, newest first, each as what it says about itself."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    needle = str(q or "").strip().lower()
    out: list[dict] = []
    for state in workflows.recent(limit=SCANNED, client=client):
        if state.get("process") != spec.name:
            continue
        row: dict[str, Any] = {k: state.get(k) for k in HEAD if state.get(k)}
        row |= {k: state[k] for k in spec.outputs if state.get(k) is not None and k not in SKIP}
        if needle and needle not in json.dumps(row, default=str).lower():
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def search(spec: ProcessSpec, *, q: str = "", limit: int = 20, client=None) -> dict:
    """`rows` as both surfaces answer it."""
    found = rows(spec, q=q, limit=limit, client=client)
    return {"process": spec.name, "runs": found, "count": len(found),
            "query": str(q or "").strip(), "scanned": SCANNED}
