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
  "views":     [{"id","title","elements":[...]}],   # scoped views; auto_edges applied
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
from shared import approvals  # noqa: E402  (Redis Streams approval gate)

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


def _build(spec):
    m = Model(spec["name"], spec.get("id", "model"))
    for e in spec.get("elements", []):
        m.el(e["id"], e["type"], e["name"], e.get("doc"))
    for r in spec.get("relations", []):
        m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
    for v in spec.get("views", []):
        vw = m.view(v["id"], v["title"])
        vw.place(*v["elements"])
        vw.auto_edges()
    if spec.get("standard_views"):
        m.standard_views()
    return m


@mcp.tool()
def archimate_validate(spec: dict) -> dict:
    """Check a model spec against ArchiMate legality rules (no rendering).
    Returns warnings (semantic) — an empty list means the model is clean."""
    with tracer.start_as_current_span("archimate_validate") as span:
        m = _build(spec)
        warnings = m.validate_relations()
        span.set_attributes({"archimate.elements": len(m.elements),
                             "archimate.relations": len(m.relations),
                             "archimate.warnings": len(warnings)})
        return {"elements": len(m.elements), "relations": len(m.relations), "warnings": warnings}


@mcp.tool()
def archimate_render(spec: dict, outdir: str, basename: str) -> dict:
    """Validate, lay out and render a model spec to ADOIT-importable Model Exchange XML
    plus one SVG preview per view. Fails on layout-invariant violations; returns the
    written file paths, per-view canvas sizes and any ArchiMate legality warnings."""
    with tracer.start_as_current_span("archimate_render") as span:
        m = _build(spec)
        report = m.render(outdir, basename, strict=True)
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
def adoit_request_import(xml_path: str, model_name: str, summary: dict,
                         requester: str = "ea-modeling-agent") -> dict:
    """WRITE PATH, step 1. Stage a rendered model for import into the EA repository by
    publishing an approval request (Redis Streams). Nothing is written to ADOIT here — a
    human must approve via the review app or Telegram. Returns the request id to poll with
    adoit_import_status. summary = the render report counts (elements, relations, views,
    violations, warnings)."""
    import glob
    from opentelemetry import trace
    with tracer.start_as_current_span("adoit_request_import") as span:
        if not os.path.exists(xml_path):
            raise FileNotFoundError(xml_path)
        base = xml_path[:-len(".archimate.xml")] if xml_path.endswith(".archimate.xml") else xml_path
        svgs = sorted(glob.glob(base + "-*.svg"))
        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        rid = approvals.request(kind="adoit-import", subject=model_name,
                                payload={"xml_path": xml_path, "svgs": svgs, "summary": summary},
                                requester=requester, trace_id=trace_id)
        span.set_attributes({"approval.request_id": rid, "approval.kind": "adoit-import"})
        return {"request_id": rid, "status": "pending", "channels": list(approvals.CHANNELS),
                "review_app": "http://127.0.0.1:8501"}


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
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="info")
