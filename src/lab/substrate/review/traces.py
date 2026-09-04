"""Per-node event detail for a run — read back from the trace, so the review app shows what
happened INSIDE a run (LLM calls, governed tool calls, errors) without leaving the approval UI.

Why here: the importer rule (CLAUDE.md "Repository Layout & Tiers") puts a module in the tier that
imports it, and today that is only the review app (`app.py`'s Runs board). It is deliberately a
PORT + adapter so the move to Azure is a swap, not a rewrite: `activity()` / `parse_spans()` /
`node_windows()` are pure functions over already-fetched data, and `JaegerTraceReader` is the one
thing that talks to a backend — give it an Application-Insights fetcher (or any `fetch(url) ->
bytes`) and nothing else changes. The reader NEVER raises: a dead Jaeger, an expired trace or a
non-JSON body is an empty panel, never a broken board.

Jaeger's query API (verified live): `GET {JAEGER_UI_URL}/api/traces/<trace_id>` ->
`{"data": [{"spans": [{operationName, startTime (epoch µs), duration (µs), tags: [{key,value}],
processID, references}], "processes": {"<pid>": {"serviceName": ...}}}]}`.

GROUPING IS BY TIME, not by parent span — on purpose. A workload injects ONE W3C traceparent per
run (built from the run's ROOT span) into every agent's `default_headers` and every MCP client, so
the gateway's `litellm_request` spans and the MCP servers' tool spans are children of the ROOT, not
of the node span that was executing. Their parent therefore says nothing about which node made
them. What does is time: the run-log (`lab.platform.runlog`) records every node's start/done with
an epoch `t`, the workflow is a sequential graph, and a span belongs to the node whose window
contains its start. That also scopes a DevUI SESSION trace (one trace, many runs) to the one run
being viewed, for free. The one caveat: the node windows carry the WORKLOAD host's clock while the
spans carry the gateway's and each MCP server's (separate containers on Railway, separate Container
Apps on Azure). Normal NTP skew is irrelevant against nodes that last tens of seconds; a call landing
within ~a second of a node boundary can be attributed to the neighbouring node. There is no better
signal available — the trace carries no node identity — so this is documented, not compensated for.

On Azure the same reader works with an authenticated fetcher (the `fetch` seam) against whatever
serves the traces; only `parse_spans` + `API_PATH` are Jaeger-shaped.
"""
import json
import math
import urllib.request
from dataclasses import dataclass, field

TIMEOUT_S = 4.0                     # a slow trace query must not stall the 5 s live board
API_PATH = "/api/traces/"

# What makes a span an LLM call / a governed tool call. OpenTelemetry gen_ai.* (the gateway emits
# the full set) and the lab MCP servers' mcp.tool/mcp.server (lab.substrate.mcpserver.LabServer).
MODEL_TAG = "gen_ai.request.model"
TOOL_TAG, SERVER_TAG = "mcp.tool", "mcp.server"
# Domain attributes a tool span may carry, shown next to the call. One tuple = adding a new server's
# namespace is a one-line change (CLAUDE.md: open for extension).
DOMAIN_PREFIXES = ("archimate.", "semantic.", "storage.", "adoit.", "visio.")


@dataclass(frozen=True)
class Span:
    """One trace span, normalised: seconds instead of microseconds, tags as a dict, error as text."""
    name: str
    service: str
    start: float                    # epoch seconds
    seconds: float
    tags: dict
    error: str | None = None


@dataclass(frozen=True)
class LlmCall:
    model: str
    operation: str
    seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    response_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ToolCall:
    server: str
    tool: str
    seconds: float
    detail: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class NodeActivity:
    """What one workflow node did, as the trace saw it. Deliberately NOT frozen: `activity()` fills
    the three lists as it walks the spans."""
    node: str
    llm: list[LlmCall] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum((c.input_tokens or 0) + (c.output_tokens or 0) for c in self.llm)

    @property
    def total_cost(self) -> float:
        return sum(c.cost or 0.0 for c in self.llm)


# ------------------------------------------------------------------------------ parsing (pure)
def _tags(span: dict) -> dict:
    return {t.get("key"): t.get("value") for t in span.get("tags") or []}


def _exception_text(span: dict) -> str | None:
    """The exception an OTel SDK records as a span EVENT (Jaeger: `logs[].fields[]`)."""
    for log in span.get("logs") or []:
        f = {x.get("key"): x.get("value") for x in log.get("fields") or []}
        if f.get("event") == "exception":
            return f"{f.get('exception.type', 'error')}: {f.get('exception.message', '')}".strip(": ")
    return None


def _error(span: dict, tags: dict) -> str | None:
    failed = (str(tags.get("otel.status_code", "")).upper() == "ERROR" or tags.get("error") is True
              or bool(tags.get("error.type") or tags.get("error.message")))
    if not failed:
        return None
    if tags.get("error.type") or tags.get("error.message"):
        return ": ".join(str(x) for x in (tags.get("error.type"), tags.get("error.message")) if x)
    return _exception_text(span) or str(tags.get("otel.status_description") or "error")


def parse_spans(payload) -> list[Span]:
    """Jaeger's trace JSON -> spans sorted by start time. Any empty/absent trace -> []."""
    data = (payload or {}).get("data") or []
    if not data:
        return []
    trace = data[0] or {}
    services = {pid: (p or {}).get("serviceName", "") for pid, p in (trace.get("processes") or {}).items()}
    spans = []
    for s in trace.get("spans") or []:
        tags = _tags(s)
        spans.append(Span(name=s.get("operationName", ""), service=services.get(s.get("processID"), ""),
                          start=(s.get("startTime") or 0) / 1e6, seconds=(s.get("duration") or 0) / 1e6,
                          tags=tags, error=_error(s, tags)))
    return sorted(spans, key=lambda s: s.start)


# ------------------------------------------------------------------------------ grouping (pure)
def node_windows(nodes) -> list[tuple]:
    """[(node, start, end)] from the run-log's node timeline, in the order the nodes ran. A node
    that has started but not finished stays OPEN (`inf`) — spans still arriving belong to it."""
    out, open_at = [], {}
    for n in nodes or []:
        name, status, t = n.get("name", ""), n.get("status"), float(n.get("t") or 0)
        if status == "start":
            open_at[name] = len(out)
            out.append([name, t, math.inf])
        else:
            i = open_at.pop(name, None)
            if i is None:                       # a close with no start (a truncated timeline)
                out.append([name, t, t])
            else:
                out[i][2] = t
    return [tuple(w) for w in out]


def _window_of(windows, t: float):
    """The INNERMOST (latest-starting) window containing `t`; None if the span is outside the run."""
    hit = None
    for i, (_, start, end) in enumerate(windows):
        if start <= t <= end and (hit is None or start >= windows[hit][1]):
            hit = i
    return hit


def _llm_call(s: Span) -> LlmCall:
    t = s.tags
    return LlmCall(model=str(t.get(MODEL_TAG)), operation=str(t.get("gen_ai.operation.name", "")),
                   seconds=s.seconds, input_tokens=t.get("gen_ai.usage.input_tokens"),
                   output_tokens=t.get("gen_ai.usage.output_tokens"),
                   cost=t.get("gen_ai.cost.total_cost"), response_id=t.get("gen_ai.response.id"),
                   error=s.error)


def _tool_call(s: Span) -> ToolCall:
    detail = {k: v for k, v in s.tags.items() if k.startswith(DOMAIN_PREFIXES)}
    return ToolCall(server=str(s.tags.get(SERVER_TAG, s.service)), tool=str(s.tags.get(TOOL_TAG)),
                    seconds=s.seconds, detail=detail, error=s.error)


def activity(spans, nodes) -> list[NodeActivity]:
    """Group `spans` onto the workflow nodes of `nodes` (the run-log timeline). Spans outside every
    node window are dropped — they belong to another run of the same (DevUI session) trace, or to
    the host's own setup. No spans or no timeline -> no panel."""
    windows = node_windows(nodes)
    if not spans or not windows:
        return []
    acts = [NodeActivity(node=w[0]) for w in windows]
    for s in spans:
        i = _window_of(windows, s.start)
        if i is None:
            continue
        a = acts[i]
        if MODEL_TAG in s.tags:
            a.llm.append(_llm_call(s))
        elif TOOL_TAG in s.tags:
            a.tools.append(_tool_call(s))
        if s.error:
            a.errors.append(f"{s.name}: {s.error}")
    return acts


# ------------------------------------------------------------------------------ the Jaeger adapter
def http_fetch(url: str, *, opener=urllib.request.urlopen) -> bytes:
    """The default fetcher: one GET, `TIMEOUT_S` budget. `opener` is a seam (tests, an authenticated
    opener on Azure)."""
    with opener(url, timeout=TIMEOUT_S) as r:
        return r.read()


class JaegerTraceReader:
    """The trace-store port as the review app needs it: `spans(trace_id)`. `fetch(url) -> bytes` is
    injected (no client is constructed here, no env is read — the base URL comes from the
    container's config)."""

    def __init__(self, base_url: str, fetch=http_fetch):
        self._base, self._fetch = (base_url or "").rstrip("/"), fetch

    def spans(self, trace_id: str) -> list[Span]:
        """Every span of `trace_id`, or [] — Jaeger down, trace expired, body not JSON."""
        if not trace_id:
            return []
        try:
            return parse_spans(json.loads(self._fetch(self._base + API_PATH + trace_id)))
        except Exception:       # noqa: BLE001 — an observability read must never break the board
            return []
