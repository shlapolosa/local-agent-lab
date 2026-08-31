"""End-to-end agent run: this client is what any lab agent does — one gateway
endpoint (LiteLLM /mcp), gateway key auth, no tool credentials held locally.

  agent -> LiteLLM MCP gateway (:4000/mcp) -> adoit-mcp (:9100) -> archimate engine / ADOIT

Usage:  .venv/bin/python architecture/run_via_gateway.py
"""
import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from opentelemetry import propagate, trace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config  # noqa: E402
from shared.identity import agent_headers  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = config.GATEWAY_MCP_URL
SERVICE = "process-ea-modelling"      # one distinct service name per business process (docx §7)


def _setup_otel():
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return trace.get_tracer(SERVICE)
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(SERVICE)


async def main():
    tracer = _setup_otel()
    spec = json.load(open(os.path.join(HERE, "lab_model.json")))
    with tracer.start_as_current_span("ea-modeling-run") as root:   # the workflow-run span
        headers = agent_headers()      # Entra JWT via MSAL (app registration), or static key fallback
        propagate.inject(headers)      # traceparent -> gateway -> adoit-mcp: one trace
        root.set_attribute("lab.trace_id", format(root.get_span_context().trace_id, "032x"))
        print("trace id:", format(root.get_span_context().trace_id, "032x"))
        await _run(tracer, spec, headers)
    trace.get_tracer_provider().shutdown() if hasattr(trace.get_tracer_provider(), "shutdown") else None


async def _run(tracer, spec, headers):
    transport = StreamableHttpTransport(GATEWAY, headers=headers)
    async with Client(transport) as c:
        tools = await c.list_tools()
        names = [t.name for t in tools]
        print("tools via gateway:", names)

        def pick(suffix):
            m = [n for n in names if n.endswith(suffix)]
            if not m:
                sys.exit(f"tool {suffix} not exposed by gateway")
            return m[0]

        with tracer.start_as_current_span("tool adoit_repos"):
            repos = await c.call_tool(pick("adoit_repos"), {})
        print("ADOIT repos (read via governed facade):", json.dumps(repos.data)[:160])

        # semantic layer first: exact ArchiMate legality + interface semantics, then load for questions
        with tracer.start_as_current_span("tool semantic_validate_model"):
            sem = await c.call_tool(pick("semantic_validate_model"), {"spec": spec})
        print(f"semantic: {len(sem.data['illegal'])} illegal relationships, {len(sem.data['warnings'])} warnings")
        for i in sem.data["illegal"]:
            print("  ILLEGAL", i)
        with tracer.start_as_current_span("tool semantic_load_model"):
            ld = await c.call_tool(pick("semantic_load_model"), {"spec": spec, "model_id": spec["id"]})
        print(f"semantic store: {ld.data['triples']} triples, {ld.data['derived_relations']} derived relations")
        with tracer.start_as_current_span("tool semantic_ask"):
            ans = await c.call_tool(pick("semantic_ask"), {
                "question": "goals_realized_by_components_on_node", "params": {"node": "M1"}})
        print("ask:", ans.data["question"])
        for row in ans.data["rows"]:
            print("   ", " -> ".join(row))

        with tracer.start_as_current_span("tool archimate_validate"):
            val = await c.call_tool(pick("archimate_validate"), {"spec": spec})
        print(f"validate: {val.data['elements']} elements, {val.data['relations']} relations, "
              f"{len(val.data['warnings'])} warnings")
        for w in val.data["warnings"]:
            print("  WARN:", w)

        with tracer.start_as_current_span("tool archimate_render"):
            res = await c.call_tool(pick("archimate_render"), {
                "spec": spec, "basename": "lab-architecture", "outdir": os.path.join(HERE, "out")})
        print("violations:", res.data["violations"])
        print("warnings:", len(res.data["warnings"]))
        for vid, canvas in res.data["views"].items():
            print(f"  view {vid}: {canvas[0]}x{canvas[1]}")
        print("artifacts:", res.data["xml_ref"], f'+ {len(res.data["svg_refs"])} svg refs')

        # governed write path: stage for human approval (review app / Telegram / CLI)
        with tracer.start_as_current_span("tool adoit_request_import"):
            summary = {"elements": val.data["elements"], "relations": val.data["relations"],
                       "views": len(res.data["views"]), "violations": len(res.data["violations"]),
                       "warnings": len(res.data["warnings"])}
            req = await c.call_tool(pick("adoit_request_import"), {
                "xml_ref": res.data["xml_ref"], "svg_refs": res.data["svg_refs"],
                "model_name": spec["name"], "summary": summary})
        print(f"approval requested: {req.data['request_id']} -> status {req.data['status']} "
              f"(review at {req.data['review_app']})")
        st = await c.call_tool(pick("adoit_import_status"), {"request_id": req.data["request_id"]})
        print("import status:", st.data["status"], "—", st.data["next"])


if __name__ == "__main__":
    asyncio.run(main())
