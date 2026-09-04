"""LOCAL dev-time entry: the Visio->ArchiMate workflow inside Microsoft Agent Framework **DevUI**
(live graph + per-node events + trace panel while a run executes). See DEVUI.md.

    .venv/bin/python -m lab.workloads.visio_to_archimate.devui_entry        # http://127.0.0.1:8090

This is a THIRD host for the same workflow, next to `host.py` (one-shot) and `consumer.py`
(long-lived): it assembles `cfg` exactly the way `host.run_once` does — same credential helpers,
same gateway MCP URL, same schema, same config builder — from ITS OWN container (its own OTel service
name, so DevUI-driven runs are told apart in Jaeger; `host.SERVICE` is never mutated) and hands the
built `Workflow` object to DevUI's in-memory registry (`serve(entities=[...])`). Nothing here changes
the governed path: every LLM and tool call a DevUI-triggered run makes still goes through the gateway
with each agent's own identity, is metered, PII-guarded and traced.

Dev-only by construction: `agent-framework-devui` is deliberately NOT in deploy/requirements.txt
(its prerelease pins broke the container build), so this module is never imported by the
container roles. Locally it is already present in `.venv` — pulled in by the `agent-framework`
1.16.0 meta package — so nothing is installed for it.
"""
import argparse
import json
import os

if __name__ == "__main__":
    # Running bare (`python -m …devui_entry`) there is no `set -a; source .env` (lab.sh does that for
    # the other hosts), so load it HERE — before lab.platform.config reads the environment, and ONLY when
    # this module is the script: merely IMPORTING a workload module must never pull the substrate's
    # credentials into the process (CLAUDE.md: workloads hold no store credentials). Values already
    # exported by the shell win (override=False).
    from dotenv import find_dotenv, load_dotenv  # (python-dotenv comes with agent-framework-core)

    load_dotenv(find_dotenv(), override=False)

from opentelemetry import propagate, trace  # noqa: E402

from lab.workloads.visio_to_archimate import host as H  # noqa: E402
from lab.workloads.visio_to_archimate.workflow import build_workflow, make_cfg  # noqa: E402
from lab.platform import config, container  # noqa: E402

# Distinct OTel service name per host (CLAUDE.md invariant): this host's container installs the
# provider under it — the first tracer taken in the process names the service.
SERVICE = "process-visio-to-archimate-devui"
DEFAULT_PORT = int(os.environ.get("DEVUI_PORT", "8090"))       # 8080 is DevUI's default; kept clear of it
DEFAULT_DIAGRAM = f"{config.VAR_DIR / 'inputs' / 'visio_to_archimate' / 'malaffi-application-solution-arch.vsdx'}#Shafafiya"
# The start executor (`ba`) takes a dict, so DevUI renders a JSON input ({"type": "object"}) —
# paste this. A bare string would reach the node un-wrapped (DevUI only json-parses strings).
DEFAULT_INPUT = {"diagram": DEFAULT_DIAGRAM, "requirements": []}


def build_cfg(root) -> tuple[dict, str]:
    """`cfg` as host.run_once builds it, minus the per-run root span: DevUI owns the run loop, so
    the root here is ONE session span (started and ended immediately so it is exported; its context
    remains a valid parent). Every node span of every run in this DevUI session, and — via the
    injected traceparent — every gateway/MCP span, joins that one trace. `root` is this host's
    container (the tracer comes from it). Returns (cfg, trace_id)."""
    tr = root.tracer()
    span = tr.start_span("visio-to-archimate-devui-session")
    trace_id = format(span.get_span_context().trace_id, "032x")
    span.set_attribute("lab.trace_id", trace_id)
    span.set_attribute("devui.default_input", os.path.basename(DEFAULT_DIAGRAM))
    root_ctx = trace.set_span_in_context(span)
    traceparent: dict = {}
    propagate.inject(traceparent, context=root_ctx)   # W3C headers: gateway + MCP servers join the trace
    span.end()

    # same identities as host.run_once, and the SAME config builder (workflow.make_cfg) so DevUI can
    # never drift from the host again (review A-F12). run_id stays None: cfg is per-session here while
    # run ids are per-run — DevUI has its own live view; the Runs board tracks CLI/consumer runs.
    cfg = make_cfg(ba_cred=H._cred("BA_AGENT"), ar_cred=H._cred("ARCHITECT_AGENT"),
                   traceparent=traceparent, schema=H._load_schema(), tracer=tr, root_ctx=root_ctx,
                   mcp_url=root.config.gateway_mcp_url(), run_id=None)
    return cfg, trace_id


def build(root):
    """Build (never run) the workflow object DevUI will serve. Returns (workflow, trace_id)."""
    cfg, trace_id = build_cfg(root)
    wf = build_workflow(cfg)
    # DevUI names the entity from these (workflow.py builds it unnamed -> "Workflow Workflow").
    wf.name = "visio-to-archimate"
    wf.description = ("Visio/diagram (+ requirements) -> BA -> resolve existing (ADOIT) -> Architect -> "
                      "store by ref -> validate+render by ref -> stage ADOIT import (human approval). "
                      "Input is JSON, e.g. " + json.dumps(DEFAULT_INPUT))
    return wf, trace_id


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Serve the Visio->ArchiMate workflow in Agent Framework DevUI (local dev only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"listen port (default {DEFAULT_PORT}, env DEVUI_PORT)")
    ap.add_argument("--headless", action="store_true", help="API only, no UI (used by the boot check)")
    ap.add_argument("--open", action="store_true", help="open the browser once the server is up")
    ap.add_argument("--auth", action="store_true",
                    help="require a Bearer token (DevUI generates and logs one). Off by default: loopback only")
    ap.add_argument("--sensitive-spans", action="store_true",
                    help="put prompt/response bodies on AF spans (they reach whatever OTEL endpoint .env points at)")
    a = ap.parse_args(argv)

    # Agent Framework's own spans (workflow.run, executor, chat) -> DevUI's trace panel AND our OTLP
    # exporter. serve(instrumentation_enabled=True) would force sensitive data ON; enable it here
    # instead so prompt bodies leave the process only on request.
    from agent_framework.observability import enable_instrumentation
    enable_instrumentation(enable_sensitive_data=a.sensitive_spans)

    root = container.build(SERVICE)                     # DevUI's own composition root (own service name)
    wf, trace_id = build(root)
    print(f"DevUI:          http://127.0.0.1:{a.port}   ({'API only' if a.headless else 'UI'}; auth {'on' if a.auth else 'off'})")
    print(f"workflow:       {wf.name}  nodes: {' -> '.join(str(getattr(e, 'id', e)) for e in wf.get_executors_list())}")
    print(f"gateway MCP:    {root.config.gateway_mcp_url()}   (./lab.sh up first)")
    print(f"paste as input: {json.dumps(DEFAULT_INPUT)}")
    print(f"session trace:  {root.config.jaeger_ui_url()}/trace/{trace_id}   (service {SERVICE}; every run this session joins it)")
    print("NOTE: each run makes real gateway LLM + MCP calls and stages an ADOIT approval request.")

    from agent_framework.devui import serve
    serve(entities=[wf], port=a.port, host="127.0.0.1", auto_open=a.open, ui_enabled=not a.headless,
          instrumentation_enabled=False, auth_enabled=a.auth)


if __name__ == "__main__":
    main()
