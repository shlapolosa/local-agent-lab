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


async def main(diagram: str, requirements: list[str] | None = None):
    requirements = list(requirements or [])
    tracer = _setup_otel()
    with tracer.start_as_current_span("visio-to-archimate-run") as root:
        trace_id = format(root.get_span_context().trace_id, "032x")
        root.set_attribute("lab.trace_id", trace_id)
        root.set_attribute("visio.input", os.path.basename(diagram))
        root.set_attribute("visio.requirements", len(requirements))
        traceparent: dict = {}
        propagate.inject(traceparent)      # W3C headers for this run -> gateway + MCP join the trace
        root_ctx = trace.set_span_in_context(root)

        ba_cred, ar_cred = _cred("BA_AGENT"), _cred("ARCHITECT_AGENT")
        cfg = {
            "ba_cred": ba_cred, "ar_cred": ar_cred,
            "traceparent": traceparent,          # W3C headers for the agents' LLM calls (join the trace)
            # tool nodes + the Architect's in-agent tools call the gateway MCP with the Architect's
            # identity (its key holds the ADOIT/semantic grants) + traceparent
            "ar_headers": {"Authorization": f"Bearer {ar_cred}", **traceparent},
            "mcp_url": GATEWAY_MCP,
            "schema": _load_schema(),
            "tracer": tracer, "root_ctx": root_ctx,
            "outdir": str(HERE / "out"),
        }
        print(f"trace id: {trace_id}")
        print(f"input:    {diagram}")
        for req in requirements:
            print(f"requires: {req}")
        out = await run_workflow(cfg, {"diagram": diagram, "requirements": requirements})

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
    import argparse
    ap = argparse.ArgumentParser(description="Visio/diagram (+ requirements) -> ArchiMate, staged for approval")
    ap.add_argument("diagram", nargs="?", default=str(DEFAULT_VSDX),
                    help="the system diagram: a .vsdx OR an image (.png/.jpg/...), as a path or an art:// ref")
    ap.add_argument("-r", "--requirements", nargs="*", default=[],
                    help="requirements documents (.docx/.pdf/.md/.txt), paths or art:// refs "
                         "(upload: python -m processes.visio_to_archimate.inputs upload <files>)")
    a = ap.parse_args()
    # A cloud job has no CLI: VISIO_DIAGRAM / VISIO_REQUIREMENTS (space-separated) env vars — set
    # as `# CLOUD:` lines in .env, typically art:// refs from `inputs upload` — override the
    # defaults, so the same container runs real uploaded inputs instead of the generated fixture.
    if len(sys.argv) == 1:
        a.diagram = os.environ.get("VISIO_DIAGRAM") or a.diagram
        a.requirements = os.environ.get("VISIO_REQUIREMENTS", "").split() or a.requirements
    for src in [a.diagram, *a.requirements]:
        if not src.startswith("art://") and not os.path.exists(src):
            sys.exit(f"no such file: {src}")
    asyncio.run(main(a.diagram, a.requirements))
