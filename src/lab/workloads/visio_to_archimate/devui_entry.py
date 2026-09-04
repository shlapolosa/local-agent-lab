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

Every DevUI run is ALSO a first-class run on the review app's Runs board: `instrument_runs()` wraps
the built workflow's `run` so each run opens its own run-log entry (`lab.platform.runlog`) before it
executes and closes it when its event stream ends — carrying the run's own output (the approval
request id and the artifact refs, read off the AF `output` event as it passes) onto the finished
row, so a DevUI row links to what the run produced exactly like a CLI one. So a reviewer watches a
DevUI run — its nodes, what it produced, and the LLM/tool calls the trace recorded for them — from
the ONE approval UI, without the DevUI window and without having triggered it. DevUI's own live
view is untouched: the wrapper forwards every event and delegates the rest of the ResponseStream API.

Dev-only by construction: `agent-framework-devui` is deliberately NOT in deploy/requirements.txt
(its prerelease pins broke the container build), so this module is never imported by the
container roles. Locally it is already present in `.venv` — pulled in by the `agent-framework`
1.16.0 meta package — so nothing is installed for it.
"""
import argparse
import itertools
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

from lab.workloads import workflowviz  # noqa: E402
from lab.workloads.visio_to_archimate import host as H  # noqa: E402
from lab.workloads.visio_to_archimate.workflow import build_workflow, make_cfg  # noqa: E402
from lab.platform import config, container, runlog  # noqa: E402

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
    # never drift from the host again (review A-F12). `run_id` starts None and is set PER RUN by
    # instrument_runs(): workflow.build_workflow reads `cfg["run_id"]` lazily, once per node, and
    # Agent Framework refuses concurrent runs on one Workflow instance — so one mutable cfg per
    # session carries a per-run id safely. The TRACE stays per session (the root context and the
    # traceparent are captured when the graph is built), which costs nothing on the Runs board: the
    # per-node detail is grouped by the run's own node windows, not by the trace.
    cfg = make_cfg(ba_cred=H._cred("BA_AGENT"), ar_cred=H._cred("ARCHITECT_AGENT"),
                   traceparent=traceparent, schema=H._load_schema(), tracer=tr, root_ctx=root_ctx,
                   mcp_url=root.config.gateway_mcp_url(), run_id=None)
    return cfg, trace_id


def _input_label(message) -> str:
    """What the Runs board shows as the run's input: the diagram's file name."""
    diagram = message.get("diagram") if isinstance(message, dict) else message
    return os.path.basename(str(diagram)) if diagram else "?"


def _output_of(event):
    """The workflow's own output carried by one DevUI stream event, or None. Agent Framework emits
    what an executor `yield_output(...)`s as an event of `type` "output" whose `data` IS that value
    (verified against agent_framework 1.16.0) — and this is the only place a streamed run can learn
    what it produced: DevUI owns the run loop, so nothing here ever sees its `WorkflowRunResult`.
    The type check is load-bearing: `executor_invoked`/`executor_completed` events carry dict/list
    payloads of their own."""
    if getattr(event, "type", None) != "output":
        return None
    data = getattr(event, "data", None)
    return data if isinstance(data, dict) else None


def _result_output(result):
    """The workflow output of a NON-streamed run: `WorkflowRunResult.get_outputs()` — the same call
    `workflow.run_workflow` makes. Anything that cannot answer yields no references rather than an
    exception: this is visibility, and it must never fail a run that already completed."""
    try:
        outs = result.get_outputs()
    except Exception:                 # noqa: BLE001 — see above
        return None
    return next((o for o in (outs or []) if isinstance(o, dict)), None)


class _LoggedStream:
    """The workflow's event stream with the run-log closed when the stream ENDS — however the caller
    consumes it — and the run's OUTPUT picked up in passing, so the finished row links to the
    approval request and the artifacts the run produced. Agent Framework's `ResponseStream` is
    iterable (`__aiter__` + `__anext__`) AND awaitable (`await stream` only RESOLVES the source and
    hands the stream back — it consumes nothing, so it must not close the run). Python resolves
    dunders on the TYPE, not through `__getattr__`, so each is delegated explicitly; everything else
    (`get_final_response()`, …) still goes through `__getattr__`. Closing is idempotent: exactly one
    `finish` per run, whichever path ends it."""

    def __init__(self, inner, close):
        self._inner, self._close, self._it, self._closed = inner, close, None, False
        self._output = None                  # the last `yield_output` seen on the way past

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _finish(self, error):
        if not self._closed:
            self._closed = True
            self._close(error, self._output)

    def __aiter__(self):
        if self._it is None:      # ResponseStream hands back itself; an async generator a new one
            self._it = self._inner.__aiter__()
        return self

    async def __anext__(self):
        self.__aiter__()          # an explicit pull loop may never have called __aiter__
        try:
            event = await self._it.__anext__()
            self._output = _output_of(event) or self._output
            return event
        except StopAsyncIteration:
            self._finish(None)
            raise
        except BaseException as e:      # noqa: BLE001 — recorded, then re-raised untouched
            self._finish(e)
            raise

    def __await__(self):
        async def resolve():
            await self._inner
            return self
        return resolve().__await__()


def instrument_runs(wf, cfg, trace_id: str, *, client=None, mermaid: str | None = None):
    """Make every run of `wf` a run on the review app's Runs board.

    DevUI owns the run loop, so this wraps the workflow's own `run`: each call takes the next run id
    (`<session trace>-<n>`), publishes it on `cfg` — which `workflow.build_workflow` reads lazily per
    node — opens the run-log entry, and closes it when the stream (or the awaited result) ends,
    carrying the run's own output (approval request + artifact refs) onto the finished row. The
    inner call happens FIRST, so a run Agent Framework refuses (concurrent runs on one instance) logs
    nothing. (A DevUI checkpoint/HIL resume — `run(stream=True, responses=…, checkpoint_id=…)`, no
    message — counts as a NEW run here; harmless until this workflow gains an in-graph HIL pause.)"""
    inner, seq = wf.run, itertools.count(1)

    def close(run_id, error, output=None):
        """Close this run's row: the same rules as every other host (`runlog.finish_from` — an
        exception fails it, and so does a `fail` node the run recorded without raising), plus the
        references the run produced, so a DevUI row is as useful as a CLI one."""
        runlog.finish_from(run_id, error, client=client, **H.run_fields(output or {}))

    async def awaited(coro, run_id):
        try:
            out = await coro
        except BaseException as e:      # noqa: BLE001
            close(run_id, e)
            raise
        close(run_id, None, _result_output(out))
        return out

    def run(message=None, **kw):
        """Run the workflow under its own run-log entry (see devui_entry.instrument_runs)."""
        out = inner(message, **kw)
        run_id = f"{trace_id}-{next(seq)}"
        cfg["run_id"] = run_id
        runlog.start(run_id, input=_input_label(message), trace_id=trace_id, client=client,
                     mermaid=mermaid or "", host=SERVICE)
        return (_LoggedStream(out, lambda e, o: close(run_id, e, o)) if kw.get("stream")
                else awaited(out, run_id))

    wf.run = run


def build(root):
    """Build (never run) the workflow object DevUI will serve. Returns (workflow, trace_id)."""
    cfg, trace_id = build_cfg(root)
    wf = build_workflow(cfg)
    # every run of this session is its own row on the review app's Runs board
    instrument_runs(wf, cfg, trace_id, client=root.redis(), mermaid=workflowviz.mermaid(wf))
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
    print(f"runs board:     {root.config.review_app_url()}   (./lab.sh review -> Runs; every run below "
          f"appears there as `{trace_id}-<n>`)")
    print("NOTE: each run makes real gateway LLM + MCP calls and stages an ADOIT approval request.")

    from agent_framework.devui import serve
    serve(entities=[wf], port=a.port, host="127.0.0.1", auto_open=a.open, ui_enabled=not a.headless,
          instrumentation_enabled=False, auth_enabled=a.auth)


if __name__ == "__main__":
    main()
