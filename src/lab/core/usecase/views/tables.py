"""Which published tables each CAFÉ view reads — the one place that says so.

A renderer reads `data[section]["tables"][table_id]`; the table ids are the corpus's artifact ids,
because the workbook's marker rows name both. So a caller reads exactly `artifacts_for(view)` under
its pin and hands the rows back through `assemble` — the substrate tool does it against
reference-mcp, the tests against the committed masters. A view whose table is missing refuses by
name, never draws a map with half its rows.
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping

from lab.core.usecase.views.common import ViewError, section

__all__ = ["OPTIONAL", "RECORD_TYPE", "SECTIONS", "VIEWS", "artifacts_for", "assemble", "required_for"]

#: section -> the tables it holds.
SECTIONS: dict[str, tuple[str, ...]] = {
    "tech": ("technology-capability-l1", "technology-capability-l2", "technology-capability-l3",
             "retired-capability-ids"),
    "real": ("ai-capability-map",),
    "ra": ("logical-building-blocks", "reference-architecture-components",
           "reference-architecture-patterns", "reference-architecture-principles",
           "reference-architecture-retired-components"),
    "ontology": ("ontology-concepts", "ontology-relationships", "ontology-modules",
                 "ontology-indicator-links"),
}

#: table -> the record type the corpus publishes it under. A read is by artifact AND type, as every
#: pinned read is; these are the types `scripts/publish_usecase_corpus.py` publishes.
RECORD_TYPE: dict[str, str] = {
    "technology-capability-l1": "technology-capability-l1",
    "technology-capability-l2": "technology-capability-l2",
    "technology-capability-l3": "technology-capability-l3",
    "retired-capability-ids": "retired-capability-id",
    "ai-capability-map": "capability",
    "logical-building-blocks": "logical-building-block",
    "reference-architecture-components": "component",
    "reference-architecture-patterns": "reference-architecture-pattern",
    "reference-architecture-principles": "reference-architecture-principle",
    "reference-architecture-retired-components": "reference-architecture-retired-component",
    "ontology-concepts": "ontology-concept",
    "ontology-relationships": "ontology-relationship",
    "ontology-modules": "ontology-module",
    "ontology-indicator-links": "ontology-indicator-link",
}

#: Tables a view draws WITHOUT: retirements, patterns, principles, modules and indicator links
#: enrich the page and their absence only thins it. Everything else is the view.
OPTIONAL = frozenset({"retired-capability-ids", "reference-architecture-patterns",
                      "reference-architecture-principles", "reference-architecture-retired-components",
                      "ontology-modules", "ontology-indicator-links"})

#: view -> the sections it reads.
VIEWS: dict[str, tuple[str, ...]] = {
    "capability_heatmap": ("tech",),
    "realisation_heatmap": ("tech", "real"),
    "scoped_architecture": ("ra", "tech"),
    "bpmn": ("tech",),
    "ontology_graph": ("ontology",),
}


def artifacts_for(view: str) -> tuple[str, ...]:
    if view not in VIEWS:
        raise ViewError(f"no view {view!r} — one of {sorted(VIEWS)}")
    return tuple(t for s in VIEWS[view] for t in SECTIONS[s])


def required_for(view: str) -> tuple[str, ...]:
    """What a pin MUST carry for `view` — the rest only enriches it."""
    return tuple(t for t in artifacts_for(view) if t not in OPTIONAL)


def assemble(view: str, rows: Callable[[str], Iterable[Mapping] | None],
             version: Callable[[str], str] = lambda _t: "") -> dict:
    """`data` for `view`, from `rows(table_id)` (None = not available) and each section's version,
    read off its first table. A required table that is not available refuses the view."""
    artifacts_for(view)                          # an unknown view refuses by name
    data: dict = {}
    for name in VIEWS[view]:
        tables, missing = {}, []
        for table in SECTIONS[name]:
            got = rows(table)
            if got is None:
                if table not in OPTIONAL:
                    missing.append(table)
                continue
            tables[table] = [dict(r) for r in got]
        if missing:
            raise ViewError(f"{view}: the pinned corpus does not carry {', '.join(missing)}")
        data[name] = section(version(SECTIONS[name][0]), tables)
    return data
