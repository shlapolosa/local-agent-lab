"""adoit-mcp — MCP facade over the ArchiMate engine + the ADOIT repository (hosted CE).

Runs as streamable HTTP so it can register with the LiteLLM MCP gateway (the lab's
governance plane): agents connect to ONE gateway endpoint; this server holds the ADOIT
credentials (injected from the environment, never given to agents) and imports the same
engine library the archimate-adoit skill uses — one implementation, two access paths.

Observability (the LabServer kit, src/lab/substrate/mcpserver.py): OTel spans (service.name=adoit-mcp)
— one per inbound MCP request via ASGI middleware (joins the caller's trace through the traceparent
header) plus one per tool, to which the tools add domain attributes (elements, relations,
violations); urllib calls to ADOIT are auto-instrumented. Exported over OTLP/HTTP when
OTEL_EXPORTER_OTLP_ENDPOINT is set; silent otherwise.

Tools (every spec argument is spec | spec_ref (art://…) | spec_path (local dev) — src/lab/substrate/specref.py):
  archimate_validate(spec…)                         -> ArchiMate legality warnings for a model spec
  archimate_render(basename, spec…, strict)         -> xml_ref + svg_refs (artifact store) + layout report;
                                                       strict=False returns layout violations instead of failing
  adoit_excel_render(basename, spec…)               -> xlsx_ref: the ADOIT Excel OBJECT import (create + update by name)
  adoit_repos()                                     -> repositories visible to the lab's ADOIT account (read)
  adoit_search(name_like, class_name, scope, limit) -> EXISTING objects/models in the repository (read)
  adoit_object(object_id)                           -> one existing object: attributes + relations (read)
  adoit_request_import(xml_ref, model_name, summary, svg_refs, xlsx_ref)
                                                    -> WRITE PATH step 1: publish an approval event, get id
  adoit_import_status(request_id)                   -> WRITE PATH step 2: decision + what happens next
  adoit_import_instructions()                       -> the human file-import procedure (Excel objects + XML views)

Write path: human-gated TWO-FILE import — the Excel object file creates/updates objects matched
by name, the ArchiMate XML imports the views. The REST write facade (adoit_rest.create/patch/
delete/relation) stays dormant behind ADOIT_REST_WRITE (see src/lab/platform/config.py: the hosted CE edge
blocks REST write verbs; reads — search/object/repos — work).

Model spec (JSON): {
  "name": str, "id": str?,
  "elements":  [{"id","type","name","doc"?}],
  "relations": [{"type","src","tgt","id"?,"accessType"?}],
  "views":     [{"id","title","elements":[...]} | {"id","title","rows":[[...],...],"containers":[...]}],
  "standard_views": bool                            # add the mapping-view catalogue
}

Run:  python -m lab.substrate.mcp.adoit.server     (port 9100, path /mcp)
"""
import json
import os
import sys
import urllib.request

from lab.core.archimate.engine import Model
from lab.platform import config
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


@server.tool()
def archimate_render(basename: str, spec: dict | None = None, spec_path: str | None = None,
                     spec_ref: str | None = None, outdir: str | None = None, strict: bool = True) -> dict:
    """Validate, lay out and render a model spec to ADOIT-importable Model Exchange XML plus
    one SVG preview per view. Pass spec by value, spec_ref (art://…) or, locally, spec_path.
    Outputs go to the artifact store: returns xml_ref + svg_refs (usable from any host),
    per-view canvas sizes, legality warnings. outdir additionally keeps local copies (dev).
    strict (default true) fails the call on a layout-invariant or XSD violation; strict=false
    still renders and returns them in `violations` so a reviewer can judge them — use it when a
    failed render at the last step would waste a whole run."""
    import tempfile
    m = _build(server.spec(spec, spec_path, spec_ref))
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


@server.tool()
def adoit_excel_render(basename: str, spec: dict | None = None, spec_path: str | None = None,
                       spec_ref: str | None = None) -> dict:
    """Render a model spec to an ADOIT **Excel object-import** file and store it as an artifact.
    This is the CE-safe write path for OBJECTS: ADOIT's 'Import objects from Excel' both CREATES and
    UPDATES repository objects (and their relationships), matching each row on its NAME — unlike the
    ArchiMate XML import, which always duplicates. Objects carry Name + Description; relationships are
    written on the source object's row (Composition/Serving/Realization/…). Returns xlsx_ref plus the
    object/relation/skip summary. The ArchiMate XML (archimate_render) remains the path for
    views/diagrams; a run stages both by ref."""
    import tempfile
    data = server.spec(spec, spec_path, spec_ref)
    out = os.path.join(tempfile.mkdtemp(prefix="adoit-xlsx-"), f"{basename}.objects.xlsx")
    res = adoit_excel.generate(data, out)
    res["xlsx_ref"] = _put_file(out)
    res.pop("path", None)
    span().set_attributes({"adoit.excel.objects": res["objects"],
                           "adoit.excel.relations": res.get("relations", 0),
                           "adoit.excel.sheets": len(res["sheets"]),
                           "adoit.excel.skipped": len(res["skipped"])})
    return res


@server.tool()
def adoit_repos() -> dict:
    """List ADOIT repositories visible to the lab's service account (read-only REST call;
    credentials are injected by this server — agents never see them)."""
    # /repos sits ABOVE the repo-scoped paths adoit_rest._get() serves, so only the credential
    # shape (_cfg) is shared here — one place knows how ADOIT Basic auth is built.
    base, _repo, auth = adoit_rest._cfg()
    req = urllib.request.Request(f"{base}{adoit_rest.REST}/repos",
                                 headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@server.tool()
def adoit_search(name_like: str = "", class_name: str = "", scope: str = "objects", limit: int = 50) -> list:
    """Search the EXISTING architecture in the ADOIT repository (read-only) — the way to check
    whether something is already modelled before designing. Give a `name_like` (substring, e.g.
    'portal') and/or a `class_name` (an ArchiMate type like 'ApplicationComponent', or a raw ADOIT
    class 'C_APPLICATION_COMPONENT'); at least one is required. `scope`: 'objects' (repository
    objects, default), 'models' (diagrams/views), or 'all'. Returns
    [{id, name, class, artefactType, groupId, modelName}] — use the `id` with adoit_object, and reuse
    it as an element id when regenerating so the object is updated in place instead of duplicated."""
    res = adoit_rest.search(name_like, class_name, scope, limit)
    span().set_attributes({"adoit.name_like": name_like, "adoit.class": class_name,
                           "adoit.scope": scope, "adoit.hits": len(res)})
    return res


@server.tool()
def adoit_object(object_id: str) -> dict:
    """Full detail of one existing ADOIT object (read-only): its class, group, key attributes and
    its relations ({type, target_id, target_name}). Use the `id` from adoit_search. Read this before
    deciding an input is an UPDATE, to see what the existing element already connects to."""
    span().set_attribute("adoit.object_id", object_id)
    obj = adoit_rest.get_object(object_id)
    span().set_attributes({"adoit.class": obj.get("class") or "", "adoit.relations": len(obj.get("relations", []))})
    return obj


@server.tool()
def adoit_request_import(xml_ref: str, model_name: str, summary: dict, svg_refs: dict | None = None,
                         xlsx_ref: str | None = None, requester: str = "ea-modeling-agent") -> dict:
    """WRITE PATH, step 1. Stage a rendered model for import into the EA repository by
    publishing an approval request (Redis Streams). Nothing is written to ADOIT here — a
    human must approve via the review app or Telegram. xml_ref / svg_refs are the artifact
    references returned by archimate_render (the views/diagram path); xlsx_ref is the Excel
    object-import file from adoit_excel_render (the object create+update path). Returns the
    request id to poll with adoit_import_status."""
    server.artifacts().info(xml_ref)         # fail fast if the reference is unknown
    ctx = span().get_span_context()
    trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
    rid = approvals.request(kind="adoit-import", subject=model_name,
                            payload={"xml_ref": xml_ref, "svg_refs": svg_refs or {},
                                     "xlsx_ref": xlsx_ref, "summary": summary},
                            requester=requester, trace_id=trace_id)
    span().set_attributes({"approval.request_id": rid, "approval.kind": "adoit-import"})
    return {"request_id": rid, "status": "pending", "channels": list(approvals.CHANNELS),
            "review_app": config.REVIEW_APP_URL}


@server.tool()
def adoit_import_status(request_id: str) -> dict:
    """WRITE PATH, step 2. Current decision on an import request and what happens next.
    approve -> the model is released for the two-file import (Excel objects + ArchiMate XML
    views, adoit_import_instructions). ADOIT_REST_WRITE=true only reports that the REST write
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
        "Excel object file, via the ADOIT UI (adoit_import_instructions). "
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


@server.tool()
def adoit_import_instructions() -> str:
    """The governed human file-import write path into ADOIT. TWO files, TWO purposes (the hosted CE
    blocks REST writes at the edge; the granular REST facade is gated behind ADOIT_REST_WRITE for a
    full tenant): the Excel object file CREATES + UPDATES objects (matched by name), the ArchiMate XML
    imports the views/diagrams."""
    base = os.environ.get("ADOIT_BASE_URL", "")
    return (
        "ADOIT write path (human-gated). Log in at " + base + ", then import BOTH artifacts:\n"
        "A) OBJECTS — the Excel file (adoit_excel_render): Object Catalogue -> right-click the target "
        "group -> Import/Export -> Import objects from Excel -> upload the .xlsx. ADOIT matches each "
        "row on its NAME: a name found once is UPDATED in place, a new name is CREATED. Review the "
        "import PREVIEW (it says create vs update per object) before confirming. Keep object names "
        "UNIQUE — a duplicate name makes the import ambiguous and it refuses that object.\n"
        "B) VIEWS — the ArchiMate XML (archimate_render): Import/Export -> ArchiMate Model Exchange "
        "File -> upload the .archimate.xml. Decline any auto-layout offer so the generated geometry "
        "survives; confirm interfaces render as icons. Note the ArchiMate import always CREATES objects "
        "in a new group (it does not match on identifier), so use it for the diagram; the Excel file is "
        "what keeps objects de-duplicated and updatable.\n"
        "Human approval is required before every import (lab approval-gate policy)."
    )


if __name__ == "__main__":
    for k in ("ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID"):
        if k not in os.environ:
            sys.exit(f"missing env var {k} — source .env before starting")
    server.serve()
