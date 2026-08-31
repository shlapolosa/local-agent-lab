"""Host process for the Visio->ArchiMate workflow — one Python host per business process
(the Azure Container Apps analogue). Sets a distinct OTel service name so this process is traced
and audited independently, opens the run's root span, wires each agent's identity, runs the
Agent Framework workflow, and prints the approval request to act on.

  .venv/bin/python -m processes.visio_to_archimate.host [path/to/diagram.vsdx]

Default input is the round-trip fixture visio-in/lab-system.vsdx. All egress is governed by the
gateway; the ADOIT write is staged for human approval (review app / Telegram / CLI).
"""
import asyncio
import os
import sys
from pathlib import Path

from opentelemetry import propagate, trace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from shared.identity import agent_headers  # noqa: E402
from processes.visio_to_archimate import agents as A  # noqa: E402
from processes.visio_to_archimate.workflow import run_workflow  # noqa: E402

SERVICE = "process-visio-to-archimate"   # one distinct service name per business process (docx §7)
DEFAULT_VSDX = HERE / "visio-in" / "lab-system.vsdx"
GATEWAY_MCP = os.environ["GATEWAY_URL"].rstrip("/") + "/mcp/"


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


def _cred(prefix: str) -> str:
    """The agent's bearer credential (Entra JWT via MSAL, or its durable virtual key)."""
    return agent_headers(prefix)["Authorization"].removeprefix("Bearer ").strip()


async def main(path: str):
    tracer = _setup_otel()
    with tracer.start_as_current_span("visio-to-archimate-run") as root:
        trace_id = format(root.get_span_context().trace_id, "032x")
        root.set_attribute("lab.trace_id", trace_id)
        root.set_attribute("visio.input", os.path.basename(path))
        traceparent: dict = {}
        propagate.inject(traceparent)      # W3C headers for this run -> gateway + MCP join the trace
        root_ctx = trace.set_span_in_context(root)

        ba_cred, ar_cred = _cred("BA_AGENT"), _cred("ARCHITECT_AGENT")
        cfg = {
            "ba_agent": A.make_agent("ba-agent", A.ba_instructions(), ba_cred, traceparent),
            "architect_agent": A.make_agent("architect-agent", A.architect_instructions(), ar_cred, traceparent),
            # tool nodes call the gateway MCP with the Architect's identity (holds ADOIT/semantic grants)
            "mcp_headers": {"Authorization": f"Bearer {ar_cred}", **traceparent},
            "mcp_url": GATEWAY_MCP,
            "schema": _load_schema(),
            "tracer": tracer, "root_ctx": root_ctx,
            "outdir": str(HERE / "out"),
        }
        print(f"trace id: {trace_id}")
        print(f"input:    {path}")
        out = await run_workflow(cfg, path)

    _shutdown()
    print("\n=== result ===")
    print(f"model elements/relations: {out['summary']['elements']}/{out['summary']['relations']}  "
          f"views: {out['summary']['views']}  semantic warnings: {out['summary']['semantic_warnings']}")
    print(f"artifacts: {out['xml_ref']}  (+{len(out['svg_refs'])} svg refs)")
    print(f"approval requested: {out['request_id']} -> {out['status']}")
    print(f"review at: {out.get('review_app')}   (./lab.sh review)")
    print(f"trace:     {os.environ.get('JAEGER_UI_URL', 'http://127.0.0.1:16686')}  (id {trace_id})")


def _load_schema():
    import json
    return json.loads((HERE / "schemas" / "ba_output.schema.json").read_text())


def _shutdown():
    tp = trace.get_tracer_provider()
    if hasattr(tp, "shutdown"):
        tp.shutdown()


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_VSDX)
    if not os.path.exists(p):
        sys.exit(f"no such file: {p}")
    asyncio.run(main(p))
