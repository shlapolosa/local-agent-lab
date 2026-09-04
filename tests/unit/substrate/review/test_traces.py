"""src/lab/substrate/review/traces.py — reading a run's trace back out of Jaeger's QUERY API and
grouping its spans onto the workflow's nodes.

Offline by construction: the reader takes an injected fetcher, so no Jaeger is contacted. The
payload below is shaped from a REAL local Jaeger response (`GET /api/traces/<id>` — `data[0].spans[]`
with operationName/startTime/duration/tags/processID/references and `processes[pid].serviceName`),
with the gateway's real `gen_ai.*` tag set and the lab MCP servers' `mcp.tool`/`mcp.server` + domain
attributes.
Run: .venv/bin/python tests/unit/substrate/review/test_traces.py   (also pytest-compatible)"""
import json
import math

from lab.substrate.review import traces as T

T0 = 1788495698.0          # epoch seconds; the run-log timeline and the spans share this clock


def _span(name, pid, start, dur, tags=None, logs=None, parent=None):
    s = {"operationName": name, "processID": pid, "spanID": name[:8],
         "startTime": int(start * 1e6), "duration": int(dur * 1e6),
         "tags": [{"key": k, "value": v} for k, v in (tags or {}).items()]}
    if logs:
        s["logs"] = logs
    if parent:
        s["references"] = [{"refType": "CHILD_OF", "spanID": parent}]
    return s


GEN_AI = {"gen_ai.request.model": "kimi-k3", "gen_ai.operation.name": "acompletion",
          "gen_ai.response.id": "chatcmpl-515", "gen_ai.usage.input_tokens": 15,
          "gen_ai.usage.output_tokens": 16, "gen_ai.usage.total_tokens": 31,
          "gen_ai.cost.total_cost": 1.185e-05, "otel.scope.name": "litellm", "span.kind": "client"}

EXCEPTION_LOG = [{"timestamp": 1, "fields": [
    {"key": "event", "value": "exception"},
    {"key": "exception.type", "value": "RuntimeError"},
    {"key": "exception.message", "value": "adoit unreachable"}]}]

# one run: root -> [ba-agent | architect-design], with gateway LLM spans and MCP tool spans that hang
# off the ROOT (the workload injects ONE traceparent per run), which is exactly why grouping is by time.
TRACE = {"data": [{
    "traceID": "ab" * 16,
    "processes": {"p1": {"serviceName": "process-visio-to-archimate"},
                  "p2": {"serviceName": "litellm-gateway"},
                  "p3": {"serviceName": "storage-mcp"},
                  "p4": {"serviceName": "adoit-mcp"}},
    "spans": [
        _span("visio-to-archimate-run", "p1", T0, 60),
        _span("boot", "p2", T0 - 5, 1),                                        # before any node: ignored
        _span("ba-agent", "p1", T0 + 1, 20, parent="visio-to"),
        _span("litellm_request", "p2", T0 + 2, 12.5, GEN_AI),
        _span("raw_gen_ai_request", "p2", T0 + 2, 12.5, {"llm.openai.id": "x"}),  # no gen_ai.*: not a call
        _span("storage_read_vsdx", "p3", T0 + 15, 0.9,
              {"mcp.tool": "storage_read_vsdx", "mcp.server": "storage-mcp", "storage.shapes": 12}),
        _span("architect-design", "p1", T0 + 22, 30, parent="visio-to"),
        _span("litellm_request", "p2", T0 + 23, 25,
              {**GEN_AI, "gen_ai.request.model": "kimi-k3", "gen_ai.usage.input_tokens": 4000,
               "gen_ai.usage.output_tokens": 900, "gen_ai.cost.total_cost": 0.002}),
        _span("adoit_search", "p4", T0 + 24, 2.0,
              {"mcp.tool": "adoit_search", "mcp.server": "adoit-mcp", "adoit.hits": 7,
               "otel.status_code": "ERROR"}, logs=EXCEPTION_LOG),
        _span("archimate_render", "p4", T0 + 90, 1.0,                          # after the last node: ignored
              {"mcp.tool": "archimate_render", "mcp.server": "adoit-mcp"}),
    ]}]}

NODES = [{"name": "ba", "status": "start", "t": T0 + 1, "ts": "", "attrs": {}},
         {"name": "ba", "status": "done", "t": T0 + 21, "ts": "", "attrs": {"elapsed": 20.0}},
         {"name": "architect_design", "status": "start", "t": T0 + 22, "ts": "", "attrs": {}}]


class Fetcher:
    """Records URLs; returns the queued body (bytes) or raises the queued exception."""

    def __init__(self, body=None, error=None):
        self.body, self.error, self.urls = body, error, []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.body


def _reader(body=None, error=None):
    f = Fetcher(body, error)
    return T.JaegerTraceReader("http://jaeger.test/", fetch=f), f


# ============================================================================ parsing
def test_parse_spans_normalises_service_time_and_tags():
    spans = T.parse_spans(TRACE)
    assert [s.name for s in spans][:3] == ["boot", "visio-to-archimate-run", "ba-agent"]   # sorted by start
    ba = next(s for s in spans if s.name == "ba-agent")
    assert ba.service == "process-visio-to-archimate" and ba.start == T0 + 1 and ba.seconds == 20.0
    llm = next(s for s in spans if s.name == "litellm_request")
    assert llm.service == "litellm-gateway" and llm.tags["gen_ai.request.model"] == "kimi-k3"
    assert llm.error is None


def test_parse_spans_empty_payloads():
    assert T.parse_spans(None) == [] and T.parse_spans({}) == [] and T.parse_spans({"data": []}) == []


def test_parse_spans_reads_the_error_off_status_exception_log_and_error_tags():
    err = next(s for s in T.parse_spans(TRACE) if s.name == "adoit_search")
    assert err.error == "RuntimeError: adoit unreachable"
    # status ERROR without an exception log falls back to the description, then to a bare marker
    payload = {"data": [{"processes": {}, "spans": [
        _span("a", "p", T0, 1, {"otel.status_code": "ERROR", "otel.status_description": "boom"}),
        _span("b", "p", T0, 1, {"otel.status_code": "ERROR"},                  # a log, but not an exception
              logs=[{"fields": [{"key": "event", "value": "retry"}]}, {}]),
        _span("c", "p", T0, 1, {"error.type": "TimeoutError", "error.message": "no answer"}),
        _span("d", "p", T0, 1, {"error": True}),
        _span("e", "p", T0, 1, {"otel.status_code": "OK"})]}]}
    by = {s.name: s.error for s in T.parse_spans(payload)}
    assert by == {"a": "boom", "b": "error", "c": "TimeoutError: no answer", "d": "error", "e": None}


# ============================================================================ node windows
def test_node_windows_pairs_start_with_done_and_leaves_a_running_node_open():
    w = T.node_windows(NODES)
    assert w == [("ba", T0 + 1, T0 + 21), ("architect_design", T0 + 22, math.inf)]
    assert T.node_windows([]) == [] and T.node_windows(None) == []


def test_node_windows_handles_a_retried_node_and_a_close_without_a_start():
    nodes = [{"name": "ba", "status": "start", "t": 10}, {"name": "ba", "status": "fail", "t": 12},
             {"name": "ba", "status": "start", "t": 13}, {"name": "ba", "status": "done", "t": 20},
             {"name": "ghost", "status": "done", "t": 21}]
    assert T.node_windows(nodes) == [("ba", 10, 12), ("ba", 13, 20), ("ghost", 21, 21)]


# ============================================================================ grouping
def test_activity_groups_llm_tool_and_error_spans_onto_the_node_that_was_running():
    acts = T.activity(T.parse_spans(TRACE), NODES)
    assert [a.node for a in acts] == ["ba", "architect_design"]

    ba = acts[0]
    assert [(c.model, c.seconds, c.input_tokens, c.output_tokens, c.cost, c.response_id) for c in ba.llm] == [
        ("kimi-k3", 12.5, 15, 16, 1.185e-05, "chatcmpl-515")]
    assert ba.llm[0].operation == "acompletion" and ba.llm[0].error is None
    assert [(t.server, t.tool, t.seconds) for t in ba.tools] == [("storage-mcp", "storage_read_vsdx", 0.9)]
    assert ba.tools[0].detail == {"storage.shapes": 12} and ba.errors == []
    assert ba.total_tokens == 31 and ba.total_cost == 1.185e-05

    ar = acts[1]
    assert ar.total_tokens == 4900 and ar.total_cost == 0.002
    assert [(t.server, t.tool, t.error) for t in ar.tools] == [
        ("adoit-mcp", "adoit_search", "RuntimeError: adoit unreachable"),
        ("adoit-mcp", "archimate_render", None)]           # the node is still running: later spans are its
    assert ar.tools[0].detail == {"adoit.hits": 7}
    assert ar.errors == ["adoit_search: RuntimeError: adoit unreachable"]


def test_activity_ignores_spans_outside_every_node_window_and_needs_no_trace():
    acts = T.activity(T.parse_spans(TRACE), NODES)
    tools = [t.tool for a in acts for t in a.tools]
    assert "boot" not in tools                                  # before the first node started: dropped
    # architect_design is still RUNNING (no done entry), so a late span still belongs to it
    assert tools == ["storage_read_vsdx", "adoit_search", "archimate_render"]
    assert T.activity([], NODES) == []                          # no spans -> no panel at all
    assert T.activity(T.parse_spans(TRACE), []) == []           # no node timeline -> nothing to group onto


def test_activity_keeps_a_node_with_no_calls_out_of_the_way_but_reports_a_bare_error_span():
    nodes = [{"name": "store", "status": "start", "t": T0}, {"name": "store", "status": "done", "t": T0 + 5}]
    payload = {"data": [{"processes": {"p": {"serviceName": "process-x"}}, "spans": [
        _span("store-spec", "p", T0 + 1, 1, {"otel.status_code": "ERROR", "otel.status_description": "no store"}),
        _span("quiet", "p", T0 + 2, 1)]}]}
    acts = T.activity(T.parse_spans(payload), nodes)
    assert len(acts) == 1 and acts[0].node == "store" and acts[0].llm == [] and acts[0].tools == []
    assert acts[0].errors == ["store-spec: no store"]
    assert acts[0].total_tokens == 0 and acts[0].total_cost == 0.0


def test_activity_assigns_a_span_to_the_innermost_window_when_nodes_overlap():
    nodes = [{"name": "outer", "status": "start", "t": 0}, {"name": "inner", "status": "start", "t": 5},
             {"name": "inner", "status": "done", "t": 9}, {"name": "outer", "status": "done", "t": 10}]
    payload = {"data": [{"processes": {"p": {"serviceName": "s"}}, "spans": [
        _span("t1", "p", 6, 1, {"mcp.tool": "x", "mcp.server": "s"})]}]}
    acts = {a.node: a for a in T.activity(T.parse_spans(payload), nodes)}
    assert [t.tool for t in acts["inner"].tools] == ["x"] and acts["outer"].tools == []


# ============================================================================ the Jaeger adapter
def test_reader_fetches_the_query_api_and_returns_parsed_spans():
    reader, f = _reader(json.dumps(TRACE).encode())
    spans = reader.spans("ab" * 16)
    assert f.urls == ["http://jaeger.test/api/traces/" + "ab" * 16]
    assert len(spans) == 10 and any(s.service == "litellm-gateway" for s in spans)


def test_reader_returns_no_spans_when_jaeger_is_unreachable_or_the_trace_is_gone():
    reader, _ = _reader(error=OSError("connection refused"))
    assert reader.spans("ab" * 16) == []                        # never raises: the board must survive
    reader, _ = _reader(json.dumps({"data": []}).encode())       # span retention expired
    assert reader.spans("ab" * 16) == []
    reader, _ = _reader(b"<html>not json</html>")
    assert reader.spans("ab" * 16) == []
    reader, f = _reader(json.dumps(TRACE).encode())
    assert reader.spans("") == [] and f.urls == []               # no trace id -> no request at all


def test_http_fetch_is_a_thin_urllib_adapter():
    """The default fetcher is injected, so this only pins the seam's shape (no network in tests)."""
    calls = {}

    class Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    def urlopen(url, timeout=None):
        calls.update(url=url, timeout=timeout)
        return Resp()

    assert T.http_fetch("http://j/api/traces/x", opener=urlopen) == b"{}"
    assert calls == {"url": "http://j/api/traces/x", "timeout": T.TIMEOUT_S}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
