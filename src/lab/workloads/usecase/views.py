"""The CAFÉ views a use case is drawn as — built from the step outputs, rendered by semantic-mcp.

Where each one sits is the CAFÉ bundle's README (29 Sep 2026): the capability heatmap at step 5,
the realisation heatmap at 6, the ontology graph at 9, the BPMN flow at 10, the scoped reference
architecture at 22. They REPLACED the ArchiMate views and the draw.io projection (user decision the
same day: the EA artifacts are gone; the model the run grows stays, internal, for step 21).

Two halves. The mappers are pure — step outputs in, view inputs out — and they are the pipeline's
own judgement about what a reviewer sees, so they are tested on the shapes the steps emit. The
renders call the governed tools under the run's pin and are BEST EFFORT: a run that cannot draw is
still a run, so every failure is a named warning on the record, never an exception.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from lab.core.usecase.views import tables as view_tables
from lab.core.usecase.views.inputs import (_rows, capability_input, ontology_input,  # noqa: F401
                                          realisation_input, workflow_spec)
from lab.platform.contracts import SemanticTools
from lab.workloads import gateway
from lab.workloads.usecase import reference

__all__ = ["DESIGN", "LOGICAL_ARCHITECTURE", "PHYSICAL_ARCHITECTURE", "SCREENING", "artifacts", "capability_input", "ontology_input", "realisation_input",
           "render_design", "render_screening", "workflow_spec"]

#: Which views each half draws, by the renderer's name — so each half pins exactly their tables.
SCREENING = ("capability_heatmap", "realisation_heatmap", "ontology_graph", "bpmn")
DESIGN = ("scoped_architecture",)


def artifacts(views, *, exclude=()) -> tuple[str, ...]:
    """What `views` read, in order, less what the run already pins — the OPTIONAL part of a pin:
    a table not released costs a picture, never the run."""
    return tuple(dict.fromkeys(t for v in views for t in view_tables.artifacts_for(v) if t not in exclude))


#: The tab labels step 22's pages are filed under. The LOGICAL one is also the design's declared
#: `architecture_ref` product, so it is named once, here, and read by name — never re-spelled.
LOGICAL_ARCHITECTURE = "22 · logical architecture"
PHYSICAL_ARCHITECTURE = "22 · physical architecture"


# ---------------------------------------------------------------- the renders (best effort)

async def _render(cfg, tool: str, args: dict, field: str, out: dict, take) -> None:
    try:
        res = await gateway.call(cfg, tool, {**args, **reference.attribution(cfg, field)})
        # An MCP result can arrive as its JSON TEXT (AF #3313); read that, never mistake it for none.
        res = res if isinstance(res, dict) else json.loads(res or "{}")
        drawn = take(res)
        if not drawn:
            out["warnings"].append(f"{field}: the tool answered with no page")
        out["view_refs"].update(drawn)
        unresolved = (res.get("summary") or {}).get("unresolved") or ()
        if unresolved:
            out["warnings"].append(f"{field}: not on the pinned map — {', '.join(map(str, unresolved))[:160]}")
    except Exception as exc:                       # noqa: BLE001 — a view is never worth a run
        out["warnings"].append(f"{field}: {type(exc).__name__}: {str(exc)[:160]}")


def _html(label: str):
    return lambda r: {label: r["html_ref"]} if r.get("html_ref") else {}


async def render_screening(cfg, derived: Mapping[str, Any], pin_id: str, *, title: str = "",
                           use_case: str = "") -> dict:
    """Steps 5, 6, 9 and 10, each drawn once its step produced something."""
    out: dict[str, Any] = {"view_refs": {}, "warnings": []}
    head = {"pin_id": pin_id, "title": title, "use_case": use_case}
    coverage = derived.get("coverage_map")
    if coverage:
        await _render(cfg, SemanticTools.view_capabilities,
                      {**head, "capabilities": capability_input(coverage)},
                      "capability_view", out, _html("5 · capabilities"))
        if derived.get("realisation_match"):
            await _render(cfg, SemanticTools.view_realisations,
                          {**head, "realisations": realisation_input(coverage, derived["realisation_match"])},
                          "realisation_view", out, _html("6 · realisations"))
    if derived.get("ontology_delta"):
        await _render(cfg, SemanticTools.view_ontology, {**head, **ontology_input(derived["ontology_delta"])},
                      "ontology_view", out, _html("9 · ontology"))
    spec = workflow_spec(derived.get("workflow_graph"), coverage, title=title)
    if spec:
        await _render(cfg, SemanticTools.view_workflow, {"pin_id": pin_id, "spec": spec},
                      "workflow_view", out, _html("10 · workflow"))
    return out


async def render_design(cfg, derived: Mapping[str, Any], pin_id: str, *, carried: Mapping[str, str],
                        title: str = "", use_case: str = "") -> dict:
    """Step 22's two scoped views from step 21's selection, after the screening's views — so the
    package a reviewer opens carries every view of the use case, in step order."""
    out: dict[str, Any] = {"view_refs": dict(carried), "warnings": []}
    components = [str(c.get("component_id")) for c in _rows(derived.get("component_selection"), "selected")
                  if c.get("component_id")]
    if components:
        await _render(cfg, SemanticTools.view_architecture,
                      {"pin_id": pin_id, "title": title, "use_case": use_case, "components": components},
                      "architecture_view", out,
                      lambda r: {k: v for k, v in ((LOGICAL_ARCHITECTURE, r.get("logical_ref")),
                                                   (PHYSICAL_ARCHITECTURE, r.get("physical_ref"))) if v})
    else:
        out["warnings"].append("architecture_view: step 21 selected no component, so there is no scope to draw")
    return out
