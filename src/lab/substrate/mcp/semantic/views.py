"""The CAFÉ views as governed tools — each reads its tables under the caller's pin, draws, and
stores the page by reference.

One tool per view the CAFÉ bundle's README places at a step: capabilities (step 5), realisations
(6), ontology (9), workflow (10), architecture (22). They replace `semantic_render_cafe`'s draw.io
projection of the ArchiMate model (user decision 29 Sep 2026: the use case is drawn as the CAFÉ
views, and the EA artifacts are gone).

The drawing is `lab.core.usecase.views` — pure, rows in, HTML out. What lives here is the rule
every governed read obeys (`pinned.rules`: no pin, no view; a pin LACKING a table the view needs
refuses, one lacking an enriching table draws without it) and the store. The inputs are small —
ids, statuses, a spec of a dozen nodes — so they travel inline; the page, which is large, goes to
the artifact store and only its ref comes back.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable

from fastmcp.exceptions import ToolError
from pydantic import Field

from lab.core.usecase.views import (bpmn, capability_heatmap, ontology_graph, realisation_heatmap,
                                    scoped_architecture, tables)
from lab.core.usecase.views.common import ViewError
from lab.platform.contracts import SemanticTools
from lab.platform.filetypes import content_type_for
from lab.substrate.mcp import pinned
from lab.substrate.mcpserver import LabServer, span

__all__ = ["register"]

PIN = Annotated[str, Field(description="The run's pin (reference_pin). A view reads the governed "
                                       "corpus under it and refuses without one.")]
RUN = Annotated[str, Field(description="The run the view is drawn for — recorded against the read.")]
PROCESS = Annotated[str, Field(description="The registered process the run belongs to.")]
FIELD = Annotated[str, Field(description="The derived field the read is attributed to "
                                         "(e.g. `capability_view`).")]
TITLE = Annotated[str, Field(description="The page title — the use case's problem, in a few words.")]
USE_CASE = Annotated[str, Field(description="The use case's id, printed under the title.")]
BASENAME = Annotated[str, Field(description="The stored file's name, without extension.")]


def _draw(server: LabServer, view: str, *, pin_id: str, run_id: str, process: str, field: str,
          draw: Callable[[dict], dict]) -> tuple[dict, dict]:
    """(what the renderer returned, provenance). Every refusal is a ToolError naming its cause."""
    table = {t: (t, tables.RECORD_TYPE[t]) for t in tables.artifacts_for(view)}
    rows, provenance = pinned.rules(
        server.reference(), pin_id, run_id, process, field, table=table, needs=list(table),
        reads=tables.required_for(view), optional=tables.OPTIONAL)
    versions = {v["artifact_id"]: v["version"] for v in provenance["versions"]}
    try:
        data = tables.assemble(view, rows.get, lambda t: versions.get(t, ""))
        return draw(data), provenance
    except (ViewError, KeyError, TypeError, AttributeError, ValueError) as exc:
        # A malformed input (a list where a word belongs, a null route) is REFUSED by name, not
        # surfaced as a crash inside a renderer the caller cannot see.
        raise ToolError(f"{view}: cannot draw this input — {type(exc).__name__}: {exc}") from exc


def _store(server: LabServer, name: str, html: str) -> str:
    return server.artifacts().put(name, html.encode("utf-8"), content_type_for(name))


def _answer(ref_fields: dict, out: dict, provenance: dict) -> dict:
    span().set_attributes({f"semantic.view.{k}": v for k, v in (out.get("summary") or {}).items()
                           if isinstance(v, (int, str)) and not isinstance(v, bool)})
    return {**ref_fields, "summary": out.get("summary") or {}, "rules_source": provenance}


def register(server: LabServer) -> None:
    @server.tool()
    def semantic_view_capabilities(
            capabilities: Annotated[list[dict], Field(description=(
                "Impacted technology L3s: {id, status: missing|new|consumed|updated, note?}; a "
                "capability NOT on the map is {name, parent_l2, status} and is drawn as a proposed "
                "block (a capability-map delta)."))],
            pin_id: PIN, run_id: RUN, process: PROCESS, field: FIELD = "capability_view",
            title: TITLE = "", use_case: USE_CASE = "", basename: BASENAME = "capabilities") -> dict:
        """Step 5's view: the whole technology capability map with every impacted L3 filled —
        red missing, green new, amber consumed (C) or updated (U) — and the rest faded. Stores
        one HTML page; returns `{html_ref, summary, rules_source}`. Unknown ids are listed on the
        page and under `summary.unresolved`, never dropped."""
        inp = {"title": title, "use_case": use_case, "capabilities": list(capabilities)}
        out, prov = _draw(server, "capability_heatmap", pin_id=pin_id, run_id=run_id,
                          process=process, field=field,
                          draw=lambda d: capability_heatmap.render(d, inp))
        return _answer({"html_ref": _store(server, f"{basename}.html", out["html"])}, out, prov)

    @server.tool()
    def semantic_view_realisations(
            realisations: Annotated[list[dict], Field(description=(
                "Shortlisted realisations: {id (L3), status: missing|new|consumed|updated, route?: "
                "microsoft|sovereign|alternative, product?, note?}."))],
            pin_id: PIN, run_id: RUN, process: PROCESS, field: FIELD = "realisation_view",
            title: TITLE = "", use_case: USE_CASE = "", basename: BASENAME = "realisations") -> dict:
        """Step 6's view: the realisation view with the shortlisted L3s filled by status and the
        chosen route marked ✔. UAE North availability shows as grey glyphs so the fill is the only
        colour. Returns `{html_ref, summary, rules_source}`."""
        inp = {"title": title, "use_case": use_case, "realisations": list(realisations)}
        out, prov = _draw(server, "realisation_heatmap", pin_id=pin_id, run_id=run_id,
                          process=process, field=field,
                          draw=lambda d: realisation_heatmap.render(d, inp))
        return _answer({"html_ref": _store(server, f"{basename}.html", out["html"])}, out, prov)

    @server.tool()
    def semantic_view_ontology(
            concepts: Annotated[list[dict], Field(description=(
                "Concepts the use case needs: {id (as in the ontology), status: matched|partial|"
                "enhancement|gap, note?}; a gap also gives {name, module, kind, definition}."))],
            pin_id: PIN, run_id: RUN, process: PROCESS,
            relationships: Annotated[list[dict] | None, Field(description=(
                "Relationships the use case adds or changes: {subject, predicate, object, "
                "status?}. Existing ones between matched concepts are added automatically."))] = None,
            field: FIELD = "ontology_view",
            title: TITLE = "", use_case: USE_CASE = "", basename: BASENAME = "ontology") -> dict:
        """Step 9's view: the ontology match as an interactive force-directed page (offline — the
        script is inlined). Green matched, amber partial or enhancement, red gap (the ontology
        delta), grey context. Returns `{html_ref, summary, rules_source}`."""
        inp = {"title": title, "use_case": use_case, "concepts": list(concepts),
               "relationships": list(relationships or ())}
        out, prov = _draw(server, "ontology_graph", pin_id=pin_id, run_id=run_id,
                          process=process, field=field, draw=lambda d: ontology_graph.render(d, inp))
        return _answer({"html_ref": _store(server, f"{basename}.html", out["html"])}, out, prov)

    @server.tool()
    def semantic_view_workflow(
            spec: Annotated[dict, Field(description=(
                "The flow: {title, lanes: [{id, label}], nodes: [{id, type: task|gateway|start|"
                "end|annotation, lane, cap?, name?, note?}], edges: [{from, to, type?, label?}]}. "
                "A task naming only `cap` (an L3 id) is labelled from the pinned map."))],
            pin_id: PIN, run_id: RUN, process: PROCESS, field: FIELD = "workflow_view",
            basename: BASENAME = "workflow") -> dict:
        """Step 10's view: the workflow as BPMN swimlanes whose tasks are L3 capabilities. Unknown
        lanes or node ids are refused by name. Returns `{html_ref, summary, rules_source}`."""
        def draw(d: dict) -> dict:
            l3 = {r["id"]: r for r in d["tech"]["tables"]["technology-capability-l3"]}
            return bpmn.render(spec, l3=l3)
        out, prov = _draw(server, "bpmn", pin_id=pin_id, run_id=run_id, process=process,
                          field=field, draw=draw)
        return _answer({"html_ref": _store(server, f"{basename}.html", out["html"])}, out, prov)

    @server.tool()
    def semantic_view_architecture(
            components: Annotated[list[str], Field(description=(
                "The SELECTED components: catalogue ids (cmp-…) or codes (GW-02). Logical "
                "building blocks are derived from them."))],
            pin_id: PIN, run_id: RUN, process: PROCESS,
            field: FIELD = "architecture_view", title: TITLE = "", use_case: USE_CASE = "",
            pattern: Annotated[str, Field(description="P1–P5, when the solution follows one.")] = "",
            basename: BASENAME = "architecture") -> dict:
        """Step 22's views: the logical reference architecture and the physical reference
        implementation, each showing ONLY the solution's scope (layers with nothing in scope
        collapse to a strip). Returns `{logical_ref, physical_ref, summary, rules_source}`."""
        inp: dict[str, Any] = {"title": title, "use_case": use_case, "components": list(components),
                               **({"pattern": pattern} if pattern else {})}
        out, prov = _draw(server, "scoped_architecture", pin_id=pin_id, run_id=run_id,
                          process=process, field=field,
                          draw=lambda d: scoped_architecture.render(d, inp))
        refs = {f"{view}_ref": _store(server, f"{basename}.{view}.html", page)
                for view, page in out["pages"].items()}
        return _answer(refs, out, prov)

