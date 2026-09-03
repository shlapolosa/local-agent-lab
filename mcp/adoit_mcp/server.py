"""adoit-mcp — MCP facade over the ArchiMate engine + the ADOIT:CE repository.

Runs as streamable HTTP so it can register with the LiteLLM MCP gateway (the lab's
governance plane): agents connect to ONE gateway endpoint; this server holds the ADOIT
credentials (injected from the environment, never given to agents) and imports the same
engine library the archimate-adoit skill uses — one implementation, two access paths.

Observability: OTel spans (service.name=adoit-mcp) — one per inbound MCP request via ASGI
middleware (joins the caller's trace through the traceparent header) plus one per tool with
domain attributes (elements, relations, violations) and auto-instrumented urllib calls to
ADOIT. Exported over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set; silent otherwise.

Tools:
  archimate_validate(spec)                  -> ArchiMate legality warnings for a model spec
  archimate_render(spec, outdir, basename)  -> .archimate.xml + per-view SVGs + layout report
  adoit_repos()                             -> repositories visible to the lab's ADOIT account
  adoit_request_import(xml_path, ...)       -> WRITE PATH step 1: publish an approval event, get id
  adoit_import_status(request_id)           -> WRITE PATH step 2: decision + what happens next
  adoit_import_instructions()               -> the ADOIT:CE UI import procedure (no REST writes)

Model spec (JSON): {
  "name": str, "id": str?,
  "elements":  [{"id","type","name","doc"?}],
  "relations": [{"type","src","tgt","id"?,"accessType"?}],
  "views":     [{"id","title","elements":[...]} | {"id","title","rows":[[...],...],"containers":[...]}],
  "standard_views": bool                            # add the mapping-view catalogue
}

Run:  python3 server.py            (port 9100, path /mcp)
"""
import base64
import json
import os
import sys
import urllib.request

from fastmcp import FastMCP

SKILL_SCRIPTS = os.path.join(
    os.path.dirname(__file__), "..", "..", ".claude", "skills", "archimate-adoit", "scripts")
sys.path.insert(0, os.path.abspath(SKILL_SCRIPTS))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from archimate_engine import Model  # noqa: E402
import adoit_rest  # noqa: E402  (ADOIT 18 REST read facade — search / object detail)
from shared import approvals, artifacts, config  # noqa: E402  (approval gate, artifact store, addresses)
from shared.mcpauth import BearerAuthMiddleware  # noqa: E402

SERVICE = "adoit-mcp"


def _setup_otel():
    """Tracer provider + OTLP exporter; returns a tracer (no-op tracer if OTel is unset)."""
    from opentelemetry import trace
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return trace.get_tracer(SERVICE)
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.urllib import URLLibInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    URLLibInstrumentor().instrument()          # ADOIT REST calls become child spans
    return trace.get_tracer(SERVICE)


tracer = _setup_otel()
mcp = FastMCP(SERVICE)


def _load_spec(spec, spec_path=None, spec_ref=None):
    """Specs arrive by value (small), by artifact reference art://… (any host), or — local
    dev only — by file path."""
    if spec_ref:
        return json.loads(artifacts.store().get(spec_ref))
    if spec_path:
        return json.load(open(spec_path))
    if not spec:
        raise ValueError("give spec (by value) or spec_path (by reference)")
    if isinstance(spec, str):
        return json.loads(spec)   # agents often serialize the nested object as a JSON string
    return spec


def _build(spec):
    m = Model(spec["name"], spec.get("id", "model"))
    for e in spec.get("elements", []):
        m.el(e["id"], e["type"], e["name"], e.get("doc"))
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


@mcp.tool()
def archimate_validate(spec: dict | None = None, spec_path: str | None = None,
                       spec_ref: str | None = None) -> dict:
    """Check a model spec against ArchiMate legality rules (no rendering). Pass spec by
    value, spec_ref (art://… from semantic_export_archimate) or, locally, spec_path.
    Returns warnings (semantic) — an empty list means the model is clean."""
    with tracer.start_as_current_span("archimate_validate") as span:
        m = _build(_load_spec(spec, spec_path, spec_ref))
        warnings = m.validate_relations()
        span.set_attributes({"archimate.elements": len(m.elements),
                             "archimate.relations": len(m.relations),
                             "archimate.warnings": len(warnings)})
        return {"elements": len(m.elements), "relations": len(m.relations), "warnings": warnings}


@mcp.tool()
def archimate_render(basename: str, spec: dict | None = None, spec_path: str | None = None,
                     spec_ref: str | None = None, outdir: str | None = None) -> dict:
    """Validate, lay out and render a model spec to ADOIT-importable Model Exchange XML plus
    one SVG preview per view. Pass spec by value, spec_ref (art://…) or, locally, spec_path.
    Outputs go to the artifact store: returns xml_ref + svg_refs (usable from any host),
    per-view canvas sizes, legality warnings. outdir additionally keeps local copies (dev)."""
    import tempfile
    with tracer.start_as_current_span("archimate_render") as span:
        m = _build(_load_spec(spec, spec_path, spec_ref))
        work = outdir or tempfile.mkdtemp(prefix="archimate-")
        report = m.render(work, basename, strict=True)
        xml = next(f for f in report["files"] if f.endswith(".archimate.xml"))
        report["xml_ref"] = artifacts.put_file(xml)
        report["svg_refs"] = {os.path.basename(f)[len(basename) + 1:-4]: artifacts.put_file(f)
                              for f in report["files"] if f.endswith(".svg")}
        if not outdir:
            report["files"] = []          # nothing durable on this host; use the refs
        span.set_attributes({"archimate.elements": len(m.elements),
                             "archimate.relations": len(m.relations),
                             "archimate.views": len(report["views"]),
                             "archimate.violations": len(report["violations"]),
                             "archimate.warnings": len(report["warnings"])})
        return report


@mcp.tool()
def adoit_repos() -> dict:
    """List ADOIT repositories visible to the lab's service account (read-only REST call;
    credentials are injected by this server — agents never see them)."""
    with tracer.start_as_current_span("adoit_repos"):
        base = os.environ["ADOIT_BASE_URL"]
        cred = base64.b64encode(
            f'{os.environ["ADOIT_USERNAME"]}:{os.environ["ADOIT_PASSWORD"]}'.encode()).decode()
        req = urllib.request.Request(f"{base}/rest/2.0/repos",
                                     headers={"Authorization": f"Basic {cred}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)


@mcp.tool()
def adoit_search(name_like: str = "", class_name: str = "", scope: str = "objects", limit: int = 50) -> list:
    """Search the EXISTING architecture in the ADOIT repository (read-only) — the way to check
    whether something is already modelled before designing. Give a `name_like` (substring, e.g.
    'portal') and/or a `class_name` (an ArchiMate type like 'ApplicationComponent', or a raw ADOIT
    class 'C_APPLICATION_COMPONENT'); at least one is required. `scope`: 'objects' (repository
    objects, default), 'models' (diagrams/views), or 'all'. Returns
    [{id, name, class, artefactType, groupId, modelName}] — use the `id` with adoit_object, and reuse
    it as an element id when regenerating so the object is updated in place instead of duplicated."""
    with tracer.start_as_current_span("adoit_search") as span:
        res = adoit_rest.search(name_like, class_name, scope, limit)
        span.set_attributes({"adoit.name_like": name_like, "adoit.class": class_name,
                             "adoit.scope": scope, "adoit.hits": len(res)})
        return res


@mcp.tool()
def adoit_object(object_id: str) -> dict:
    """Full detail of one existing ADOIT object (read-only): its class, group, key attributes and
    its relations ({type, target_id, target_name}). Use the `id` from adoit_search. Read this before
    deciding an input is an UPDATE, to see what the existing element already connects to."""
    with tracer.start_as_current_span("adoit_object") as span:
        span.set_attribute("adoit.object_id", object_id)
        obj = adoit_rest.get_object(object_id)
        span.set_attributes({"adoit.class": obj.get("class") or "", "adoit.relations": len(obj.get("relations", []))})
        return obj


@mcp.tool()
def adoit_request_import(xml_ref: str, model_name: str, summary: dict, svg_refs: dict | None = None,
                         requester: str = "ea-modeling-agent") -> dict:
    """WRITE PATH, step 1. Stage a rendered model for import into the EA repository by
    publishing an approval request (Redis Streams). Nothing is written to ADOIT here — a
    human must approve via the review app or Telegram. xml_ref / svg_refs are the artifact
    references returned by archimate_render (reachable from any host). Returns the request id
    to poll with adoit_import_status."""
    from opentelemetry import trace
    with tracer.start_as_current_span("adoit_request_import") as span:
        artifacts.store().info(xml_ref)          # fail fast if the reference is unknown
        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        rid = approvals.request(kind="adoit-import", subject=model_name,
                                payload={"xml_ref": xml_ref, "svg_refs": svg_refs or {}, "summary": summary},
                                requester=requester, trace_id=trace_id)
        span.set_attributes({"approval.request_id": rid, "approval.kind": "adoit-import"})
        return {"request_id": rid, "status": "pending", "channels": list(approvals.CHANNELS),
                "review_app": config.REVIEW_APP_URL}


@mcp.tool()
def adoit_import_status(request_id: str) -> dict:
    """WRITE PATH, step 2. Current decision on an import request and what happens next.
    approve -> the model is released for import (on ADOIT:CE the import itself is the UI
    procedure from adoit_import_instructions; on a full tenant this is where the REST write
    will run). decline -> stop. update -> changes requested, see comment; re-render and
    re-request."""
    st = approvals.status(request_id)
    if not st:
        raise KeyError(f"unknown request {request_id}")
    nxt = {"pending": "awaiting a human decision (review app / Telegram / CLI)",
           "approve": "released for import — run the ADOIT:CE UI import (adoit_import_instructions); "
                      "REST write will execute here once a full ADOIT tenant is available",
           "decline": "declined — do not import",
           "update": "changes requested — address the comment, re-render, re-request"}
    st["next"] = nxt.get(st.get("status"), "")
    return st


@mcp.tool()
def adoit_import_instructions() -> str:
    """The governed write path into ADOIT:CE (its REST write endpoints are disabled)."""
    return (
        "ADOIT:CE write path (verified Aug 2026): REST 2.0 write endpoints return 403, so "
        "imports go through the UI. 1) Log in at " + os.environ.get("ADOIT_BASE_URL", "") +
        " 2) Menu -> Import/Export -> ArchiMate Model Exchange File -> upload the "
        ".archimate.xml. 3) Decline any auto-layout offer so the generated geometry "
        "survives. 4) Confirm interfaces render as icons (toggle representation to symbol "
        "if not). Re-imports never overwrite: ADOIT places same-named models/objects in new "
        "groups — delete stale import groups after regeneration. Human approval required "
        "before every import (lab approval-gate policy)."
    )


if __name__ == "__main__":
    for k in ("ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD"):
        if k not in os.environ:
            sys.exit(f"missing env var {k} — source .env before starting")
    import uvicorn
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    app = mcp.http_app(path="/mcp")
    app.add_middleware(OpenTelemetryMiddleware)   # inbound request spans + traceparent extraction
    app.add_middleware(BearerAuthMiddleware)      # gateway must present MCP_SHARED_SECRET (if set)
    uvicorn.run(app, host=config.BIND_HOST, port=config.ADOIT_MCP_PORT, log_level="info")
