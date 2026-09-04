"""src/lab/substrate/review/app.py page functions — Review / Submit / Runs — driven through a FAKE `streamlit`
module (a recording stub installed in sys.modules before the app is loaded, so the module-level
`@st.fragment` decorators are identity) and fake `lab.substrate.approvals / workflows / runlog /
artifacts` modules swapped into the app's namespace. Offline: no Redis, no gateway, no browser.
Asserts BEHAVIOUR: which decision is published, what Submit publishes for N files, the Runs board
row shape, the Mermaid highlight of the current node, artifact-unavailable degradation.
Run: .venv/bin/python tests/unit/substrate/review/test_app_pages.py   (also pytest-compatible)"""
import sys

from lab.substrate import artifacts as real_artifacts
from lab.substrate.review import traces

from fixtures.streamlit import (
    Rerun, FakeSt, APP, FakeStore, FakeApprovals, FakeWorkflows, FakeRunlog, install, XML, MERMAID, _request, _store_for, Upload, _run)


class FakeTraces:
    """The trace-store port (src/lab/substrate/review/traces.JaegerTraceReader): records the trace ids
    asked for and returns canned spans. Installed for the whole module so no test can reach Jaeger."""

    def __init__(self, spans=()):
        self.spans_, self.asked = list(spans), []

    def spans(self, trace_id):
        self.asked.append(trace_id)
        return list(self.spans_)


APP.TRACES = FakeTraces()


def _traces(spans=()):
    APP.TRACES = FakeTraces(spans)
    return APP.TRACES


# ============================================================================ Review mode
def test_review_page_no_pending_shows_history_and_acks_channel_events():
    ap = FakeApprovals(events=[("1-0", {"request_id": "apr-9"}), ("2-0", {"request_id": "apr-8"})],
                       history=[{"request_id": "apr-7", "decision": "approve", "actor": "ann", "channel": "cli",
                                 "comment": "", "decided_at": "t1"}])
    st = install(FakeSt(), approvals=ap)
    APP._review_page("ann")
    assert ap.acked == [("review-app", "1-0"), ("review-app", "2-0")]
    assert st.said("info", "No models awaiting review")
    assert st.said("write", "`apr-7` **approve** by ann via cli")
    assert ("sidebar.metric", ("Pending", 0), {}) in st.calls
    assert ap.decisions == []


def test_review_page_approve_publishes_decision_and_reruns():
    req = _request(comment="please rename", decided_by="bob", decided_via="telegram")
    ap = FakeApprovals(items=[req])
    st = install(FakeSt(**{"✅ Approve — release for import": True}), approvals=ap, store=_store_for(req))
    try:
        APP._review_page("ann")
        raise AssertionError("approve must st.rerun()")
    except Rerun:
        pass
    assert ap.decisions == [("apr-1", "approve", "ann", "review-app", "")]
    assert st.said("success", "Recorded: approve")
    # header + trace link + last comment + UPDATE resolution
    assert st.said("subheader", "Malaffi model")
    assert st.said("write", "0123456789abcdef…") and st.said("write", APP.JAEGER + req["trace_id"])
    assert st.said("warning", "Last comment (bob via telegram): please rename")
    assert st.said("warning", "**UPDATE** to **Malaffi** (domain: Health) — 2 existing element(s) reused, 1 new")
    assert st.said("caption", "names match the existing landscape")
    # metrics for the 5 summary keys
    metrics = [a for p, a, _ in st.calls if p.endswith("metric") and not p.startswith("sidebar")]
    assert metrics == [("elements", 3), ("relations", 1), ("views", 2), ("violations", 0), ("warnings", 1)]
    # model contents grouped by type, downloads for XML + Excel, one tab per view
    assert st.said("expander", "Model contents — 3 elements, 1 relationships")
    assert st.said("write", "**ApplicationComponent**: API, Portal") and st.said("write", "**Node**: Server")
    dl = [(a[0], k.get("file_name")) for p, a, k in st.calls if p.endswith("download_button")]
    assert dl == [("Download .archimate.xml (views/diagrams)", "model.archimate.xml"),
                  ("Download objects .xlsx (3 objects — create/update)", "objects.xlsx")]
    assert st.texts("tabs") == ["['Overview', 'Detail']"]
    imgs = [a[0] for p, a, k in st.calls if p.endswith("markdown") and k.get("unsafe_allow_html")]
    assert len(imgs) == 2 and all("data:image/svg+xml;base64," in i for i in imgs)


def test_review_page_decline_requires_a_comment():
    req = _request()
    ap = FakeApprovals(items=[req])
    st = install(FakeSt(**{"⛔ Decline": True}), approvals=ap, store=_store_for(req))
    APP._review_page("ann")                     # no rerun: the decision was refused
    assert ap.decisions == []
    assert st.said("error", "A comment is required for that decision.")


def test_review_page_decline_and_request_changes_with_comment():
    for label, decision in (("⛔ Decline", "decline"), ("✏️ Request changes", "update")):
        req = _request()
        ap = FakeApprovals(items=[req])
        st = install(FakeSt(**{label: True, "Comment (required for changes / decline)": "  fix names  "}),
                     approvals=ap, store=_store_for(req))
        try:
            APP._review_page("carol")
            raise AssertionError("a recorded decision must st.rerun()")
        except Rerun:
            pass
        assert ap.decisions == [("apr-1", decision, "carol", "review-app", "fix names")]
        assert st.said("success", f"Recorded: {decision}")


def test_review_page_selects_the_chosen_request_and_new_model_branch():
    a = _request(request_id="apr-a", subject="A")
    b = _request(request_id="apr-b", subject="B", trace_id="")
    b["payload"]["summary"] = {"decision": "NEW", "domain": "Finance", "elements": 4}
    ap = FakeApprovals(items=[a, b])
    st = install(FakeSt(Requests="B · apr-b"), approvals=ap, store=_store_for(b))
    APP._review_page("ann")
    assert st.said("radio", "Requests ['A · apr-a', 'B · apr-b']")
    assert st.said("success", "**NEW** model in domain **Finance** — 4 new element(s).")
    assert st.said("write", "`apr-b`") and not st.said("write", "**Trace**")
    assert not st.said("warning", "Last comment")
    metrics = [a for p, a, _ in st.calls if p.endswith("metric") and not p.startswith("sidebar")]
    assert metrics[0] == ("elements", 4) and metrics[1] == ("relations", "—")


def test_review_page_degrades_when_artifacts_are_missing():
    req = _request()
    req["payload"]["summary"].pop("decision")
    ap = FakeApprovals(items=[req])
    st = install(FakeSt(), approvals=ap, store=FakeStore())     # nothing in the store
    APP._review_page("ann")
    assert st.said("warning", "model artifact unavailable for this request")
    assert st.said("error", "model artifact not available: art://x1/model.archimate.xml")
    assert st.said("warning", "object Excel file not available")
    assert st.said("warning", "view Overview:") and st.said("warning", "view Detail:")
    assert st.count("tabs") == 0 and st.count("download_button") == 0
    assert not st.said("warning", "**UPDATE**") and not st.said("success", "**NEW**")


def test_xml_bytes_and_object_file_without_refs():
    st = install(FakeSt())
    assert APP._xml_bytes({}) == (None, None)
    APP._object_file({}, {})
    APP._views({})
    assert st.calls == []
    APP._model_contents({})
    assert st.said("error", "model artifact not available: None")


def test_submit_page_idle_lists_recent_submissions():
    wf = FakeWorkflows(recent=[{"request_id": "wfr-1", "status": "done", "requester": "ann", "created_at": "t",
                                "inputs": {"diagram": "art://1/sys.vsdx", "requirements": ["art://2/a.md"]},
                                "approval_id": "apr-1"},
                               {"request_id": "wfr-2", "status": "pending", "requester": "bob", "created_at": "t"}])
    st = install(FakeSt(), workflows=wf)
    APP._submit_page("ann")
    assert st.session_state["submit_refs"] == {"diagram": None, "requirements": []}
    assert st.said("write", "`wfr-1` **done** — sys.vsdx + 1 doc(s) (ann, t) → approval `apr-1`")
    assert st.said("write", "`wfr-2` **pending** —  + 0 doc(s) (bob, t)")
    assert wf.requests == [] and st.count("subheader") == 1      # no run status block


def test_submit_page_upload_stores_diagram_and_n_requirements_by_reference():
    ups = FakeStore()
    st = install(FakeSt(**{"⬆️ Upload": True, "up_diagram": Upload("sys.vsdx", b"V"),
                           "up_reqs": [Upload("a.docx", b"A"), Upload("b.md", b"B")]}), uploads=ups)
    st.session_state["submit_rid"] = "wfr-old"
    APP._submit_page("ann")
    assert [(n, d) for n, d, _ in ups.puts] == [("sys.vsdx", b"V"), ("a.docx", b"A"), ("b.md", b"B")]
    assert ups.puts[0][2] == real_artifacts.content_type_for("sys.vsdx")
    refs = st.session_state["submit_refs"]
    assert refs == {"diagram": "art://u1/sys.vsdx", "requirements": ["art://u2/a.docx", "art://u3/b.md"]}
    assert st.session_state["submit_rid"] is None
    assert st.said("success", "Stored.") and st.said("write", "**Diagram** `art://u1/sys.vsdx`")
    assert st.texts("write").count("**Requirements** `art://u2/a.docx`") == 1


def test_submit_page_upload_with_no_requirements():
    ups = FakeStore()
    st = install(FakeSt(**{"⬆️ Upload": True, "up_diagram": Upload("sys.png", b"P"), "up_reqs": None}), uploads=ups)
    APP._submit_page("ann")
    assert st.session_state["submit_refs"] == {"diagram": "art://u1/sys.png", "requirements": []}


def test_submit_page_run_publishes_one_request_with_the_refs():
    wf = FakeWorkflows()
    st = install(FakeSt(**{"▶️ Run visio_to_archimate": True}), workflows=wf)
    st.session_state["submit_refs"] = {"diagram": "art://d/sys.vsdx", "requirements": ["art://r/a.md"]}
    try:
        APP._submit_page("ann")
        raise AssertionError("Run must st.rerun()")
    except Rerun:
        pass
    assert wf.requests == [("visio_to_archimate", {"diagram": "art://d/sys.vsdx", "requirements": ["art://r/a.md"]}, "ann")]
    assert st.session_state["submit_rid"] == "wfr-1"


def test_submit_page_shows_run_status_for_every_state():
    statuses = {
        "p": {"status": "pending", "created_at": "c"},
        "r": {"status": "running", "started_at": "s", "consumer": "wf-visio-1", "trace_id": "ab" * 16},
        "d": {"status": "done", "approval_id": "apr-1", "xml_ref": "art://x/m.xml",
              "summary": {"elements": 5, "relations": 4, "views": 1, "semantic_warnings": 0}},
        "f": {"status": "failed", "error": "ValueError: bad diagram"},
        "z": {"status": "weird"},
        "d2": {"status": "done", "approval_id": "apr-2"},          # done, artifact ref not written back
    }
    for rid, expect in (("p", ("info", "Waiting for a workload host")), ("r", ("info", "in progress")),
                        ("d", ("success", "Model staged for approval `apr-1`")),
                        ("f", ("error", "ValueError: bad diagram")), ("z", None),
                        ("d2", ("success", "Model staged for approval `apr-2`"))):
        st = install(FakeSt(), workflows=FakeWorkflows(statuses=statuses))
        st.session_state["submit_rid"] = rid
        APP._submit_page("ann")
        if expect:
            assert st.said(*expect), (rid, st.calls)
        assert st.said("subheader", f"Run `{rid}` — {statuses[rid]['status']}")
    # details of the done + running renders
    st = install(FakeSt(), workflows=FakeWorkflows(statuses=statuses)); st.session_state["submit_rid"] = "d"
    APP._submit_page("ann")
    assert st.said("write", "Artifact `art://x/m.xml`")
    assert [a for p, a, _ in st.calls if p.endswith("metric")] == [("elements", 5), ("relations", 4), ("views", 1), ("semantic_warnings", 0)]
    st = install(FakeSt(), workflows=FakeWorkflows(statuses=statuses)); st.session_state["submit_rid"] = "d2"
    APP._submit_page("ann")
    assert not st.said("write", "Artifact `") and st.said("metric", "elements —")
    st = install(FakeSt(), workflows=FakeWorkflows(statuses=statuses)); st.session_state["submit_rid"] = "r"
    APP._submit_page("ann")
    assert st.said("write", "**Consumer** wf-visio-1") and st.said("write", f"{APP.JAEGER}{'ab' * 16}")
    # unknown request id
    st = install(FakeSt(), workflows=FakeWorkflows()); st.session_state["submit_rid"] = "nope"
    APP._submit_page("ann")
    assert st.said("warning", "unknown request nope")


def test_runs_board_empty():
    st = install(FakeSt())
    APP._runs_board()
    assert st.said("info", "No runs recorded yet") and st.count("dataframe") == 0


def test_runs_board_rows_selection_timeline_and_highlighted_graph():
    act = _run()
    rec = _run(run_id="run-0", status="done", node="render", elapsed=200, finished_at="2026-09-03T09:00:00+00:00",
               request_id="wfr-1", approval_id="apr-1", xml_ref="art://x/m.xml", trace_id="")
    rl = FakeRunlog(active=[act], recent=[rec], runs={"run-1": act, "run-0": rec})
    st = install(FakeSt(), runlog=rl); _traces()
    APP._runs_board()
    # the DETAIL is the primary view; the full list is one expander below it (the LAST dataframe)
    assert st.said("expander", "All runs — 1 active, 1 recent")
    board = [a[0] for p, a, _ in st.calls if p.endswith("dataframe")][-1]
    assert [r["run"] for r in board] == ["run-1", "run-0"]
    assert board[0] == {"run": "run-1", "process": "visio_to_archimate", "host": "", "input": "sys.vsdx",
                        "status": "running", "current node": "ba (start)", "started": "2026-09-03 10:00:00",
                        "elapsed": "42s", "trace": APP.JAEGER + "ff" * 16}
    assert board[1]["current node"] == "render" and board[1]["elapsed"] == "3.3m" and board[1]["trace"] is None
    assert st.said("selectbox", "Run ['run-1', 'run-0']") and st.session_state["runs_selected"] == "run-1"
    assert st.said("subheader", "`run-1` — running · at **ba**")
    assert st.said("write", "**Elapsed** 42s")
    timeline = [a[0] for p, a, _ in st.calls if p.endswith("dataframe")][0]
    assert [(t["node"], t["status"], t["at"], t["elapsed"], t["detail"]) for t in timeline] == [
        ("read_input", "start", "10:00:01", "—", ""), ("read_input", "done", "10:00:03", "2s", "shapes=12"),
        ("ba", "start", "10:00:03", "—", "")]
    graph = st.texts("code")[0]
    assert graph.startswith(MERMAID)
    assert f"style read_input {APP.NODE_STYLE['done']};" in graph and f"style ba {APP.NODE_STYLE['running']};" in graph
    assert "style store" not in graph
    assert st.count("iframe") == 1 and st.said("expander", "Mermaid source")


def test_runs_board_selected_run_details_and_fallbacks():
    rec = _run(run_id="run-0", status="failed", error="RuntimeError: boom", nodes=[], mermaid=None,
               request_id="wfr-1", approval_id="apr-1", xml_ref="art://x/m.xml", trace_id="")
    rl = FakeRunlog(recent=[rec], runs={"run-0": rec})
    st = install(FakeSt(), runlog=rl); _traces()
    st.session_state["runs_selected"] = "run-0"
    APP._runs_board()
    assert st.said("subheader", "`run-0` — failed") and not st.said("subheader", "· at")
    assert st.said("error", "RuntimeError: boom") and not st.said("write", "**Trace**")
    for k in ("request_id", "approval_id", "xml_ref"):
        assert st.said("write", f"**{k}** `{rec[k]}`")
    assert st.said("caption", "no node reported yet") and st.said("caption", "no graph stored on this run")
    # a stale default selection falls back to the first row; an expired hash warns
    rl = FakeRunlog(recent=[rec], runs={})
    st = install(FakeSt(), runlog=rl); _traces()
    st.session_state["runs_selected"] = "gone"
    APP._runs_board()
    assert st.said("warning", "run run-0 expired") and st.count("subheader") == 0
    assert st.said("expander", "All runs — 0 active, 1 recent")      # the list stays reachable


def test_render_mermaid_never_loses_the_board():
    st = install(FakeSt())
    st.raise_on["iframe"] = RuntimeError("no browser")
    APP._render_mermaid(MERMAID)
    assert st.said("caption", "diagram not rendered (no browser); source below") and st.texts("code") == [MERMAID]
    # a Streamlit without st.iframe falls back to components.html (deprecated but present) or the caption
    st = install(FakeSt())
    st.has_iframe = False
    APP._render_mermaid("flowchart TD\n  a --> b")
    assert st.count("iframe") == 0 and st.texts("code") == ["flowchart TD\n  a --> b"]


def test_runs_page_refresh_and_auto_toggle():
    _traces()
    st = install(FakeSt(**{"🔄 Refresh": True}))
    try:
        APP._runs_page("ann")
        raise AssertionError("Refresh must st.rerun()")
    except Rerun:
        pass
    for auto in (True, False):
        st = install(FakeSt(**{"Auto (5 s)": auto}))
        APP._runs_page("ann")
        assert st.said("title", "Runs") and st.said("info", "No runs recorded yet")


# ---------------------------------------------------------------------------- per-node trace detail
T0 = 1788495698.0


def _traced_run(**over):
    """A run whose node timeline carries the epoch `t` the run-log writes (what the trace is grouped on)."""
    h = _run(nodes=[{"name": "ba", "status": "start", "ts": "2026-09-03T10:00:01+00:00", "t": T0, "attrs": {}},
                    {"name": "ba", "status": "done", "ts": "2026-09-03T10:00:21+00:00", "t": T0 + 20,
                     "attrs": {"elapsed": 20.0}},
                    {"name": "store", "status": "start", "ts": "2026-09-03T10:00:22+00:00", "t": T0 + 21,
                     "attrs": {}}])
    h.update(over)
    return h


def _spans():
    return [traces.Span("litellm_request", "litellm-gateway", T0 + 1, 12.5,
                        {"gen_ai.request.model": "kimi-k3", "gen_ai.operation.name": "acompletion",
                         "gen_ai.usage.input_tokens": 1200, "gen_ai.usage.output_tokens": 800,
                         "gen_ai.cost.total_cost": 0.0021, "gen_ai.response.id": "resp-1"}),
            traces.Span("storage_read_vsdx", "storage-mcp", T0 + 2, 0.94,
                        {"mcp.tool": "storage_read_vsdx", "mcp.server": "storage-mcp", "storage.shapes": 12}),
            traces.Span("semantic_store_spec", "semantic-mcp", T0 + 22, 0.2,
                        {"mcp.tool": "semantic_store_spec", "mcp.server": "semantic-mcp"},
                        error="RuntimeError: store down")]


def test_runs_board_shows_per_node_llm_and_tool_calls_read_back_from_the_trace():
    h = _traced_run()
    st = install(FakeSt(), runlog=FakeRunlog(active=[h], runs={"run-1": h})); tr = _traces(_spans())
    APP._runs_board()
    assert tr.asked == ["ff" * 16]                                   # the run's own trace id
    assert st.said("markdown", "**Inside the run**")
    labels = [t for t in st.texts("expander") if " — " in t]
    assert labels[:2] == ["• ba — 1 LLM call(s) · 1 tool call(s) · 2,000 tokens · $0.0021",
                          "⛔ store — 0 LLM call(s) · 1 tool call(s)"]
    dfs = [a[0] for p, a, _ in st.calls if p.endswith("dataframe")]
    assert dfs[1] == [{"model": "kimi-k3", "operation": "acompletion", "seconds": 12.5, "in": 1200,
                       "out": 800, "cost": 0.0021, "response": "resp-1"}]
    assert dfs[2] == [{"server": "storage-mcp", "tool": "storage_read_vsdx", "seconds": 0.9, "detail": "shapes=12"}]
    assert dfs[3] == [{"server": "semantic-mcp", "tool": "semantic_store_spec", "seconds": 0.2, "detail": ""}]
    assert st.said("error", "semantic_store_spec: RuntimeError: store down")


def test_node_with_no_calls_says_so_and_a_missing_trace_leaves_an_empty_panel():
    h = _traced_run(nodes=[{"name": "ba", "status": "start", "ts": "2026-09-03T10:00:01+00:00", "t": T0, "attrs": {}}])
    st = install(FakeSt(), runlog=FakeRunlog(active=[h], runs={"run-1": h})); _traces()
    APP._runs_board()                                                # Jaeger unreachable / trace expired -> []
    assert st.said("caption", "no trace detail (no node has run yet, the trace expired")
    st = install(FakeSt(), runlog=FakeRunlog(active=[h], runs={"run-1": h}))
    _traces([traces.Span("quiet", "process-x", T0 + 1, 0.1, {})])    # a span that is neither LLM nor tool
    APP._runs_board()
    assert st.said("expander", "• ba — 0 LLM call(s) · 0 tool call(s)")
    assert st.said("caption", "no LLM or tool call in this step")


def test_trace_detail_is_reread_only_when_the_run_moved():
    """The board refreshes every 5 s; re-reading a finished run's whole trace each tick would be waste."""
    h = _traced_run(status="done", finished_at="2026-09-03T10:01:00+00:00")
    st = install(FakeSt(), runlog=FakeRunlog(recent=[h], runs={"run-1": h})); tr = _traces(_spans())
    APP._runs_board(); APP._runs_board()
    assert tr.asked == ["ff" * 16]                                   # same (trace, status, timeline) -> memo hit
    h["nodes"] = h["nodes"] + [{"name": "store", "status": "done", "ts": "2026-09-03T10:00:30+00:00",
                                "t": T0 + 30, "attrs": {"elapsed": 9.0}}]
    APP._runs_board()
    assert len(tr.asked) == 2                                        # the timeline grew: read it again


def test_activity_label_and_detail_text_are_pure_formatters():
    a = traces.NodeActivity("ba")
    assert APP._activity_label(a) == "• ba — 0 LLM call(s) · 0 tool call(s)"
    a.llm.append(traces.LlmCall("kimi-k3", "acompletion", 1.0, 10, 5, None))
    assert APP._activity_label(a) == "• ba — 1 LLM call(s) · 0 tool call(s) · 15 tokens"
    a.errors.append("boom")
    assert APP._activity_label(a).startswith("⛔ ba —")
    assert APP._detail_text({"archimate.elements": 42, "views": 2}) == "elements=42, views=2"
    assert APP._detail_text({}) == ""


def test_two_runs_of_one_devui_session_do_not_share_the_memoised_trace_detail():
    """A DevUI session injects ONE traceparent, so its runs share a trace id — the memo must key on
    the RUN, or selecting the second run shows the first one's calls."""
    a = _traced_run(run_id="s-1")
    # the SAME status and the SAME number of node entries — only the run id and the windows differ
    b = _traced_run(run_id="s-2", nodes=[dict(n, t=n["t"] + 100) for n in _traced_run()["nodes"]])
    rl = FakeRunlog(recent=[a, b], runs={"s-1": a, "s-2": b})
    st = install(FakeSt(), runlog=rl)
    _traces([traces.Span("litellm_request", "litellm-gateway", T0 + 1, 1.0, {"gen_ai.request.model": "m1"}),
             traces.Span("litellm_request", "litellm-gateway", T0 + 101, 1.0, {"gen_ai.request.model": "m2"})])
    APP._runs_board()                                        # both runs carry trace_id "ff"*16
    assert st.said("expander", "• ba — 1 LLM call(s)")
    st.session_state["runs_selected"] = "s-2"
    APP._runs_board()
    labels = [t for t in st.texts("expander") if "LLM call(s)" in t]
    assert labels[-2:] == ["• ba — 1 LLM call(s) · 0 tool call(s)", "• store — 0 LLM call(s) · 0 tool call(s)"]


def test_a_run_without_a_trace_says_so_rather_than_blaming_jaeger():
    h = _traced_run(trace_id="")
    st = install(FakeSt(), runlog=FakeRunlog(active=[h], runs={"run-1": h})); tr = _traces(_spans())
    APP._runs_board()
    assert st.said("caption", "this run recorded no trace (tracing was off)")
    assert tr.asked == [] and not st.said("caption", "Jaeger is unreachable")


def test_the_board_names_the_host_that_ran_each_run():
    """Three hosts write runs (CLI, the wf-visio consumer, DevUI) — the reviewer must be able to tell."""
    h = _run(host="process-visio-to-archimate-devui")
    st = install(FakeSt(), runlog=FakeRunlog(active=[h], runs={"run-1": h})); _traces()
    APP._runs_board()
    board = [a[0] for p, a, _ in st.calls if p.endswith("dataframe")][-1]
    assert board[0]["host"] == "process-visio-to-archimate-devui"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")


# ------------------------------------------------------------------ the review app is a HUMAN channel
def test_review_app_records_through_human_decision_with_a_named_reviewer(monkeypatch):
    """Every human channel decides on the SAME terms (lab.substrate.approvals.human_decision): an
    identified actor, a legal decision, one final answer. The review app used to call the raw
    recorder with a free-text reviewer that could be blank — an ANONYMOUS approval releasing an EA
    repository write, a weaker guarantee than Teams, Telegram and the approvals_decide tool."""
    import inspect
    from lab.substrate.review import app as A
    src = inspect.getsource(A._review_page)
    assert "approvals.human_decision(" in src, "the review app must use the one human-gate path"
    assert "approvals.decide(" not in src, "the raw recorder must not be called from a channel"


def test_a_blank_reviewer_cannot_release_a_write(monkeypatch):
    """A blank actor is refused by human_decision; the app must surface that, not crash."""
    from lab.substrate import approvals
    import pytest as _pytest
    with _pytest.raises(ValueError, match="actor is required"):
        approvals.human_decision("apr-x", "approve", "   ", "review-app", "")
