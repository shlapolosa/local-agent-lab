"""Architecture Review — the human channel for the lab's business processes.

Three modes (sidebar), one function each, dispatched by the PAGES table in main():
  Review  — the approval gate for EA repository writes: reads approval requests from Redis Streams
            (consumer group "review-app"), renders the model's views + summary, records approve /
            request changes / decline; the decision flows back on approvals:decisions.
  Submit  — start a run: upload a system diagram (.vsdx or image) plus requirements documents;
            they are stored in the UPLOAD store (a bucket in the cloud) as art:// refs and an
            explicit Run publishes a durable workflow:requests event that the long-lived workload
            host consumes (src/lab/platform/workflows.py). The run's trace, approval and outputs are shown
            here as the consumer writes them back. Only refs cross into the workload — it reads
            them through the gateway's storage-mcp tools, never with store credentials.
  Runs    — live run visibility for EVERY run, whoever started it (CLI, the wf-visio consumer, or
            DevUI): each workflow host reports its current node through src/lab/platform/runlog.py
            (Redis hash per run + unbuffered stdout lines), so no run is a black box. ONE run is the
            primary view — node timeline, the workflow graph (Mermaid, exported by
            src/lab/workloads/workflowviz.py) with the current node highlighted, and the per-node
            LLM/tool/error detail read back from the run's trace (review/traces.py) — with the full
            run list one expander below. That is the DevUI live view, for runs you did not trigger.

Run: ./lab.sh review   (streamlit, http://127.0.0.1:8501)
Streamlit executes this file as __main__; importing it (tests) only defines the helpers. Stores come
from the substrate container built once at import (`container.artifacts()` for renders,
`container.uploads()` for submitted inputs) — tests override its providers.
"""
import base64
import os
import re
import xml.etree.ElementTree as ET
from html import escape

import streamlit as st

from lab.platform import config, contracts, runlog, workflows
from lab.platform.filetypes import content_type_for
from lab.substrate import approvals
from lab.substrate.container import build
from lab.substrate.review import traces

container = build("review-app")
JAEGER_UI = container.config.jaeger_ui_url().rstrip("/")   # one source for both the link and the reader
JAEGER = JAEGER_UI + "/trace/"
TRACES = traces.JaegerTraceReader(JAEGER_UI)               # trace-store port; tests swap it wholesale
NS = {"a": "http://www.opengroup.org/xsd/archimate/3.0/"}
DIAGRAM_TYPES = ["vsdx", "png", "jpg", "jpeg", "gif", "webp"]
REQUIREMENT_TYPES = ["docx", "pdf", "md", "txt", "csv"]


# ============================================================================ Submit mode
def _submit_page(reviewer):
    st.title("Submit a diagram for conversion")
    st.caption("Upload a system diagram and its requirements. Files are stored by reference; the "
               "workflow reads them through the governed gateway. Nothing runs until you press Run.")
    refs = st.session_state.setdefault("submit_refs", {"diagram": None, "requirements": []})

    c1, c2 = st.columns(2)
    diagram = c1.file_uploader("System diagram (.vsdx or image)", type=DIAGRAM_TYPES, key="up_diagram")
    reqs = c2.file_uploader("Requirements documents", type=REQUIREMENT_TYPES,
                            accept_multiple_files=True, key="up_reqs")
    if st.button("⬆️ Upload", disabled=not diagram) and diagram is not None:
        store = container.uploads()
        # keep the original filename: the workflow decides vsdx/image/document from its suffix
        refs["diagram"] = store.put(diagram.name, diagram.getvalue(), content_type_for(diagram.name))
        refs["requirements"] = [store.put(f.name, f.getvalue(), content_type_for(f.name))
                                for f in (reqs or [])]
        st.session_state["submit_rid"] = None
        st.success("Stored. Review the references below, then press Run.")

    if refs["diagram"]:
        st.write("**Diagram**", f'`{refs["diagram"]}`')
        for r in refs["requirements"]:
            st.write("**Requirements**", f"`{r}`")
        if st.button("▶️ Run visio_to_archimate", type="primary"):
            try:    # the process's OWN contract validates every producer (lab.platform.contracts)
                rid = workflows.request("visio_to_archimate",
                                        {"diagram": refs["diagram"], "requirements": refs["requirements"]},
                                        requester=reviewer)
            except ValueError as e:
                st.error(f"rejected: {e}")
            else:
                st.session_state["submit_rid"] = rid
                st.rerun()

    rid = st.session_state.get("submit_rid")
    if rid:
        _run_status(rid)

    st.divider()
    st.subheader("Recent submissions")
    for s in workflows.recent(10):
        inp = s.get("inputs") or {}
        line = (f'`{s.get("request_id")}` **{s.get("status", "?")}** — {os.path.basename(inp.get("diagram", "") or "")} '
                f'+ {len(inp.get("requirements") or [])} doc(s) ({s.get("requester")}, {s.get("created_at")})')
        if s.get("approval_id"):
            line += f' → approval `{s["approval_id"]}`'
        st.write(line)


@st.fragment(run_every=5)
def _run_status(rid):
    s = workflows.status(rid)
    if not s:
        st.warning(f"unknown request {rid}"); return
    status = s.get("status", "pending")
    icon = {"pending": "⏳", "running": "🏃", "done": "✅", "failed": "⛔"}.get(status, "•")
    st.subheader(f"{icon} Run `{rid}` — {status}")
    cols = st.columns(4)
    cols[0].write(f'**Requested** {s.get("created_at", "")}')
    cols[1].write(f'**Started** {s.get("started_at", "—")}')
    cols[2].write(f'**Finished** {s.get("finished_at", "—")}')
    cols[3].write(f'**Consumer** {s.get("consumer", "—")}')
    if s.get("trace_id"):
        st.write(f'**Trace** [{s["trace_id"][:16]}…]({JAEGER}{s["trace_id"]})')
    if status == "pending":
        st.info("Waiting for a workload host to pick this up (the wf-visio consumer).")
    elif status == "running":
        st.info("BA → Architect → validate/render in progress…")
    elif status == "done":
        summ = s.get("summary") or {}
        m = st.columns(4)
        for col, k in zip(m, ("elements", "relations", "views", "semantic_warnings")):
            col.metric(k, summ.get(k, "—"))
        st.success(f'Model staged for approval `{s.get("approval_id")}` — switch to **Review** mode to decide.')
        if s.get("xml_ref"):
            st.write(f'Artifact `{s["xml_ref"]}`')
    elif status == "failed":
        st.error(s.get("error", "failed"))


# ============================================================================ Runs mode
STATUS_ICON = {"running": "🏃", "done": "✅", "failed": "⛔", "start": "▶️", "fail": "⛔"}
NODE_STYLE = {"done": "fill:#d4edda,stroke:#28a745", "running": "fill:#fff3cd,stroke:#ffc107,stroke-width:3px",
              "failed": "fill:#f8d7da,stroke:#dc3545,stroke-width:3px"}


def _fmt_elapsed(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return "—"
    return f"{s:.0f}s" if s < 90 else f"{s / 60:.1f}m"


def _run_row(h):
    node = h.get("node") or ""
    if h.get("status") == "running" and node:
        node = f"{node} ({h.get('node_status', '')})"
    return {"run": h.get("run_id", ""), "process": h.get("process", ""),
            "host": h.get("host", ""), "input": os.path.basename(h.get("input", "") or ""),
            "status": h.get("status", ""),
            "current node": node, "started": (h.get("started_at") or "")[:19].replace("T", " "),
            "elapsed": _fmt_elapsed(h.get("elapsed")),
            "trace": (JAEGER + h["trace_id"]) if h.get("trace_id") else None}


def _node_states(h):
    """name -> done | running | failed, from the ordered node timeline."""
    states = {}
    for n in h.get("nodes") or []:
        states[n["name"]] = {"start": "running", "done": "done", "fail": "failed"}[n["status"]]
    return states


def _mermaid_with_state(src, states):
    lines = [src.rstrip()]
    for name, state in states.items():
        if state in NODE_STYLE and re.search(rf"^\s*{re.escape(name)}\[", src, re.M):
            lines.append(f"  style {name} {NODE_STYLE[state]};")
    return "\n".join(lines)


def _render_mermaid(src):
    """Render in an iframe with mermaid.js (Streamlit's markdown has no mermaid); source below."""
    try:
        html = ('<script type="module">import mermaid from '
                '"https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";'
                'mermaid.initialize({startOnLoad:true,theme:"neutral"});</script>'
                f'<pre class="mermaid" style="margin:0">{escape(src)}</pre>')   # mermaid entity-decodes
        height = min(80 + 90 * (src.count("-->") + 1), 720)
        if hasattr(st, "iframe"):                # Streamlit >= 1.6x; components.v1.html is deprecated
            st.iframe(html, height=height)
        else:
            import streamlit.components.v1 as components
            components.html(html, height=height, scrolling=True)
    except Exception as e:                       # noqa: BLE001 — never lose the board over a diagram
        st.caption(f"diagram not rendered ({e}); source below")
    with st.expander("Mermaid source"):
        st.code(src, language="mermaid")


def _trace_activity(h):
    """Per-node LLM / tool / error detail for this run, from its trace. Memoised on (run, trace,
    status, timeline length) so the 5 s live fragment re-reads Jaeger only when the run actually
    moved — and never for a finished one. The RUN id is part of the key because a trace id is not
    unique: every run of one DevUI session shares its session trace. Jaeger down or trace expired =
    an empty panel (never an error)."""
    key = (h.get("run_id"), h.get("trace_id"), h.get("status"), len(h.get("nodes") or []))
    hit = st.session_state.get("trace_detail")
    if not hit or hit[0] != key:
        hit = (key, traces.activity(TRACES.spans(h.get("trace_id") or ""), h.get("nodes") or []))
        st.session_state["trace_detail"] = hit
    return hit[1]


def _activity_label(a):
    """One node's headline: what it called, how much it cost."""
    parts = [f"{len(a.llm)} LLM call(s)", f"{len(a.tools)} tool call(s)"]
    if a.total_tokens:
        parts.append(f"{a.total_tokens:,} tokens")
    if a.total_cost:
        parts.append(f"${a.total_cost:.4f}")
    return f'{"⛔" if a.errors else "•"} {a.node} — ' + " · ".join(parts)


def _detail_text(detail):
    """Domain attributes of a tool span (`archimate.elements=42`) without their namespace."""
    return ", ".join(f"{k.split('.', 1)[-1]}={v}" for k, v in detail.items())


def _node_events(h):
    """The DevUI-equivalent per-node event view, for a run this reviewer did not have to trigger."""
    st.markdown("**Inside the run** — every LLM and governed tool call, read back from the trace")
    if not h.get("trace_id"):
        st.caption("this run recorded no trace (tracing was off), so there is no per-node detail")
        return
    acts = _trace_activity(h)
    if not acts:
        st.caption("no trace detail (no node has run yet, the trace expired from Jaeger's store, or "
                   f"Jaeger is unreachable at {JAEGER_UI})")
        return
    for a in acts:
        with st.expander(_activity_label(a), expanded=bool(a.errors)):
            for e in a.errors:
                st.error(e)
            if a.llm:
                st.dataframe([{"model": c.model, "operation": c.operation, "seconds": round(c.seconds, 1),
                               "in": c.input_tokens, "out": c.output_tokens, "cost": c.cost,
                               "response": c.response_id} for c in a.llm], hide_index=True, width="stretch")
            if a.tools:
                st.dataframe([{"server": t.server, "tool": t.tool, "seconds": round(t.seconds, 1),
                               "detail": _detail_text(t.detail)} for t in a.tools],
                             hide_index=True, width="stretch")
            if not (a.llm or a.tools or a.errors):
                st.caption("no LLM or tool call in this step")


def _runs_board():
    act, rec = runlog.active(), runlog.recent(20)
    if not act and not rec:
        st.info("No runs recorded yet. Start one with `python -m lab.workloads.visio_to_archimate.host …`, "
                "from **Submit** mode, or in DevUI; it appears here the moment its first node starts.")
        return
    rows = [_run_row(h) for h in act + rec]
    ids = [r["run"] for r in rows]
    default = st.session_state.get("runs_selected")
    # the DETAIL is the view (watch a run); the list is one expander below (pick another run)
    sel = st.selectbox("Run", ids, index=ids.index(default) if default in ids else 0)
    st.session_state["runs_selected"] = sel
    h = runlog.get(sel)
    if h:
        _run_detail(h)
    else:
        st.warning(f"run {sel} expired")

    with st.expander(f"All runs — {len(act)} active, {len(rec)} recent"):
        st.caption("A workflow host reports every node transition through `src/lab/platform/runlog.py` "
                   "(`run:<id>` in Redis + one unbuffered stdout line). Rows expire after 7 days.")
        st.dataframe(rows, hide_index=True, width="stretch",
                     column_config={"trace": st.column_config.LinkColumn("trace", display_text="open in Jaeger")})


def _run_detail(h):
    icon, sel = STATUS_ICON.get(h.get("status"), "•"), h.get("run_id", "")
    st.subheader(f'{icon} `{sel}` — {h.get("status")}' + (f' · at **{h["node"]}**' if h.get("status") == "running" else ""))
    m = st.columns(5)
    m[0].write(f'**Process** {h.get("process", "")}'); m[1].write(f'**Input** `{h.get("input", "")}`')
    m[2].write(f'**Started** {h.get("started_at", "—")}'); m[3].write(f'**Finished** {h.get("finished_at", "—")}')
    m[4].write(f'**Elapsed** {_fmt_elapsed(h.get("elapsed"))}')
    if h.get("trace_id"):
        st.write(f'**Trace** [{h["trace_id"][:16]}…]({JAEGER}{h["trace_id"]})')
    if h.get("error"):
        st.error(h["error"])
    for k in ("request_id", "approval_id", "xml_ref"):
        if h.get(k):
            st.write(f"**{k}** `{h[k]}`")

    left, right = st.columns([2, 3])
    with left:
        st.markdown("**Node timeline**")
        timeline = [{"": STATUS_ICON.get(n["status"], "•"), "node": n["name"], "status": n["status"],
                     "at": n["ts"][11:19], "elapsed": _fmt_elapsed(n["attrs"].get("elapsed")),
                     "detail": ", ".join(f"{k}={v}" for k, v in n["attrs"].items() if k != "elapsed")}
                    for n in h.get("nodes") or []]
        if timeline:
            st.dataframe(timeline, hide_index=True, width="stretch")
        else:
            st.caption("no node reported yet")
    with right:
        st.markdown("**Workflow graph**")
        if h.get("mermaid"):
            _render_mermaid(_mermaid_with_state(h["mermaid"], _node_states(h)))
        else:
            st.caption("no graph stored on this run (the host stores `mermaid` via "
                       "`lab.workloads.workflowviz.mermaid(workflow)` at start)")
    _node_events(h)


@st.fragment(run_every=5)
def _runs_board_live():
    _runs_board()


def _runs_page(_reviewer):
    st.title("Runs")
    top = st.columns([1, 1, 6])
    if top[0].button("🔄 Refresh"):
        st.rerun()
    auto = top[1].toggle("Auto (5 s)", value=True, key="runs_auto")
    if auto:
        _runs_board_live()          # st.fragment re-runs only this board every 5 s
    else:
        _runs_board()


# ============================================================================ Review mode
def _xml_bytes(p):
    """The model XML from the artifact store, or None if it is missing/unavailable (the filename is
    the download's business, and downloads belong to the adapter's artifact list)."""
    if not p.get("xml_ref"):
        return None
    try:
        return container.artifacts().get(p["xml_ref"])
    except Exception as e:      # an old approval whose artifact expired/was purged must not crash the gate
        st.warning(f"model artifact unavailable for this request: {e}")
        return None


def _model_contents(p):
    """What the reviewer is judging: the ArchiMate model itself, grouped by type. The DOWNLOAD of it
    belongs to `_import_files` — the repository's adapter decides which files a human needs and how to
    label them, and one of them may well be this XML."""
    xml_bytes = _xml_bytes(p)
    if not xml_bytes:
        st.error(f"model artifact not available: {p.get('xml_ref')}")
        return
    root = ET.fromstring(xml_bytes)
    els = root.findall(".//a:elements/a:element", NS)
    rels = root.findall(".//a:relationships/a:relationship", NS)
    with st.expander(f"Model contents — {len(els)} elements, {len(rels)} relationships"):
        by_type = {}
        for e in els:
            by_type.setdefault(e.get("{http://www.w3.org/2001/XMLSchema-instance}type"), []).append(
                e.find("a:name", NS).text)
        for t in sorted(by_type):
            st.write(f"**{t}**: " + ", ".join(sorted(by_type[t])))


def _import_files(p):
    """The files a human must carry into the EA repository — RENDERED, not interpreted.

    Each entry is a {ref, label, note} the repository's own ADAPTER wrote (see
    `lab.platform.contracts.ImportArtifact`), so this app offers a download with the adapter's label
    and prints its note, and knows nothing about what any of them IS: an ADOIT object spreadsheet
    today, a change-set on another tool, nothing at all on a repository that writes over its own API.
    That is the point — the vendor's knowledge stays on the vendor's adapter. Approvals staged before
    this shape existed still render (the normaliser turns their flat `*_ref` fields into downloads),
    so a reviewer can open the ~10 requests already waiting."""
    for art in contracts.import_artifacts(p):
        try:
            data = container.artifacts().get(art.ref)
        except Exception as e:      # an old approval whose artifact expired must not break the gate
            st.warning(f"{art.label}: not available ({e})")
            continue
        st.download_button(art.label, data, file_name=art.filename, mime=art.mime)
        if art.note:
            st.caption(art.note)
    if p.get("instructions"):
        with st.expander("Import instructions (from the EA repository)"):
            st.text(p["instructions"])


def _views(p):
    views = []                                   # [(label, bytes)]
    for label, ref in (p.get("svg_refs") or {}).items():
        try:
            views.append((label, container.artifacts().get(ref)))
        except Exception as e:                   # noqa: BLE001
            st.warning(f"view {label}: {e}")
    if not views:
        return
    tabs = st.tabs([v[0] for v in views])
    for tab, (_, svg_bytes) in zip(tabs, views):
        with tab:
            data = base64.b64encode(svg_bytes).decode()
            st.markdown(f'<div style="overflow:auto;max-height:75vh;border:1px solid #ccc">'
                        f'<img src="data:image/svg+xml;base64,{data}"/></div>', unsafe_allow_html=True)


def _answer_form(p, request_id):
    """The form for an approval that asks a QUESTION, or None when it asks nothing.

    `request_id` is here ONLY to scope the widget keys, and that is load-bearing rather than tidy.
    Streamlit keys widget state on the key string for the whole browser session, and a speaker label
    is an anonymous provider placeholder — every meeting has a SPEAKER_00. Keyed on the label alone,
    switching between two pending approvals in the sidebar re-fills the second one's fields with what
    was typed into the first, and a pre-filled value counts as answered by the check below. The
    reviewer then approves meeting B carrying meeting A's identities, and the audit log records them
    doing it deliberately — the exact misattribution this whole gate exists to prevent.

    Rendered from what the PAYLOAD declares, never from the approval kind — the same property the
    Teams card and the approval tools keep, and what lets a new kind of question reach this page
    without it being edited.

    Returns the answer object, and the reason it is not yet answerable, so the caller can disable
    the approve button rather than let someone submit half an answer and be refused.
    """
    q = p.get("question") or {}
    prompts = contracts.speaker_prompts(p)
    if not prompts:
        return None, ""

    st.divider()
    st.subheader("Who is each speaker?")
    if q.get("prompt"):
        st.caption(q["prompt"])

    # Who the provider says attended, offered as a PICK. A suggestion and never a constraint: the
    # free-text boxes stay, because attending is not speaking and not everyone in the room is in the
    # directory. No candidates (the usual case when the meeting could not be resolved) renders
    # exactly the form that existed before.
    candidates = contracts.speaker_candidates(p)
    PICK_NONE = "— type it below —"
    if candidates:
        st.caption(f"{len(candidates)} attendee(s) reported by the meeting. Attending is not "
                   "speaking, and someone can attend and never say a word — pick only what you "
                   "actually recognise.")

    answer, missing = {}, []
    for prompt in prompts:
        st.markdown(f'**{prompt.label}** — {prompt.seconds:.0f}s across {prompt.turns} turn(s)')
        # the verbatim lines are what actually let a person recognise a voice
        for sample in prompt.samples:
            st.code(sample, language=None)
        picked = ""
        if candidates:
            chosen = st.selectbox("Attended this meeting", [PICK_NONE] + [c.label for c in candidates],
                                  key=f"pick_{request_id}_{prompt.label}",
                                  help="Picking one fills the identity for you. A typed address that "
                                       "is wrong survives this gate and only fails later, during "
                                       "attribution — by which time you are not here to correct it.")
            picked = next((c.identity for c in candidates if c.label == chosen), "")
        c1, c2 = st.columns(2)
        identity = c1.text_input("Directory identity", key=f"id_{request_id}_{prompt.label}",
                                 placeholder="maria@contoso.com",
                                 help="Their user principal name, if they are in the organisation.")
        tag = c2.text_input("or a free tag", key=f"tag_{request_id}_{prompt.label}",
                            placeholder="the vendor's architect",
                            help="For anyone outside the organisation. Not everyone in the room is "
                                 "in the directory, and guessing is worse than saying so.")
        identity, tag = identity.strip(), tag.strip()
        # A typed identity WINS over a pick: the box is the more specific act, and silently
        # overriding what someone typed is how a form loses a person's trust.
        identity = identity or picked
        if bool(identity) == bool(tag):
            missing.append(prompt.label)
        else:
            answer[prompt.label] = {"identity": identity} if identity else {"tag": tag}

    if missing:
        st.info(f'Give exactly one of identity or tag for: {", ".join(missing)}. '
                "Every speaker must be answered — an unidentified voice stops the minutes.")
        return answer, f'{len(missing)} speaker(s) still unanswered'
    return answer, ""


def _review_page(reviewer):
    # drain this channel's unseen events (mark delivered) — the pending set drives the UI
    for eid, _ in approvals.channel_events("review-app", block_ms=0):
        approvals.ack("review-app", eid)

    st.title("Architecture Review")
    items = approvals.pending()
    st.sidebar.metric("Pending", len(items))
    if not items:
        st.info("Nothing awaiting a person. Staged models and questions a run could not answer "
                "itself both appear here.")
        st.subheader("Recent decisions")
        for h in approvals.history(20):
            st.write(f'`{h["request_id"]}` **{h["decision"]}** by {h["actor"]} via {h["channel"]} — {h["comment"]} ({h["decided_at"]})')
        return

    labels = [f'{i["subject"]} · {i["request_id"]}' for i in items]
    # A card links here with ?approval=<id>: a reviewer with three open should land on theirs.
    wanted = st.query_params.get("approval")
    index = next((n for n, i in enumerate(items) if i["request_id"] == wanted), 0)
    choice = st.sidebar.radio("Requests", labels, index=index)
    req = items[labels.index(choice)]
    p = req["payload"]

    st.subheader(req["subject"])
    c1, c2, c3, c4 = st.columns(4)
    c1.write(f'**Request** `{req["request_id"]}`'); c2.write(f'**From** {req["requester"]}')
    c3.write(f'**Status** {req["status"]}'); c4.write(f'**Created** {req["created_at"]}')
    if req.get("trace_id"):
        st.write(f'**Trace** [{req["trace_id"][:16]}…]({JAEGER}{req["trace_id"]}) — the run that produced this model')
    if req.get("comment"):
        st.warning(f'Last comment ({req.get("decided_by")} via {req.get("decided_via")}): {req["comment"]}')

    summ = p.get("summary", {})
    # existing-architecture resolution — is this NEW or an UPDATE to something already in the repository?
    decision = summ.get("decision")
    if decision:
        if decision == "UPDATE":
            base = summ.get("base_model") or summ.get("domain")
            st.warning(f'**UPDATE** to **{base}** (domain: {summ.get("domain")}) — '
                       f'{summ.get("matched_existing", 0)} existing element(s) reused, '
                       f'{summ.get("new_elements", 0)} new. Approving reuses the existing repository object ids.')
        else:
            st.success(f'**NEW** model in domain **{summ.get("domain")}** — {summ.get("new_elements", summ.get("elements"))} new element(s).')
        if summ.get("resolve_rationale"):
            st.caption(summ["resolve_rationale"])
    m = st.columns(5)
    for col, k in zip(m, ("elements", "relations", "views", "violations", "warnings")):
        col.metric(k, summ.get(k, "—"))

    _model_contents(p)
    _views(p)
    _import_files(p)
    answer, blocked = _answer_form(p, req["request_id"])

    # --- decision ---
    st.divider()
    comment = st.text_area("Comment (required for changes / decline)")
    b1, b2, b3 = st.columns(3)

    def _decide(d):
        if d != "approve" and not comment.strip():
            st.error("A comment is required for that decision."); return
        try:
            # the ONE human-gate path (identified actor, legal decision, one final answer claimed
            # atomically) — the same terms Teams, Telegram, the CLI and approvals_decide record on
            approvals.human_decision(req["request_id"], d, reviewer, "review-app", comment.strip(),
                                     answer=answer if d == "approve" else None)
        except ValueError as e:                 # blank reviewer, or already decided
            st.error(str(e)); return
        st.success(f"Recorded: {d}"); st.rerun()
    # An approval that asks a question is approved by ANSWERING it, so the button says so and is
    # disabled until every speaker has one — better than letting someone submit and be refused.
    approve_label = "✅ Approve — start the minutes" if answer is not None else "✅ Approve — release for import"
    if b1.button(approve_label, type="primary", disabled=bool(blocked),
                 help=blocked or None): _decide("approve")
    if b2.button("✏️ Request changes"): _decide("update")
    if b3.button("⛔ Decline"): _decide("decline")


# ============================================================================ page
PAGES = {"Review": _review_page, "Submit": _submit_page, "Runs": _runs_page}


def main():
    st.set_page_config(page_title="Architecture Review", page_icon="🏛️", layout="wide")
    if config.REVIEW_APP_PASSWORD:      # minimal gate; production fronts this app with Entra / an identity-aware proxy
        if st.session_state.get("authed") is not True:
            pw = st.text_input("Review app password", type="password")
            if pw == config.REVIEW_APP_PASSWORD:
                st.session_state["authed"] = True; st.rerun()
            st.stop()
    # the audit log answers "who released this EA-repository write", so the reviewer is never blank
    reviewer = st.sidebar.text_input("Reviewer", value=os.environ.get("USER", "reviewer")).strip()
    if not reviewer:
        st.sidebar.warning("Enter your name to decide — an approval must carry the human who made it.")
    mode = st.sidebar.radio("Mode", list(PAGES), horizontal=True)
    PAGES[mode](reviewer)


if __name__ == "__main__":
    main()
