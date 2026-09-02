"""storage-mcp — READ-ONLY governed access to the upload store (port 9300, /mcp).

Why a server: a workload must never hold object-store credentials (invariant: agents never hold
tool credentials — the gateway injects them). Submitted inputs live in a bucket (Railway Bucket
now, Azure Blob later) or in the Postgres artifact store; the credentials live HERE, in the
substrate, and every read an agent or workload makes goes gateway -> this server, so it is
granted per team, allow-listed per tool, metered, PII-scanned and traced like any other call.
Nothing here writes: uploads are made by the review app (a trusted substrate component), and a
workload's own outputs go through semantic-mcp / adoit-mcp. Azure parity: Blob reached only
through a governed API, never a SAS handed to an agent.

Parsing and the image SIZING CONTRACT are shared code (shared/docparse.py): figures are
normalised server-side (decorations < 2 KB / < 64 px dropped, downscaled to max_edge, PNG unless
already PNG/JPEG) so every workload gets consistent, bounded images — the visio-reader skill
documents this contract.

Tools (all read-only, over art://<id>/<name> refs)
  storage_list(prefix, limit)               objects in the upload store
  storage_info(ref)                         name / content type / size / created_at
  storage_get(ref, max_edge)                an IMAGE object, normalised, as image content + a label
  storage_read_document(ref, max_chars)     .docx/.pdf/.md/.txt -> plain text
  storage_read_vsdx(ref)                    .vsdx -> {pages, shapes, connectors}
  storage_extract_figures(ref, max_images)  figures embedded in a .docx/.pdf -> images + labels
"""
import os
import sys

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from shared import artifacts, config, docparse  # noqa: E402
from shared.mcpauth import BearerAuthMiddleware  # noqa: E402

SERVICE = "storage-mcp"


def _setup_otel():
    from opentelemetry import trace
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return trace.get_tracer(SERVICE)
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(SERVICE)


tracer = _setup_otel()
mcp = FastMCP(SERVICE)


def _store():
    return artifacts.uploads()            # the UPLOAD store (bucket in the cloud, Postgres locally)


def _name(ref: str) -> str:
    return ref.rstrip("/").split("/")[-1]


def _image(data: bytes, mime: str) -> Image:
    return Image(data=data, format="jpeg" if mime == "image/jpeg" else "png")


@mcp.tool()
def storage_list(prefix: str = "", limit: int = 100) -> list:
    """Objects in the upload store (newest first): [{ref, name, content_type, size, created_at}].
    `prefix` filters by file name. Use the `ref` (art://…) with the other storage_* tools."""
    with tracer.start_as_current_span("storage_list") as span:
        items = _store().list(prefix, limit)
        span.set_attributes({"storage.count": len(items), "storage.prefix": prefix})
        return items


@mcp.tool()
def storage_info(ref: str) -> dict:
    """Metadata for one object: name, content_type, size, created_at, and its kind
    (vsdx | image | document) so a caller knows which read tool applies."""
    with tracer.start_as_current_span("storage_info") as span:
        span.set_attribute("storage.ref", ref)
        info = _store().info(ref)
        info["kind"] = docparse.kind(info["name"])
        return info


# NOTE: the two image tools deliberately have NO return annotation — fastmcp derives an
# outputSchema from one, and a schema makes clients demand structured output that image content
# blocks cannot carry ("outputSchema defined but no structured output returned", verified).
@mcp.tool()
def storage_get(ref: str, max_edge: int = docparse.MAX_IMAGE_EDGE):
    """Fetch an IMAGE object (png/jpg/gif/webp) for a vision model: returned normalised to the
    sizing contract (longest edge <= max_edge, PNG/JPEG) as image content, followed by a text
    label "<name> <w>x<h> <mime>". Only for image refs — use storage_read_document /
    storage_read_vsdx for documents and Visio files. Never returns a URL."""
    with tracer.start_as_current_span("storage_get") as span:
        span.set_attribute("storage.ref", ref)
        name = _name(ref)
        if docparse.kind(name) != "image":
            raise ValueError(f"{name} is not an image; use storage_read_document / storage_read_vsdx")
        data = _store().get(ref)
        norm = docparse.normalise_image(data, docparse.media_type(name), max_edge)
        if not norm:
            raise ValueError(f"{name} is too small or not a readable image")
        out, mime, (w, h) = norm
        span.set_attributes({"storage.bytes": len(out), "storage.kind": "image",
                             "storage.width": w, "storage.height": h})
        return [_image(out, mime), f"{name} {w}x{h} {mime}"]


@mcp.tool()
def storage_read_document(ref: str, max_chars: int = docparse.MAX_DOC_CHARS) -> str:
    """Read a requirements document (.docx paragraphs + tables, .pdf page text, .md/.txt/.csv)
    into plain text (capped at max_chars with an explicit truncation marker). Read EVERY
    requirements document you were given before describing a system."""
    with tracer.start_as_current_span("storage_read_document") as span:
        span.set_attribute("storage.ref", ref)
        name = _name(ref)
        if docparse.kind(name) != "document":
            raise ValueError(f"{name} is not a document (.docx/.pdf/.md/.txt/.csv)")
        text = docparse.document_text(_store().get(ref), docparse.ext_of(name), max_chars)
        span.set_attributes({"storage.kind": "document", "storage.chars": len(text)})
        return text


@mcp.tool()
def storage_read_vsdx(ref: str) -> dict:
    """Read a Microsoft Visio .vsdx diagram into {pages, shapes, connectors} (shape captions,
    stencil masters as soft hints, directed connectors with labels). Call it with the exact
    art:// ref you were given BEFORE describing the system."""
    with tracer.start_as_current_span("storage_read_vsdx") as span:
        span.set_attribute("storage.ref", ref)
        name = _name(ref)
        if docparse.kind(name) != "vsdx":
            raise ValueError(f"{name} is not a .vsdx file")
        d = docparse.vsdx_dict(_store().get(ref), name)
        span.set_attributes({"storage.kind": "vsdx", "storage.shapes": len(d.get("shapes", [])),
                             "storage.connectors": len(d.get("connectors", []))})
        return d


@mcp.tool()
def storage_extract_figures(ref: str, max_images: int = docparse.MAX_EMBEDDED_IMAGES,
                            max_edge: int = docparse.MAX_IMAGE_EDGE):
    """Figures EMBEDDED in a .docx/.pdf (diagrams, screenshots) for a vision model: each figure
    is returned normalised as image content followed by its label "figure N embedded in <doc>".
    Decorations (icons, logos) are dropped. Returns an empty list when the document has none."""
    with tracer.start_as_current_span("storage_extract_figures") as span:
        span.set_attribute("storage.ref", ref)
        name = _name(ref)
        if docparse.kind(name) != "document":
            raise ValueError(f"{name} is not a document")
        figs = docparse.embedded_figures(_store().get(ref), docparse.ext_of(name), name, max_images, max_edge)
        span.set_attributes({"storage.kind": "document", "storage.figures": len(figs)})
        out: list = []
        for label, data, mime in figs:
            out.append(_image(data, mime)); out.append(label)
        return out


if __name__ == "__main__":
    import uvicorn
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    if config.UPLOADS_URL.startswith("s3://"):
        for k in ("S3_ENDPOINT", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
            if not os.environ.get(k):
                sys.exit(f"missing env var {k} — UPLOADS_URL is a bucket; source .env before starting")
    print(f"storage-mcp: upload store = {config.UPLOADS_URL.split('@')[-1] if '@' in config.UPLOADS_URL else config.UPLOADS_URL}")
    app = mcp.http_app(path="/mcp")
    app.add_middleware(OpenTelemetryMiddleware)
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host=config.BIND_HOST, port=config.STORAGE_MCP_PORT, log_level="info")
