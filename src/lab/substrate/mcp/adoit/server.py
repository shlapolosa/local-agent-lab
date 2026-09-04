"""adoit-mcp — the ADOIT ADAPTER behind the lab's vendor-neutral EA-repository PORT.

The PORT is the tool contract (`lab.platform.contracts.EATools`, gateway alias `ea_mcp`):
`ea_search` / `ea_object` / `ea_repositories` read the existing architecture, `ea_stage_import`
stages a model for a human-approved write, `ea_import_status` / `ea_import_instructions` follow it.
No tool names ADOIT and none leaks an ADOIT limitation — swapping ADOIT for another EA tool is a
different server registering these SAME names under the SAME gateway alias, with no workload change.
This SERVICE is where the vendor lives: the ADOIT credentials, REST facade, and the fact that hosted
CE blocks REST writes so a human must import an Excel object file (a PRIVATE detail of this adapter,
produced inside `ea_stage_import` — the caller is told only what artifacts came out).

Runs as streamable HTTP so it can register with the LiteLLM MCP gateway (the lab's
governance plane): agents connect to ONE gateway endpoint; this server holds the ADOIT
credentials (injected from the environment, never given to agents) and imports the same
engine library the archimate-adoit skill uses — one implementation, two access paths.

Observability (the LabServer kit, src/lab/substrate/mcpserver.py): OTel spans (service.name=adoit-mcp)
— one per inbound MCP request via ASGI middleware (joins the caller's trace through the traceparent
header) plus one per tool, to which the tools add domain attributes (elements, relations,
violations); urllib calls to ADOIT are auto-instrumented. Exported over OTLP/HTTP when
OTEL_EXPORTER_OTLP_ENDPOINT is set; silent otherwise.

Tools (every spec argument is spec | spec_ref (art://…) | spec_path (local dev) — src/lab/substrate/specref.py).
DOMAIN (engine) services — here only because the engine is, they belong with the modelling side if it splits:
  archimate_validate(spec…)                         -> ArchiMate legality warnings for a model spec
  archimate_render(basename, spec…, strict)         -> xml_ref + svg_refs (artifact store) + layout report;
                                                       strict=False returns layout violations instead of failing
EA-REPOSITORY PORT (vendor-neutral names; this server is the ADOIT adapter):
  ea_repositories()                                 -> repositories visible to the lab's account (read)
  ea_search(name_like, class_name, scope, limit)    -> EXISTING objects/models in the repository (read)
  ea_object(object_id)                              -> one existing object: attributes + relations (read)
  ea_stage_import(spec_ref, model_name, summary, xml_ref, svg_refs)
                                                    -> WRITE PATH step 1: produce this repository's import
                                                       artifacts + publish an approval event, get id
  ea_import_status(request_id)                      -> WRITE PATH step 2: decision + what happens next
  ea_import_instructions()                          -> the human import procedure for this repository

Write path on THIS adapter: human-gated TWO-FILE import — an Excel object file creates/updates objects
matched by name, the ArchiMate XML imports the views. Both are produced INSIDE ea_stage_import (private
`_object_import_file` / `_render_model`), because "a spreadsheet a human imports" is an ADOIT:CE
limitation, not something the port may oblige a caller to know. The REST write facade
(adoit_rest.create/patch/delete/relation) stays dormant behind ADOIT_REST_WRITE (see
src/lab/platform/config.py: the hosted CE edge blocks REST write verbs; reads work). A write-capable
tenant's adapter would write over REST after the approval and return NO import artifacts.

Model spec (JSON): {
  "name": str, "id": str?,
  "elements":  [{"id","type","name","doc"?}],
  "relations": [{"type","src","tgt","id"?,"accessType"?}],
  "views":     [{"id","title","elements":[...]} | {"id","title","rows":[[...],...],"containers":[...]}],
  "standard_views": bool                            # add the mapping-view catalogue
}

Run:  python -m lab.substrate.mcp.adoit.server     (port 9100, path /mcp, gateway alias ea_mcp)
"""
import json
import os
import re
import sys
import urllib.request

from lab.core.archimate.engine import Model
from lab.platform import config
from lab.platform.contracts import ApprovalKind
from lab.substrate import approvals  # (approval gate)
from lab.substrate.artifacts import put_file
from lab.substrate.mcp.adoit import adoit_excel  # (ADOIT Excel object-import generator — CE-safe object create/update)
from lab.substrate.mcp.adoit import adoit_rest  # (ADOIT 18 REST read facade — search / object detail)
from lab.substrate.mcpserver import LabServer, span

SERVICE = "adoit-mcp"

server = LabServer(SERVICE, config.ADOIT_MCP_PORT, instrument_urllib=True)   # ADOIT REST calls become child spans


def _put_file(path) -> str:
    return put_file(path, target=server.artifacts())


def _build(spec):
    m = Model(spec["name"], spec.get("id", "model"))
    for e in spec.get("elements", []):
        m.el(e["id"], e["type"], e["name"], e.get("doc"), folder=e.get("folder"))
    for r in spec.get("relations", []):
        m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
    for v in spec.get("views", []):
        vw = m.view(v["id"], v["title"])
        if v.get("rows"):                       # explicit rows (e.g. capability-map overview grids)
            for i, row in enumerate(v["rows"]):
                vw.place(*row, rank=i)
        else:
            vw.place(*v["elements"])
        for c in v.get("containers", []):       # nesting where the notation calls for it (capability maps)
            vw.container(c["id"], children=c["children"])
        vw.auto_edges()
    if spec.get("standard_views"):
        m.standard_views()
    return m


@server.tool()
def archimate_validate(spec: dict | None = None, spec_path: str | None = None,
                       spec_ref: str | None = None) -> dict:
    """Check a model spec against ArchiMate legality rules (no rendering). Pass spec by
    value, spec_ref (art://… from semantic_export_archimate) or, locally, spec_path.
    Returns warnings (semantic) — an empty list means the model is clean."""
    m = _build(server.spec(spec, spec_path, spec_ref))
    warnings = m.validate_relations()
    span().set_attributes({"archimate.elements": len(m.elements),
                           "archimate.relations": len(m.relations),
                           "archimate.warnings": len(warnings)})
    return {"elements": len(m.elements), "relations": len(m.relations), "warnings": warnings}


def _render_model(spec: dict, basename: str, outdir: str | None = None, strict: bool = True) -> dict:
    """Lay out and render a built model to Model Exchange XML + one SVG per view, stored as artifacts.
    ONE implementation, two callers: the `archimate_render` tool and `ea_stage_import` (which renders
    the views itself when the caller has not already)."""
    import tempfile
    m = _build(spec)
    work = outdir or tempfile.mkdtemp(prefix="archimate-")
    report = m.render(work, basename, strict=strict)
    xml = next(f for f in report["files"] if f.endswith(".archimate.xml"))
    report["xml_ref"] = _put_file(xml)
    report["svg_refs"] = {os.path.basename(f)[len(basename) + 1:-4]: _put_file(f)
                          for f in report["files"] if f.endswith(".svg")}
    if not outdir:
        report["files"] = []          # nothing durable on this host; use the refs
    span().set_attributes({"archimate.elements": len(m.elements),
                           "archimate.relations": len(m.relations),
                           "archimate.views": len(report["views"]),
                           "archimate.violations": len(report["violations"]),
                           "archimate.warnings": len(report["warnings"]),
                           "archimate.strict": strict})
    return report


def _object_import_file(spec: dict, basename: str) -> dict:
    """PRIVATE to this adapter: the ADOIT Excel OBJECT-import file (xlsx_ref + counts). It exists only
    because hosted ADOIT:CE blocks REST writes, so objects are created/updated by a human importing a
    spreadsheet that matches each row on its NAME. That is an ADOIT limitation, so it is NOT a tool of
    the EA port — `ea_stage_import` produces it and reports it as one of the artifacts it produced."""
    import tempfile
    out = os.path.join(tempfile.mkdtemp(prefix="adoit-xlsx-"), f"{basename}.objects.xlsx")
    res = adoit_excel.generate(spec, out)
    res["xlsx_ref"] = _put_file(out)
    res.pop("path", None)
    span().set_attributes({"adoit.excel.objects": res["objects"],
                           "adoit.excel.relations": res.get("relations", 0),
                           "adoit.excel.sheets": len(res["sheets"]),
                           "adoit.excel.skipped": len(res["skipped"])})
    return res


def _slug(name: str) -> str:
    """A safe artifact basename from a model name ('Claims Portal' -> 'claims-portal')."""
    return re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower() or "model"


# archimate_validate / archimate_render are DOMAIN (engine) services, not EA-repository operations:
# they live on this server only because the engine does, and would move with the modelling side if
# the two ever split — which is why they keep their names while the repository tools are `ea_*`.
@server.tool()
def archimate_render(basename: str, spec: dict | None = None, spec_path: str | None = None,
                     spec_ref: str | None = None, outdir: str | None = None, strict: bool = True) -> dict:
    """Validate, lay out and render a model spec to importable ArchiMate Model Exchange XML plus
    one SVG preview per view. Pass spec by value, spec_ref (art://…) or, locally, spec_path.
    Outputs go to the artifact store: returns xml_ref + svg_refs (usable from any host),
    per-view canvas sizes, legality warnings. outdir additionally keeps local copies (dev).
    strict (default true) fails the call on a layout-invariant or XSD violation; strict=false
    still renders and returns them in `violations` so a reviewer can judge them — use it when a
    failed render at the last step would waste a whole run."""
    return _render_model(server.spec(spec, spec_path, spec_ref), basename, outdir, strict)


@server.tool()
def ea_repositories() -> dict:
    """List the EA repositories visible to the lab's service account (read-only; the repository
    credentials are injected by this server — agents never see them)."""
    # /repos sits ABOVE the repo-scoped paths adoit_rest._get() serves, so only the credential
    # shape (_cfg) is shared here — one place knows how ADOIT Basic auth is built.
    base, _repo, auth = adoit_rest._cfg()
    req = urllib.request.Request(f"{base}{adoit_rest.REST}/repos",
                                 headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@server.tool()
def ea_search(name_like: str = "", class_name: str = "", scope: str = "objects", limit: int = 50) -> list:
    """Search the EXISTING architecture in the EA repository (read-only) — the way to check
    whether something is already modelled before designing. Give a `name_like` (substring, e.g.
    'portal') and/or a `class_name` (an ArchiMate type like 'ApplicationComponent', or the
    repository's own class name such as 'C_APPLICATION_COMPONENT'); at least one is required.
    `scope`: 'objects' (repository objects, default), 'models' (diagrams/views), or 'all'. Returns
    [{id, name, class, artefactType, groupId, modelName}] — use the `id` with ea_object, and reuse
    it as an element id when regenerating so the object is updated in place instead of duplicated."""
    res = adoit_rest.search(name_like, class_name, scope, limit)
    span().set_attributes({"adoit.name_like": name_like, "adoit.class": class_name,
                           "adoit.scope": scope, "adoit.hits": len(res)})
    return res


@server.tool()
def ea_object(object_id: str) -> dict:
    """Full detail of one existing repository object (read-only): its class, group, key attributes and
    its relations ({type, target_id, target_name}). Use the `id` from ea_search. Read this before
    deciding an input is an UPDATE, to see what the existing element already connects to."""
    span().set_attribute("adoit.object_id", object_id)
    obj = adoit_rest.get_object(object_id)
    span().set_attributes({"adoit.class": obj.get("class") or "", "adoit.relations": len(obj.get("relations", []))})
    return obj


@server.tool()
def ea_stage_import(spec_ref: str, model_name: str, summary: dict, xml_ref: str | None = None,
                    svg_refs: dict | None = None, requester: str = "ea-modeling-agent") -> dict:
    """WRITE PATH, step 1. Stage a model for a human-approved write into the EA repository: produce
    whatever THIS repository needs in order to take the model, and publish an approval request (Redis
    Streams). NOTHING is written here — a human decides via the review app or Telegram, then
    ea_import_status says what happens next.
    `spec_ref` is the model BY REFERENCE (art://…, e.g. from semantic_store_spec). `xml_ref`/`svg_refs`
    are OPTIONAL ArchiMate view artifacts you already rendered (archimate_render) that this repository
    may reuse instead of rendering them again; omit them and it renders what it needs itself.
    Returns the `request_id` to poll with ea_import_status, `artifacts` — whatever this repository
    produced for the import, by reference — and the human `instructions` for it. Do NOT assume any
    particular artifact: a repository that writes over its own API after the approval returns
    `artifacts: {}` (this ADOIT adapter returns the views XML, its SVG previews and an Excel object
    file, because hosted ADOIT:CE requires a human to import them). An adapter MAY add facts of its own
    to the staged summary (this one adds the object count and, when it rendered the views itself, the
    lenient render's violation count) — a caller must never require them."""
    if svg_refs and not xml_ref:             # the pair is atomic: previews without their XML describe nothing
        raise ValueError("svg_refs given without xml_ref — pass both rendered artifacts or neither")
    spec = server.spec(spec_ref=spec_ref)
    basename = _slug(model_name)
    facts: dict = {}
    if xml_ref:
        server.artifacts().info(xml_ref)     # fail fast if the caller's reference is unknown
    else:                                    # strict=False: a failed render at the last step wastes a whole run
        rendered = _render_model(spec, basename, strict=False)
        xml_ref, svg_refs = rendered["xml_ref"], rendered["svg_refs"]
        # lenient render: the violations must NOT vanish — the human approving this import is the only
        # gate left, so what strict=True would have refused is reported to them.
        facts["render_violations"] = len(rendered["violations"])
    objects = _object_import_file(spec, basename)     # ADOIT:CE object create/update — this adapter's need
    facts["excel_objects"] = objects["objects"]
    artifacts = {"xml_ref": xml_ref, "svg_refs": svg_refs or {}, "xlsx_ref": objects["xlsx_ref"]}
    ctx = span().get_span_context()
    trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
    rid = approvals.request(kind=ApprovalKind.ADOIT_IMPORT.value, subject=model_name,
                            payload={**artifacts, "summary": {**summary, **facts}},
                            requester=requester, trace_id=trace_id)
    span().set_attributes({"approval.request_id": rid, "approval.kind": ApprovalKind.ADOIT_IMPORT.value,
                           **{f"adoit.{k}": v for k, v in facts.items()}})
    return {"request_id": rid, "status": "pending", "channels": list(approvals.CHANNELS),
            "review_app": config.REVIEW_APP_URL, "artifacts": artifacts,
            "instructions": _import_instructions()}


@server.tool()
def ea_import_status(request_id: str) -> dict:
    """WRITE PATH, step 2. Current decision on an import request and what happens next.
    approve -> the artifacts ea_stage_import produced are released for the human import
    (ea_import_instructions). ADOIT_REST_WRITE=true only reports that the REST write
    path is enabled (`rest_write_enabled`); the gated REST apply step is not implemented, so
    file-import stays the release path. decline -> stop. update -> changes requested, see
    comment; re-render and re-request."""
    st = approvals.status(request_id)
    if not st:
        raise KeyError(f"unknown request {request_id}")
    # The hosted CE blocks REST writes at the edge, so the release path is human file-import. The REST
    # write facade (adoit_rest.create/patch/delete/relation) has NO caller yet: with ADOIT_REST_WRITE=true
    # this tool says so instead of claiming a changeset ran (wiring the gated apply step is a separate,
    # human-gated change).
    approve_next = (
        "released for file-import — import the ArchiMate XML (views/creates) and, for object updates, the "
        "Excel object file, via the ADOIT UI (ea_import_instructions). "
        + ("REST write path is ENABLED (ADOIT_REST_WRITE=true) but the gated apply step is not implemented "
           "on this tenant/version — file-import remains the release path"
           if config.ADOIT_REST_WRITE else
           "REST write is off (ADOIT_REST_WRITE=false — hosted CE blocks it)")
    )
    nxt = {"pending": "awaiting a human decision (review app / Telegram / CLI)",
           "approve": approve_next,
           "decline": "declined — do not import",
           "update": "changes requested — address the comment, re-render, re-request"}
    st["next"] = nxt.get(st.get("status"), "")
    st["write_path"] = "file-import"
    st["rest_write_enabled"] = bool(config.ADOIT_REST_WRITE)
    return st


def _import_instructions() -> str:
    """This adapter's human import procedure — ONE text, two callers (the tool and ea_stage_import,
    which hands it back with the artifacts it produced)."""
    base = adoit_rest._cfg()[0]          # the ONE place that knows where this tenant lives
    return (
        "ADOIT write path (human-gated). Log in at " + base + ", then import BOTH artifacts:\n"
        "A) OBJECTS — the Excel object file (from ea_stage_import): Object Catalogue -> right-click the target "
        "group -> Import/Export -> Import objects from Excel -> upload the .xlsx. ADOIT matches each "
        "row on its NAME: a name found once is UPDATED in place, a new name is CREATED. Review the "
        "import PREVIEW (it says create vs update per object) before confirming. Keep object names "
        "UNIQUE — a duplicate name makes the import ambiguous and it refuses that object.\n"
        "B) VIEWS — the ArchiMate XML (from ea_stage_import): Import/Export -> ArchiMate Model Exchange "
        "File -> upload the .archimate.xml. Decline any auto-layout offer so the generated geometry "
        "survives; confirm interfaces render as icons. Note the ArchiMate import always CREATES objects "
        "in a new group (it does not match on identifier), so use it for the diagram; the Excel file is "
        "what keeps objects de-duplicated and updatable.\n"
        "Human approval is required before every import (lab approval-gate policy)."
    )


@server.tool()
def ea_import_instructions() -> str:
    """The governed human write path into this EA repository (ADOIT). TWO files, TWO purposes (the
    hosted CE blocks REST writes at the edge; the granular REST facade is gated behind
    ADOIT_REST_WRITE for a full tenant): the Excel object file CREATES + UPDATES objects (matched by
    name), the ArchiMate XML imports the views/diagrams. ea_stage_import returns this same text with
    the artifacts it produced."""
    return _import_instructions()


if __name__ == "__main__":
    for k in ("ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID"):
        if k not in os.environ:
            sys.exit(f"missing env var {k} — source .env before starting")
    server.serve()
