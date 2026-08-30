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

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = "http://127.0.0.1:4000/mcp/"
SERVICE = "process-ea-modelling"


async def main(scheme, root, depth):
    from architecture.run_via_gateway import _setup_otel  # same service name / exporter
    tracer = _setup_otel()
    with tracer.start_as_current_span("capability-export-run") as span:
        headers = {"Authorization": f"Bearer {os.environ['EA_AGENT_KEY']}"}
        propagate.inject(headers)
        print("trace id:", format(span.get_span_context().trace_id, "032x"))
        async with Client(StreamableHttpTransport(GATEWAY, headers=headers)) as c:
            names = [t.name for t in await c.list_tools()]
            pick = lambda suf: next(n for n in names if n.endswith(suf))
            os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
            out_path = os.path.join(HERE, "out", f"{scheme}-export.json")
            spec = (await c.call_tool(pick("semantic_export_archimate"), {
                "scheme": scheme, "root_label": root, "depth": depth, "out_path": out_path})).data
            print(f"exported: {spec['name']} — {spec['elements']} elements, "
                  f"{spec['relations']} compositions, {spec['views']} views -> {spec['spec_path']}")
            base = spec["id"]
            res = (await c.call_tool(pick("archimate_render"), {          # by reference: no payload
                "spec_path": spec["spec_path"], "outdir": os.path.join(HERE, "out"), "basename": base})).data
            print("violations:", len(res["violations"]), "| warnings:", len(res["warnings"]),
                  "| views:", len(res["views"]))
            xml = next(f for f in res["files"] if f.endswith(".archimate.xml"))
            req = (await c.call_tool(pick("adoit_request_import"), {
                "xml_path": xml, "model_name": spec["name"],
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
