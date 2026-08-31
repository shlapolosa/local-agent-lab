"""Governed export of a reference capability map into ADOIT.

  semantic-mcp  : semantic_export_archimate(scheme, root, depth)  -> ArchiMate spec (read-only)
  adoit-mcp     : archimate_render(spec) -> XML + SVG views ; adoit_request_import -> approval

Usage: .venv/bin/python architecture/export_capabilities.py <scheme> [root_label] [depth]
   e.g. ... healthcare-provider-v2.0                       (whole map, L1 overview + L2 branch views)
        ... healthcare-provider-v2.0 "Patient Management" 3
"""
import asyncio
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
SERVICE = "process-ea-modelling"


async def main(scheme, root, depth):
    from architecture.run_via_gateway import _setup_otel  # same service name / exporter
    tracer = _setup_otel()
    with tracer.start_as_current_span("capability-export-run") as span:
        headers = agent_headers()   # Entra JWT via MSAL, or the static key fallback
        propagate.inject(headers)
        print("trace id:", format(span.get_span_context().trace_id, "032x"))
        async with Client(StreamableHttpTransport(GATEWAY, headers=headers)) as c:
            names = [t.name for t in await c.list_tools()]
            pick = lambda suf: next(n for n in names if n.endswith(suf))
            spec = (await c.call_tool(pick("semantic_export_archimate"), {
                "scheme": scheme, "root_label": root, "depth": depth})).data     # by reference (art://)
            print(f"exported: {spec['name']} — {spec['elements']} elements, "
                  f"{spec['relations']} compositions, {spec['views']} views -> {spec['spec_ref']}")
            base = spec["id"]
            res = (await c.call_tool(pick("archimate_render"), {          # no payload crosses the gateway
                "spec_ref": spec["spec_ref"], "basename": base})).data
            print("violations:", len(res["violations"]), "| warnings:", len(res["warnings"]),
                  "| views:", len(res["views"]), "| xml:", res["xml_ref"])
            req = (await c.call_tool(pick("adoit_request_import"), {
                "xml_ref": res["xml_ref"], "svg_refs": res["svg_refs"], "model_name": spec["name"],
                "summary": {"elements": spec["elements"], "relations": spec["relations"],
                            "views": len(res["views"]), "violations": len(res["violations"]),
                            "warnings": len(res["warnings"])}})).data
            print(f"approval requested: {req['request_id']} ({req['status']}) — review at {req['review_app']}")
    trace.get_tracer_provider().shutdown() if hasattr(trace.get_tracer_provider(), "shutdown") else None


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(HERE))
    a = sys.argv[1:]
    asyncio.run(main(a[0] if a else "healthcare-provider-v2.0",
                     a[1] if len(a) > 1 else None, int(a[2]) if len(a) > 2 else None))
