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
import json
import os
import re
import xml.etree.ElementTree as ET
from html import escape

import streamlit as st

from lab.platform import config, contracts, runlog, workflows
from lab.platform.filetypes import content_type_for
from lab.substrate import approvals
from lab.substrate.container import build
from lab.substrate.review import identity, intake_csv, roadmap, staging, traces

container = build("review-app")
JAEGER_UI = container.config.jaeger_ui_url().rstrip("/")   # one source for both the link and the reader
JAEGER = JAEGER_UI + "/trace/"
TRACES = traces.JaegerTraceReader(JAEGER_UI)               # trace-store port; tests swap it wholesale
NS = {"a": "http://www.opengroup.org/xsd/archimate/3.0/"}
DIAGRAM_TYPES = ["vsdx", "png", "jpg", "jpeg", "gif", "webp"]
REQUIREMENT_TYPES = ["docx", "pdf", "md", "txt", "csv"]

#: Which file types each REF field accepts, by (process, field). A hint only — the CONTRACT is
#: `ProcessSpec.validate`, and a field with no entry accepts anything the store will hold. It lives
#: here rather than in the contract because "what a file picker offers" is a presentation choice,
#: and putting it in the contract would make an upload surface able to narrow what a process means.
UPLOAD_TYPES = {
    ("visio_to_archimate", "diagram"): DIAGRAM_TYPES,
    ("visio_to_archimate", "requirements"): REQUIREMENT_TYPES,
    ("use_case_screening", "submission"): REQUIREMENT_TYPES,
    ("use_case_screening", "attachments"): REQUIREMENT_TYPES + DIAGRAM_TYPES,
}

#: Suggested rows for a MAPPING field, so a person filling one in is not staring at an empty
#: key/value grid. Suggestions ONLY: every row is editable and rows can be added, because a
#: submission that does not fit the suggested shape must still be possible to make.
MAPPING_ROWS = {
    ("use_case_screening", "intake"): "intake-fields",       # the corpus ARTIFACT, read under a pin
}

#: The TYPED fields inside those groups — one record per field, so the form is generated rather than
#: guessed. Adding a field later (ROI, say) is a corpus publish, not a change to this app.
MAPPING_FIELDS = {
    ("use_case_screening", "intake"): ("intake-field-specs", "intake-field"),
}


def _mapping_labels(process: str, field: str) -> list[str]:
    """The field groups a governed artifact publishes for this mapping, or none.

    Read from the CORPUS under a pin taken once per session — the same artifact, at the released
    version, that the valuation steps consume — and recorded in the consumption trail like any
    other read. Never the packaged seed: the form would otherwise suggest the fields the image
    was built with, not the ones Finance has released since. A corpus that cannot answer is a
    suggestion missing, never a submission refused."""
    artifact = MAPPING_ROWS.get((process, field))
    if not artifact:
        return []
    cache = st.session_state.setdefault("intake_labels", {})
    if artifact in cache:
        return list(cache[artifact])
    try:
        from lab.core.reference.model import RunRef
        library = container.reference()
        pin = library.pin([artifact])
        rows = library.lookup(pin, record_type="field-group", key={},
                              run=RunRef(run_id="review-app", process="review-app", field=field),
                              artifact_id=artifact).records
        labels = [str(r.body.get("Field group") or "").strip() for r in rows]
        cache[artifact] = [label for label in labels if label]
    except Exception:                      # a missing or unpublished artifact is a suggestion
        cache[artifact] = []               # missing, never a submission refused
    return list(cache[artifact])


#: The two corpus artifacts the roadmap is built from: the published methodology, and the join to
#: the implementation's step numbers, record keys and AGENTS.
ROADMAP_ARTIFACTS = (("process-steps", "process-step"), ("process-step-keys", "step-key"))

#: Which HALF of the published methodology a run belongs to, so the roadmap draws that run's steps
#: and not the whole book. Screening implements E0.1-E0.10 and the readiness gate; everything from
#: Q1.1 down is the design half, run later and separately. Drawing all nineteen rows made a
#: COMPLETED screening look half-finished, with ten rows permanently pending that were never its
#: to run. A process absent here is not filtered — unknown is shown in full, never hidden.
PROCESS_HALF = {
    "use_case_screening": "screening",
    "use_case_design": "design",
}


def _corpus_table(artifact: str, record_type: str) -> tuple:
    """`(rows, headers)` for a whole-retrieval artifact, read under a pin and cached per session.

    Same contract as `_mapping_labels`: a corpus that cannot answer is a view missing, never a page
    that fails — and the roadmap says so rather than inventing the process from code.
    """
    cache = st.session_state.setdefault("corpus_tables", {})
    if artifact in cache:
        return cache[artifact]
    try:
        from lab.core.reference.model import RunRef
        library = container.reference()
        pin = library.pin([artifact])
        records = library.lookup(pin, record_type=record_type, key={},
                                 run=RunRef(run_id="review-app", process="review-app",
                                            field="roadmap"),
                                 artifact_id=artifact).records
        headers = list(records[0].body) if records else []
        cache[artifact] = ([[r.body.get(h, "") for h in headers] for r in records], headers)
    except Exception:                      # noqa: BLE001 — a view missing, never a page that fails
        cache[artifact] = ([], [])
    return cache[artifact]


def _roadmap_view(h):
    """The run as the nineteen published steps, with this run's state on each.

    Replaces the Mermaid graph, which drew EXECUTORS — `readiness`, `feasibility`, `derive_design` —
    and so answered "which node" when an SME is asking "which step".
    """
    (steps_rows, steps_headers) = _corpus_table(*ROADMAP_ARTIFACTS[0])
    (key_rows, key_headers) = _corpus_table(*ROADMAP_ARTIFACTS[1])
    if not steps_rows:
        st.caption("the published process steps could not be read from the corpus, so there is no "
                   "roadmap to draw — the methodology is an artifact, not a list in this app")
        return
    record = _record_of(h)
    plan = roadmap.build(steps_rows, steps_headers,
                         roadmap.index_from(key_rows, key_headers),
                         order=roadmap.order_from(key_rows, key_headers),
                         nodes=h.get("nodes") or [], record=record,
                         process=PROCESS_HALF.get(h.get("process", ""), ""),
                         activity=_trace_activity(h))
    for step in plan:
        icon = {"done": "✅", "running": "🏃", "failed": "⛔", "defaulted": "⚠️"}.get(step.state, "⚪")
        who = step.agent or ("derived, not asked" if step.derived else "")
        head = f"{icon} **{step.id}** {step.title}" + (f" · {who}" if who else "")
        if step.elapsed:
            head += f" · {_fmt_elapsed(step.elapsed)}"
        with st.expander(head, expanded=step.open):
            if step.note:
                st.warning(step.note)
            if step.error:
                st.error(step.error)
            cols = st.columns(3)
            cols[0].caption(f"**Input**  \n{step.inputs_declared or '—'}")
            cols[1].caption(f"**Decides**  \n{step.decided or '—'}")
            cols[2].caption(f"**Output**  \n{step.outputs_declared or '—'}")
            for gap in step.gaps:
                st.warning(gap)
            if step.model:
                st.caption(f"{step.model} · {step.tokens:,} tokens · ${step.cost:.4f}")
            # The three captions above are the PUBLISHED contract — the same words on every run.
            # These two are what THIS run did, and they are what a reviewer came for.
            actual = st.columns(2)
            with actual[0]:
                st.caption(f"**What it was shown**  \n`{'`, `'.join(step.reads) or '—'}`")
                if step.input is not None:
                    st.json(step.input, expanded=False)
            with actual[1]:
                st.caption("**What it produced**")
                if step.output is not None:
                    st.json(step.output, expanded=False)
                else:
                    st.caption("— nothing recorded yet")


def _record_of(h) -> dict:
    """The run's own record, for the per-step sections the roadmap shows. Absent is `{}` — a run
    still in flight has not written one, and every step then shows its published shape alone."""
    # `record_ref` FIRST: it is the partial record a live run republishes after every step, so a
    # run in flight — the only time anyone is watching — shows what each step actually produced.
    # `screening_ref` is the finished article and wins once the run closes, because `finish_from`
    # writes it last. Preferring the partial for a DONE run would show a record one step short.
    ref = (h.get("screening_ref") or h.get("design_ref") or h.get("xml_ref")
           or h.get("record_ref"))
    if not ref or not str(ref).endswith(".json"):
        return {}
    try:
        raw = container.artifacts().get(ref)
        return json.loads(raw if isinstance(raw, str) else raw.decode())
    except Exception:                      # noqa: BLE001
        return {}


#: A worked example, filled in: the use-case screening agent group assessed as a use case of itself.
#: Ships in the image (`pyproject.toml` package-data) so the page can hand it over without a network
#: read. It is an EXAMPLE, not a schema — the schema is the published artifact, and a row of this
#: file that no longer matches one is reported by the parser like any other unknown field.
SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "samples", "intake-agent.csv")


def _intake_from_csv(rows, headers, key: str) -> None:
    """Fill the intake from a CSV file instead of twenty-one boxes.

    The template is GENERATED from the same published rows the form is, so it cannot drift from the
    fields; a stale hand-written column would be indistinguishable from a typo. The upload sets the
    widgets' own session state and reruns, so what lands is an ordinary filled-in form the person
    can read and correct — not a hidden payload that bypasses the one surface they can check.
    """
    col = {h: i for i, h in enumerate(headers)}
    with st.expander("📄 Fill this in from a CSV file", expanded=False):
        left, right = st.columns(2)
        left.download_button("⬇️ Blank template (.csv)", intake_csv.template(rows, headers),
                             file_name="intake-template.csv", mime="text/csv",
                             key=f"{key}_tmpl", use_container_width=True)
        try:
            with open(SAMPLE_CSV, "rb") as handle:
                right.download_button("⬇️ Filled example (.csv)", handle.read(),
                                      file_name="intake-example.csv", mime="text/csv",
                                      key=f"{key}_sample", use_container_width=True)
        except OSError:                    # an example missing is not a submission refused
            right.caption("no filled example ships with this build")
        st.caption("Fill the **Value** column and upload it back here. A blank cell means *not answered*; "
                   "every field is still editable below before you run.")
        upload = st.file_uploader("Completed intake", type=["csv"], key=f"{key}_csv")
        if upload is None:
            return
        # Apply ONCE per file: this reruns top-to-bottom on every interaction, and re-applying would
        # silently undo an edit the person made to a field after uploading.
        stamp = f"{upload.name}:{upload.size}"
        if st.session_state.get(f"{key}_csv_done") == stamp:
            return
        answer, problems = intake_csv.parse(upload.getvalue(), rows, headers)
        # `Field` is the full "Group · Label" key the parser resolves to, and also the widget key
        # suffix `_typed_intake` uses — one identity, so the join needs no second convention.
        kinds = {str(r[col["Field"]]): str(r[col["Type"]]) for r in rows}
        for label, value in answer.items():
            text = str(value.get("value", ""))
            # A yes/no field is a selectbox, and Streamlit refuses a value outside its options.
            if kinds.get(label) == "yesno" and text.strip().lower() not in ("yes", "no"):
                problems.append(f"{label}: {text!r} is not yes or no — left blank")
                continue
            st.session_state[f"{key}_{label}"] = (text.strip().lower()
                                                  if kinds.get(label) == "yesno" else text)
        st.session_state[f"{key}_csv_done"] = stamp
        st.session_state[f"{key}_csv_note"] = (len(answer), problems)
        st.rerun()


def _typed_intake(process: str, field, key: str) -> dict | None:
    """One input per PUBLISHED field, grouped — or None when the corpus cannot say what the fields
    are, in which case the caller falls back to the free grid.

    The answer shape is unchanged: `{label: {"value": text}}`, which is what `InputKind.MAPPING`
    means and what every other producer sends. A type here is a widget and a hint to the person, not
    a promise about the wire — `InputField._mapping` accepts strings only.
    """
    spec = MAPPING_FIELDS.get((process, field.name))
    rows, headers = _corpus_table(*spec) if spec else ([], [])
    if not rows:
        return None
    _intake_from_csv(rows, headers, key)
    filled, problems = st.session_state.pop(f"{key}_csv_note", (0, []))
    if filled or problems:
        st.success(f"{filled} field{'' if filled == 1 else 's'} filled in from the CSV")
        # Named, never dropped: a row that went nowhere is invisible once filtered, and the
        # submission then arrives short with nothing to explain it.
        for problem in problems:
            st.warning(problem)
    col = {h: i for i, h in enumerate(headers)}
    answer: dict = {}
    for group in dict.fromkeys(str(r[col["Group"]]) for r in rows):
        with st.expander(group, expanded=True):
            for row in [r for r in rows if str(r[col["Group"]]) == group]:
                label, kind = str(row[col["Label"]]), str(row[col["Type"]])
                required = str(row[col.get("Required", 0)]).strip().lower() == "yes"
                widget_key = f"{key}_{row[col['Field']]}"
                shown = f"{label}{'' if required else ' (optional)'}"
                if kind == "yesno":
                    picked = st.selectbox(shown, ["", "yes", "no"], key=widget_key)
                else:
                    picked = st.text_input(shown, key=widget_key,
                                           help=f"{kind} — used by {row[col['Used by']]}"
                                           if "Used by" in col else kind)
                if str(picked).strip():
                    answer[f"{group} · {label}"] = {"value": str(picked).strip()}
    return answer


def _mapping_editor(process: str, field, key: str) -> dict:
    """The published fields when the corpus can name them, and a free label/value grid when it
    cannot. `MAPPING` is a human's answer, not a payload — the contract bounds it, and this offers
    the shape rather than enforcing it."""
    typed = _typed_intake(process, field, key)
    if typed is not None:
        return typed
    rows = st.session_state.setdefault(key, [{"label": name, "value": ""}
                                             for name in _mapping_labels(process, field.name)]
                                            or [{"label": "", "value": ""}])
    edited = st.data_editor(rows, key=f"{key}_ed", num_rows="dynamic", use_container_width=True,
                            column_config={"label": st.column_config.TextColumn("Field"),
                                           "value": st.column_config.TextColumn("Value")})
    # `label -> {field: value}`, which is what `InputKind.MAPPING` means and what every other
    # producer sends. A flat `label -> value` is refused by the contract — found by trying to
    # submit one, because no test asserted the shape this widget produces against the validator
    # that has to accept it.
    return {r["label"].strip(): {"value": r["value"].strip()} for r in edited
            if str(r.get("label", "")).strip() and str(r.get("value", "")).strip()}


#: What a text field's kind expects, shown IN the empty box. Derived from the kind's own validator
#: (`InputField._handle`/`._identity`/`._conversation`), not invented here — a placeholder that
#: disagreed with the validator would be worse than none.
PLACEHOLDERS = {
    contracts.InputKind.HANDLE: "collab://item/<drive-id>/<item-id>",
    contracts.InputKind.IDENTITY: "name@domain, or a directory object id",
    contracts.InputKind.CONVERSATION: "the provider's conversation id",
    contracts.InputKind.REF: "art://<id>/<name>",
}


def _field_widget(spec, field) -> object:
    """One input field, rendered from its KIND. Adding a process adds no code here.

    REF and REF_LIST are the exception and deliberately so: content reaches a workload only as a
    reference, so the widget uploads first and the run is given what the store returned."""
    kinds = contracts.InputKind
    types = UPLOAD_TYPES.get((spec.name, field.name))
    label = f'{field.name}{"" if field.required else " (optional)"}'
    if field.kind is kinds.REF:
        return st.file_uploader(label, type=types, key=f"up_{spec.name}_{field.name}",
                                help=field.description)
    if field.kind is kinds.REF_LIST:
        return st.file_uploader(label, type=types, accept_multiple_files=True,
                                key=f"up_{spec.name}_{field.name}", help=field.description)
    if field.kind is kinds.MAPPING:
        st.caption(f"**{label}** — {field.description}")
        return _mapping_editor(spec.name, field, f"map_{spec.name}_{field.name}")
    if field.kind is kinds.CHOICE and getattr(field, "choices", ()):
        # It declared its options and was still rendered as free text, so the one field whose valid
        # answers are KNOWN was the one most easily got wrong.
        picked = st.selectbox(label, ["", *field.choices], key=f"in_{spec.name}_{field.name}",
                              help=field.description)
        return picked or ""
    # Three kinds fall through to a text box, and each has a STRICT validator behind it: HANDLE
    # parses as `collab://kind/scope/id`, IDENTITY refuses a display name, CONVERSATION refuses
    # whitespace and URLs. They looked identical to free text with the format hidden in a hover,
    # so a person typed their own name into the first box on the form and learned the rule from a
    # rejection. A placeholder shows the shape before it is typed, which is the whole difference.
    return st.text_input(label, key=f"in_{spec.name}_{field.name}", help=field.description,
                         placeholder=PLACEHOLDERS.get(field.kind, ""))


# ============================================================================ Submit mode
def _submit_page(reviewer):
    """Start a run of any process an outside caller may start.

    Rendered from `ProcessSpec` rather than written per process: `verbs_for` already decides which
    processes have an entry point at all, so a continuation cannot be started from here for the
    same reason it cannot be started through the gateway — the surface is generated from the same
    contract, not guarded by a second rule that could disagree with the first."""
    startable = [s for s in contracts.PROCESSES.values() if s.external]
    st.title("Submit work to a business process")
    st.caption("Files are stored by reference; the workflow reads them through the governed "
               "gateway. Nothing runs until you press Run.")

    names = [s.name for s in startable]
    chosen = st.selectbox("Process", names, format_func=lambda n: contracts.PROCESSES[n].title)
    spec = contracts.PROCESSES[chosen]
    st.caption(spec.description)

    refs = st.session_state.setdefault(f"submit_refs_{spec.name}", {})
    widgets = {f.name: _field_widget(spec, f) for f in spec.inputs}

    file_fields = [f for f in spec.inputs
                   if f.kind in (contracts.InputKind.REF, contracts.InputKind.REF_LIST)]
    required_files = [f.name for f in file_fields if f.required]
    have_required = all(widgets.get(n) is not None and widgets.get(n) != [] for n in required_files)

    if file_fields and st.button("⬆️ Upload", disabled=not have_required):
        store = container.uploads()
        for field in file_fields:
            value = widgets.get(field.name)
            # The original filename is KEPT: several workloads decide how to read an input from
            # its suffix, and a store-assigned name would take that decision away from them.
            if field.kind is contracts.InputKind.REF and value is not None:
                refs[field.name] = store.put(value.name, value.getvalue(),
                                             content_type_for(value.name))
            elif field.kind is contracts.InputKind.REF_LIST:
                refs[field.name] = [store.put(f.name, f.getvalue(), content_type_for(f.name))
                                    for f in (value or [])]
        st.session_state[f"submit_rid_{spec.name}"] = None
        st.success("Stored. Review the references below, then press Run.")

    for name, value in refs.items():
        if value:
            st.write(f"**{name}**", " ".join(f"`{v}`" for v in
                                             (value if isinstance(value, list) else [value])))

    # What Run is allowed to send. It used to check only REQUIRED FILE fields, and for
    # `use_case_screening` that list is EMPTY — both submission routes are individually optional
    # because the real rule is "exactly one of them" — so Run was always enabled and pressing it
    # with nothing attached queued a run that died at the first executor. Now the button asks the
    # same three questions `ProcessSpec.validate` will ask, so the form refuses what the contract
    # would refuse, rather than a 600-second run discovering it.
    def _supplied(name: str) -> bool:
        value = refs.get(name, widgets.get(name))
        return bool(value) if not isinstance(value, str) else bool(value.strip())

    missing = [f.name for f in spec.inputs if f.required and not _supplied(f.name)]
    unmet = [g for g in spec.one_of if sum(_supplied(n) for n in g) != 1]
    ready = not missing and not unmet
    for group in unmet:
        st.caption("Supply exactly one of " + " or ".join(f"**{n}**" for n in group)
                   + " — upload a document, or give the handle of one already in the "
                     "collaboration platform.")
    if missing:
        st.caption("Still needed: " + ", ".join(f"**{n}**" for n in missing))
    if st.button(f"▶️ Run {spec.name}", type="primary", disabled=not ready):
        inputs = dict(refs)
        for field in spec.inputs:
            if field not in file_fields:
                inputs[field.name] = widgets.get(field.name)
        try:    # the process's OWN contract validates every producer (lab.platform.contracts)
            rid = workflows.request(spec.name, {k: v for k, v in inputs.items() if v},
                                    requester=reviewer)
        except ValueError as e:
            st.error(f"rejected: {e}")
        else:
            st.session_state[f"submit_rid_{spec.name}"] = rid
            st.rerun()

    rid = st.session_state.get(f"submit_rid_{spec.name}")
    if rid:
        _run_status(rid)

    st.divider()
    st.subheader("Recent submissions")
    for sub in workflows.recent(10):
        inp = sub.get("inputs") or {}
        files = [os.path.basename(str(v)) for v in inp.values() if isinstance(v, str)
                 and str(v).startswith("art://")]
        line = (f'`{sub.get("request_id")}` **{sub.get("status", "?")}** — '
                f'{sub.get("process", "")} {", ".join(files[:2])} '
                f'({sub.get("requester")}, {sub.get("created_at")})')
        if sub.get("approval_id"):
            line += f' → approval `{sub["approval_id"]}`'
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


def _runs_board(live: bool = True):
    # `live=False` holds the view still by reusing the last read rather than by not drawing — see
    # `_runs_board_live`. A first render always reads, because there is nothing to hold yet.
    if live or "runs_snapshot" not in st.session_state:
        st.session_state["runs_snapshot"] = (runlog.active(), runlog.recent(20))
    act, rec = st.session_state["runs_snapshot"]
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

    st.markdown("**Roadmap**")
    _roadmap_view(h)
    with st.expander("Node timeline — the executors, for debugging the workflow itself"):
        timeline = [{"": STATUS_ICON.get(n["status"], "•"), "node": n["name"], "status": n["status"],
                     "at": n["ts"][11:19], "elapsed": _fmt_elapsed(n["attrs"].get("elapsed")),
                     "detail": ", ".join(f"{k}={v}" for k, v in n["attrs"].items() if k != "elapsed")}
                    for n in h.get("nodes") or []]
        if timeline:
            st.dataframe(timeline, hide_index=True, width="stretch")
        else:
            st.caption("no node reported yet")
    _node_events(h)


@st.fragment(run_every=5)
def _runs_board_live():
    """The board, re-rendered every 5 s.

    Called UNCONDITIONALLY, and that is the whole point. It used to be `if auto: _runs_board_live()
    else: _runs_board()`, which walks into two known Streamlit defects at once: a `run_every`
    fragment that stops being called loses its id (streamlit#9080, "Could not find fragment with
    id"), and a fragment registered in a previous session is stale after a browser reload
    (streamlit#11660, "Fragment does not exist anymore after reloading the page"). Measured
    18 Sep 2026: auto-refresh stopped after a manual page refresh and never restarted.

    So the toggle gates the WORK rather than the CALL. Off, the board re-renders from the snapshot
    it last read instead of hitting Redis — which is also what a person means by turning it off:
    hold the view still, not stop drawing it.
    """
    _runs_board(live=bool(st.session_state.get("runs_auto", True)))


def _runs_page(_reviewer):
    st.title("Runs")
    top = st.columns([1, 1, 6])
    if top[0].button("🔄 Refresh"):
        st.session_state.pop("runs_snapshot", None)
        st.rerun()
    top[1].toggle("Auto (5 s)", value=True, key="runs_auto")
    _runs_board_live()


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


#: The figures a reviewer judges the open items against — shown only when the approval carries them,
#: so a model approval keeps the five counts above and nothing else changes.
_HEADLINE = (("recommendation", "Recommendation"), ("topology", "Topology"),
             ("components", "Components"), ("year_one_cost", "Year-one cost"),
             ("annual_benefit", "Annual benefit"))


def _still_open(summ):
    """What the work has left OPEN, before the reviewer opens anything.

    A conformance approval used to arrive with an EMPTY summary: a package of twenty-five sections,
    a question, and nothing saying that four obligations were bound to no enforcement point. The
    reviewer then judges what reads well rather than what is complete, which is the one failure this
    gate exists to prevent.
    """
    figures = [(label, summ[key]) for key, label in _HEADLINE if summ.get(key) not in (None, "")]
    if figures:
        cols = st.columns(len(figures))
        for col, (label, value) in zip(cols, figures):
            col.metric(label, f"{value:,.0f}" if isinstance(value, (int, float)) else str(value))
    total, priced = summ.get("components"), summ.get("components_priced")
    if isinstance(total, int) and isinstance(priced, int) and priced < total:
        st.caption(f"The year-one figure prices {priced} of {total} selected components — the rest "
                   f"have no line in the catalogue at this envelope.")
    open_items = [str(o) for o in (summ.get("owed") or []) if str(o).strip()]
    if not open_items:
        if summ.get("owed") is not None:
            st.success("Nothing outstanding: every obligation is bound, every figure computed.")
        return
    st.warning(f"**{len(open_items)} thing(s) still open** — approving accepts them as they are.")
    for item in open_items[:20]:
        st.markdown(f"- {item}")
    if len(open_items) > 20:
        st.caption(f"…and {len(open_items) - 20} more, in the record.")


def _model_contents(p):
    """What the reviewer is judging: the ArchiMate model itself, grouped by type. The DOWNLOAD of it
    belongs to `_import_files` — the repository's adapter decides which files a human needs and how to
    label them, and one of them may well be this XML.

    PAYLOAD-DRIVEN, never kind-driven — the rule every other channel already follows (see
    `channels/teams.py`, which picks its sections from what the payload HAS). An approval that
    carries no model is not a broken approval: a speaker-mapping question has no `xml_ref` at all,
    and this is the one channel that can actually answer one. Saying nothing is the correct render;
    an error is reserved for a ref that was DECLARED and could not be read.
    """
    if not p.get("xml_ref"):
        return
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
    if contracts.answer_fields(p) == ("value",):
        return _item_form(q, prompts, request_id)   # declared by the asker: a question, not a line-up

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


def _item_form(q, prompts, request_id):
    """One value per label, for a question whose items are not voices — the criticality class.

    The items carry no seconds or turns because nobody spoke; their `samples` are the answers the
    asker suggests (the classes of the taxonomy), offered as a pick BESIDE free text and never
    instead of it. The answer travels as the same MAPPING every other surface builds —
    `{label: {"value": text}}` — so the completeness gate and the process contract stay generic.
    """
    st.divider()
    if q.get("prompt"):
        st.caption(q["prompt"])
    answer, missing = {}, []
    PICK_NONE = "— choose —"
    for prompt in prompts:
        typed, picked = "", ""
        if prompt.samples:
            c1, c2 = st.columns(2)
            chosen = c1.selectbox(prompt.label, [PICK_NONE] + list(prompt.samples),
                                  key=f"pick_{request_id}_{prompt.label}")
            picked = "" if chosen == PICK_NONE else chosen
            typed = c2.text_input(f"{prompt.label} — or type it",
                                  key=f"val_{request_id}_{prompt.label}")
        else:
            typed = st.text_input(prompt.label, key=f"val_{request_id}_{prompt.label}")
        value = typed.strip() or picked            # what someone typed wins over a pick
        if value:
            answer[prompt.label] = {"value": value}
        else:
            missing.append(prompt.label)
    if missing:
        st.info(f'Answer {", ".join(missing)} — approving is answering, and a blank is not an answer.')
        return answer, f'{len(missing)} still unanswered'
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
    _still_open(summ)

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
    # ...and says what approving STARTS, read from the continuation the asker declared. Guarded,
    # because `continuation_of` refuses a process this build does not know — version skew between
    # a review app and the workload that staged the approval — and a caption must not make the
    # approval undecidable: the reviewer can still decline or comment.
    try:
        cont = contracts.continuation_of(p)
    except ValueError as e:
        cont = None
        st.warning(f"This approval declares a continuation this build cannot start: {e}")
    approve_label = (f"✅ Approve — start the {cont.starts}" if cont
                     else "✅ Approve — record the answer" if answer is not None
                     else "✅ Approve — release for import")
    if b1.button(approve_label, type="primary", disabled=bool(blocked),
                 help=blocked or None): _decide("approve")
    if b2.button("✏️ Request changes"): _decide("update")
    if b3.button("⛔ Decline"): _decide("decline")


# ============================================================================ Artifacts mode


def _artifacts_page(reviewer):
    """Admin: replace a reference artifact's master, validated, and STAGE it.

    It cannot publish, and says so. The corpus publisher holds the Ed25519 signing seed, which is
    deliberately kept out of `.env` and `LAB_ENV` — putting it behind a web session would make the
    thing that signs the corpus reachable by anyone who reaches this page. So the app does the part
    that actually prevents a bad corpus (validate, diff, stage) and an operator does the part that
    needs the key.
    """
    st.title("Reference artifacts")
    st.caption("Upload a replacement master. It is validated and staged; an operator signs and "
               "releases it. Nothing here changes what a run reads until they do.")
    names = staging.artifact_names()
    if not names:
        st.info("No artifact catalogue available — the publisher's artifact table could not be read.")
        return
    artifact_id = st.selectbox("Artifact", names)
    upload = st.file_uploader("New master (markdown)", type=["md"], key=f"master_{artifact_id}")
    if upload and st.button("Validate and stage", type="primary"):
        try:
            result = staging.stage(artifact_id, upload.getvalue(), actor=reviewer)
        except staging.StagingError as bad:
            st.error(f"Refused: {bad}")           # the reason, not just a refusal
            return
        st.success(f"Staged {artifact_id}: {result.records} record(s), "
                   f"{len(result.added)} added, {len(result.removed)} removed, "
                   f"{len(result.changed)} changed.")
        for title, rows in (("Added", result.added), ("Removed", result.removed),
                            ("Changed", result.changed)):
            if rows:
                with st.expander(f"{title} — {len(rows)}"):
                    st.dataframe(rows, use_container_width=True)
        st.code(f"python -m lab.substrate.reference.publish publish {artifact_id} --from-staged",
                language="bash")
    for cand in staging.list_staged():
        st.caption(f"staged: **{cand['artifact_id']}** by {cand['actor']} at {cand['staged_at']} "
                   f"— {cand['records']} records")


# ============================================================================ page
#: The dispatch table, and now the authorisation beside it: `name -> (page, roles that may reach it)`.
#: Together, so a page cannot be added without somebody deciding who it is for — the table was
#: always the only routing, and a second table of permissions would be a second thing to forget.
#: An EMPTY role tuple means any signed-in person; it is not the same as "no reader".
PAGES = {
    "Review":    (_review_page, (identity.ARCHITECT, identity.BUSINESS)),
    "Submit":    (_submit_page, (identity.ARCHITECT, identity.BUSINESS)),
    "Runs":      (_runs_page, identity.ROLES),
    "Artifacts": (_artifacts_page, (identity.ADMIN,)),
}


def pages_for(principal) -> list:
    """The pages this person may open, in table order."""
    return [name for name, (_, roles) in PAGES.items() if principal.holds_any(roles)]


def may_open(principal, name: str) -> bool:
    """Checked again at the point of entry, not only when building the menu. A hidden option is not
    an authorisation control — the mode is a query parameter anyone can set."""
    entry = PAGES.get(name)
    return bool(entry) and principal.holds_any(entry[1])


def _announce_build():
    """Print the build ONCE per process, not once per Streamlit rerun.

    Streamlit re-executes the whole script on every interaction, so a module-level print would put a
    line in the deploy log for every click — and `deploymentLogs` returns a bounded window, so the
    startup line of a busy app would scroll away exactly when someone needs it. A process-global
    flag keeps it to one.
    """
    if not getattr(_announce_build, "done", False):
        print(f"review: serving  {config.build_id()}", flush=True)
        _announce_build.done = True


def _principal():
    """Who is signed in, or None when SSO is not configured.

    Entra when it is configured, and the shared password otherwise — the fallback is deliberate: a
    half-configured SSO must not half-enable the gate, and "not set up" and "locked out" are
    different states. `st.stop()` on every path that has not yet produced a principal.
    """
    if not identity.configured():
        return None
    who = st.session_state.get("principal")
    if isinstance(who, identity.Principal):
        return who
    flow = identity.build()
    code = st.query_params.get("code")
    if code:
        try:
            who = flow.redeem(code)
        except identity.SignInError as bad:
            st.error(f"Sign-in failed: {bad}")
            st.stop()
        st.session_state["principal"] = who
        st.query_params.clear()        # the code is single-use; leaving it on the URL re-redeems it
        st.rerun()
    st.title("Architecture Review")
    st.link_button("Sign in with Microsoft", flow.login_url(state="review"), type="primary")
    st.stop()


def main():
    _announce_build()
    st.set_page_config(page_title="Architecture Review", page_icon="🏛️", layout="wide")
    who = _principal()
    if who is None:
        if config.REVIEW_APP_PASSWORD:  # the fallback gate, for a deployment with no SSO configured
            if st.session_state.get("authed") is not True:
                pw = st.text_input("Review app password", type="password")
                if pw == config.REVIEW_APP_PASSWORD:
                    st.session_state["authed"] = True; st.rerun()
                st.stop()
        # the audit log answers "who released this EA-repository write", so the reviewer is never
        # blank — and on this path it is still self-asserted, which is what SSO exists to end
        reviewer = st.sidebar.text_input("Reviewer", value=os.environ.get("USER", "reviewer")).strip()
        if not reviewer:
            st.sidebar.warning("Enter your name to decide — an approval must carry the human who made it.")
        offered = list(PAGES)
    else:
        reviewer = who.actor
        st.sidebar.caption(f"**{who.name or reviewer}**  \n{reviewer}")
        offered = pages_for(who)
        if not offered:
            st.warning(f"You are signed in as {reviewer} but hold no role in this app, so there is "
                       f"nothing here yet. Ask for one of {', '.join(identity.ROLES)} — it is "
                       f"granted in Entra, under Enterprise applications -> lab-review-app.")
            st.stop()
    mode = st.sidebar.radio("Mode", offered, horizontal=True)
    if who is not None and not may_open(who, mode):      # not merely hidden
        st.error(f"{reviewer} may not open {mode}."); st.stop()
    PAGES[mode][0](reviewer)


if __name__ == "__main__":
    main()
