"""Host process for the Visio->ArchiMate workflow — one Python host per business process
(the Azure Container Apps analogue). Sets a distinct OTel service name so this process is traced
and audited independently, opens the run's root span, wires each agent's identity, runs the
Agent Framework workflow, and reports the approval request to act on.

Two entry points share `run_once()`:
  CLI / one-shot job:  .venv/bin/python -m processes.visio_to_archimate.host [diagram] [-r docs...]
                       (or VISIO_DIAGRAM / VISIO_REQUIREMENTS env for a cloud job)
  long-lived host:     processes/visio_to_archimate/consumer.py — runs `run_once` per
                       workflow:requests event (what the review app's Submit page publishes)

Inputs are paths (local dev) or art:// refs — refs are read ONLY through the gateway's
storage-mcp tools, so this process holds no object-store credentials. All egress is governed by
the gateway; the ADOIT write is staged for human approval (review app / Telegram / CLI).
"""
import asyncio
import os
import sys
from pathlib import Path

from opentelemetry import propagate, trace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from shared.identity import agent_headers  # noqa: E402
from processes.visio_to_archimate.workflow import run_workflow  # noqa: E402

SERVICE = "process-visio-to-archimate"   # one distinct service name per business process (docx §7)
DEFAULT_VSDX = HERE / "visio-in" / "lab-system.vsdx"
_TRACER = None


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


def tracer():
    """The process tracer — set up ONCE (OpenTelemetry refuses a second global provider)."""
    global _TRACER
    if _TRACER is None:
        _TRACER = _setup_otel()
    return _TRACER


def _cred(prefix: str) -> str:
    """The agent's bearer credential (Entra JWT via MSAL, or its durable virtual key)."""
    return agent_headers(prefix)["Authorization"].removeprefix("Bearer ").strip()


async def run_once(diagram: str, requirements: list[str] | None = None, on_trace=None) -> dict:
    """One governed run: root span -> agent identities -> workflow -> approval request.
    Returns the workflow output plus `trace_id`. `on_trace(trace_id)` fires as soon as the span
    exists so a caller (the consumer) can publish it before the run finishes."""
    requirements = list(requirements or [])
    tr = tracer()
    gateway_mcp = os.environ["GATEWAY_URL"].rstrip("/") + "/mcp/"
    with tr.start_as_current_span("visio-to-archimate-run") as root:
        trace_id = format(root.get_span_context().trace_id, "032x")
        root.set_attribute("lab.trace_id", trace_id)
        root.set_attribute("visio.input", os.path.basename(diagram))
        root.set_attribute("visio.requirements", len(requirements))
        if on_trace:
            on_trace(trace_id)
        traceparent: dict = {}
        propagate.inject(traceparent)      # W3C headers for this run -> gateway + MCP join the trace
        root_ctx = trace.set_span_in_context(root)

        ba_cred, ar_cred = _cred("BA_AGENT"), _cred("ARCHITECT_AGENT")
        cfg = {
            "ba_cred": ba_cred, "ar_cred": ar_cred,
            "traceparent": traceparent,          # W3C headers for the agents' LLM calls (join the trace)
            # the BA reads its inputs (refs) through the gateway's storage-mcp with ITS identity;
            # tool nodes + the Architect's in-agent tools call the gateway MCP with the Architect's
            # identity (its key holds the ADOIT/semantic grants) + traceparent
            "ba_headers": {"Authorization": f"Bearer {ba_cred}", **traceparent},
            "ar_headers": {"Authorization": f"Bearer {ar_cred}", **traceparent},
            "mcp_url": gateway_mcp,
            "schema": _load_schema(),
            "tracer": tr, "root_ctx": root_ctx,
            "outdir": str(HERE / "out"),
        }
        out = await run_workflow(cfg, {"diagram": diagram, "requirements": requirements})
    return {**out, "trace_id": trace_id}


async def main(diagram: str, requirements: list[str] | None = None):
    print(f"input:    {diagram}")
    for req in requirements or []:
        print(f"requires: {req}")
    out = await run_once(diagram, requirements, on_trace=lambda t: print(f"trace id: {t}"))
    _shutdown()
    print("\n=== result ===")
    print(f"model elements/relations: {out['summary']['elements']}/{out['summary']['relations']}  "
          f"views: {out['summary']['views']}  semantic warnings: {out['summary']['semantic_warnings']}")
    print(f"artifacts: {out['xml_ref']}  (+{len(out['svg_refs'])} svg refs)")
    print(f"approval requested: {out['request_id']} -> {out['status']}")
    print(f"review at: {out.get('review_app')}   (./lab.sh review)")
    print(f"trace:     {os.environ.get('JAEGER_UI_URL', 'http://127.0.0.1:16686')}  (id {out['trace_id']})")


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
