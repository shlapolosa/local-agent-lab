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

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = "http://127.0.0.1:4000/mcp/"
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
    key = os.environ["EA_AGENT_KEY"]   # agent identity, never the master key
    spec = json.load(open(os.path.join(HERE, "lab_model.json")))
    with tracer.start_as_current_span("ea-modeling-run") as root:   # the workflow-run span
        headers = {"Authorization": f"Bearer {key}"}
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

        with tracer.start_as_current_span("tool archimate_validate"):
            val = await c.call_tool(pick("archimate_validate"), {"spec": spec})
        print(f"validate: {val.data['elements']} elements, {val.data['relations']} relations, "
              f"{len(val.data['warnings'])} warnings")
        for w in val.data["warnings"]:
            print("  WARN:", w)

        with tracer.start_as_current_span("tool archimate_render"):
            res = await c.call_tool(pick("archimate_render"), {
                "spec": spec, "outdir": os.path.join(HERE, "out"), "basename": "lab-architecture"})
        print("violations:", res.data["violations"])
        print("warnings:", len(res.data["warnings"]))
        for vid, canvas in res.data["views"].items():
            print(f"  view {vid}: {canvas[0]}x{canvas[1]}")
        print("files:")
        for f in res.data["files"]:
            print("  ", f)


if __name__ == "__main__":
    asyncio.run(main())
