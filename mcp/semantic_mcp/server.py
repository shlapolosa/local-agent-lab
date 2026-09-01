"""semantic-mcp — the lab's semantic layer as governed MCP tools (port 9200, /mcp).

Separate from adoit-mcp on purpose: this server is domain-general (vocabularies are data —
ArchiMate today, DOH glossaries / FHIR / TOGAF later), holds no credentials and only answers
questions, so it is granted to every team; adoit-mcp is the EA-repository facade with the
governed write path. Same engine library for both worlds: the skill imports `semantic`
directly, agents reach it through LiteLLM's MCP gateway.

Tools
  semantic_ontologies()                       vocabularies available + sizes
  semantic_describe(type, vocab)              classification card: layer, aspect, definition, examples, confusables
  semantic_classify(text, vocab)              candidate types for a concept description (agent decides)
  semantic_check(source, relation, target)    exact legality (ArchiMate Appendix B matrix) + what IS allowed
  semantic_validate_model(spec)               all illegal relationships + semantic warnings (interface exposure…)
  semantic_load_model(spec, model_id)         model -> RDF with derived relations, queryable
  semantic_query(sparql)                      SPARQL over vocabularies + loaded models
  semantic_ask(question, params)              named traceability questions; semantic_questions() lists them
"""
import json
import os
import sys

from fastmcp import FastMCP

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from semantic.service import SemanticService  # noqa: E402
from shared import artifacts, config  # noqa: E402
from shared.mcpauth import BearerAuthMiddleware  # noqa: E402

SERVICE = "semantic-mcp"


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
S = SemanticService()


@mcp.tool()
def semantic_ontologies() -> list:
    """Vocabularies available in the semantic layer and their sizes."""
    return S.ontologies()


@mcp.tool()
def semantic_describe(type: str, vocab: str = "archimate-3.1") -> dict:
    """Classification card for an element type: layer, aspect (active/behaviour/passive),
    definition, examples, and what it is commonly confused with."""
    return S.describe(type, vocab)


@mcp.tool()
def semantic_classify(text: str, vocab: str = "archimate-3.1", limit: int = 5) -> list:
    """Candidate element types for a concept described in words (e.g. 'REST API exposed by
    the backend'). Deterministic keyword scoring — the agent makes the final call using the
    definitions returned."""
    with tracer.start_as_current_span("semantic_classify"):
        return S.classify(text, vocab, limit)


@mcp.tool()
def semantic_check(source: str, relation: str, target: str, vocab: str = "archimate-3.1") -> dict:
    """Is `relation` permitted from element type `source` to `target`? Exact answer from the
    ArchiMate relationship matrix, plus the full list of what is allowed for that pair."""
    return S.check(source, relation, target, vocab)


@mcp.tool()
def semantic_validate_model(spec: dict | None = None, vocab: str = "archimate-3.1",
                            spec_ref: str | None = None) -> dict:
    """Validate a model spec (same JSON as archimate_render): every illegal relationship with
    the allowed alternatives, plus semantic warnings such as services consumed without an
    interface assigned to them. Pass the spec by value (`spec`) or by artifact reference
    (`spec_ref`, art://…) — the reference keeps the tool argument small for agent callers."""
    with tracer.start_as_current_span("semantic_validate_model") as span:
        if spec_ref:
            spec = json.loads(artifacts.store().get(spec_ref))
        elif isinstance(spec, str):
            spec = json.loads(spec)   # agents often serialize the nested object as a JSON string
        r = S.validate_model(spec, vocab)
        span.set_attributes({"semantic.illegal": len(r["illegal"]), "semantic.warnings": len(r["warnings"])})
        return r


@mcp.tool()
def semantic_load_model(spec: dict, model_id: str, vocab: str = "archimate-3.1") -> dict:
    """Load a model into the semantic store as RDF (with derived relationships) so it can
    be queried with semantic_query / semantic_ask."""
    with tracer.start_as_current_span("semantic_load_model"):
        return S.load_model(spec, model_id, vocab)


@mcp.tool()
def semantic_query(sparql: str, limit: int = 200) -> dict:
    """Run SPARQL across the vocabularies and every loaded model. Prefixes:
    am: <urn:lab:semantic:archimate#>  meta: <urn:lab:semantic:meta#>. Derived relations
    are am:derivedRealization / am:derivedServing / am:derivedAssignment / ..."""
    with tracer.start_as_current_span("semantic_query"):
        return S.query(sparql, limit)


@mcp.tool()
def semantic_schemes() -> list:
    """Reference models loaded as SKOS concept schemes (capability maps, value streams,
    organisation / stakeholder / information maps) with per-kind, per-level counts."""
    return S.schemes()


@mcp.tool()
def semantic_concepts(scheme: str, root_label: str | None = None, depth: int | None = None,
                      kind: str = "capability") -> list:
    """Concepts of a reference scheme: the whole map, or the subtree under `root_label`
    (e.g. 'Patient Management') to `depth` levels. kinds: capability, value-stream, org-unit,
    stakeholder, information."""
    return S.concepts(scheme, root_label, depth, kind)


@mcp.tool()
def semantic_export_archimate(scheme: str, root_label: str | None = None, depth: int | None = None,
                              kind: str = "capability", views: str = "overview,branches",
                              out_path: str | None = None, by_ref: bool = True) -> dict:
    """Project a reference scheme (or subtree) to an ArchiMate model spec — Capability /
    ValueStream elements with Composition, plus an L1 overview view and one nested view per
    top concept. Feed the result to adoit-mcp's archimate_render + adoit_request_import: that
    is the governed way to write reference capabilities into ADOIT.
    By default the spec is stored as an artifact and only counts + spec_ref (art://…) are
    returned — the gateway meters tool payloads as tokens and adoit-mcp accepts spec_ref from
    any host. by_ref=False returns the payload inline (small subtrees); out_path also writes a
    local copy (dev)."""
    import json
    with tracer.start_as_current_span("semantic_export_archimate") as span:
        spec = S.export_archimate(scheme, root_label, depth, kind, views)
        span.set_attributes({"semantic.scheme": scheme, "semantic.elements": len(spec["elements"])})
        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            json.dump(spec, open(out_path, "w"), indent=0)
        if by_ref:
            ref = artifacts.store().put(f'{spec["id"]}.spec.json', json.dumps(spec).encode(), "application/json")
            return {"spec_ref": ref, "spec_path": out_path, "name": spec["name"], "id": spec["id"],
                    "elements": len(spec["elements"]), "relations": len(spec["relations"]),
                    "views": len(spec["views"])}
        return spec


@mcp.tool()
def semantic_questions() -> dict:
    """Named traceability questions available to semantic_ask, with their parameters."""
    return S.questions()


@mcp.tool()
def semantic_ask(question: str, params: dict | None = None) -> dict:
    """Ask a named question, e.g. semantic_ask('goals_realized_by_components_on_node',
    {'node': 'M1'}) -> which goals are transitively realized by components on that node."""
    with tracer.start_as_current_span("semantic_ask") as span:
        span.set_attribute("semantic.question", question)
        return S.ask(question, **(params or {}))


if __name__ == "__main__":
    import uvicorn
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    app = mcp.http_app(path="/mcp")
    app.add_middleware(OpenTelemetryMiddleware)
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host=config.BIND_HOST, port=config.SEMANTIC_MCP_PORT, log_level="info")
