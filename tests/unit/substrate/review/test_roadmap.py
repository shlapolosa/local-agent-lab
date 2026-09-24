"""The run as a vertical roadmap — the published methodology, with this run's state on it.

The runs page drew a Mermaid graph of EXECUTORS (readiness, feasibility, derive_design), which
answers "which node" when an SME is asking "which step". The nineteen published process steps are
what a person recognises, every one already declaring its inputs, its decision and its outputs — and
the run log already records each as `step_<n>`, start to done or fail, with elapsed and error.

So this joins three things that exist and invents none of them. Pure: no Streamlit, no Redis, no
Jaeger — a roadmap is a projection, and a projection is testable.
"""
from lab.core.usecase import seed
from lab.substrate.review import roadmap

#: The index the app reads from the corpus, here read from the same rows the publisher publishes.
_KEYS = seed.artifact("process_step_keys")["step_keys"]
INDEX = roadmap.index_from(_KEYS["rows"], _KEYS["headers"])
ORDER = roadmap.order_from(_KEYS["rows"], _KEYS["headers"])

PUBLISHED = [
    ["E0.1 Frame the use case Pre-work", "—", "No decision. Records the problem", "Use case record"],
    ["E0.2 Decompose Pre-work", "Use case record", "No decision. Separates elements", "Element inventory"],
    ["E0.3 Match capabilities Pre-work", "Element inventory; map", "No decision. A gap means", "Coverage map"],
    ["Q0.8–Q0.9 Readiness verdict Gate", "All of the above", "GATE. Pass, conditional or fail", "Verdict"],
]
HEADERS = ["Step", "Input artifacts", "What is decided", "Output artifacts"]


def _build(nodes=(), record=None, activity=(), published=None):
    return roadmap.build(published if published is not None else PUBLISHED, HEADERS, INDEX,
                         nodes=list(nodes), record=record or {}, activity=list(activity))


# ---------------------------------------------------------------- what a row IS


def test_a_row_carries_the_published_input_decision_and_output():
    """The three columns are the framework's own words. A roadmap that paraphrased them would be a
    second description of the methodology, drifting from the one that is published."""
    step = _build()[0]
    assert step.title == "Frame the use case"
    assert step.decided.startswith("No decision")
    assert step.outputs_declared == "Use case record"


def test_the_kind_is_read_off_the_step_and_a_gate_is_distinguishable():
    """A Gate is where a person acts; Pre-work is where they only look. The roadmap has to tell
    them apart to know where to put a decision."""
    kinds = {s.id: s.kind for s in _build()}
    assert kinds["E0.1"] == "Pre-work" and kinds["Q0.8–Q0.9"] == "Gate"


def test_a_step_names_the_agent_that_performs_it():
    """`Step.service` — so a reviewer sees WHO produced an answer. Ten roles across seventeen agent
    steps, and the distinction matters when judging an answer's authority."""
    assert _build()[2].agent == "Business Architect"      # E0.3 -> step 5 -> coverage_map


def test_a_derived_step_says_so_rather_than_naming_an_agent():
    """Steps 18, 19 and 22 are computed, not asked. "Derived, not asked" tells a reviewer no model
    formed that answer — a stronger statement about it than any agent's name."""
    rows = [["Q3.1–Q3.4 Derive obligations Gate", "Facet vectors", "No discretion", "Obligations"]]
    step = roadmap.build(rows, HEADERS, INDEX)[0]
    assert step.agent == "" and step.derived is True and step.keys == ("obligations",)


def test_the_index_is_injected_so_the_substrate_never_imports_a_workload():
    """`Step.service` lives in `lab.workloads.usecase.steps`, and `substrate` may not import
    `workloads` — the seam that keeps a workload reachable only over the network. So the join is
    derived into a published artifact and read from the corpus like any other reference."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(roadmap))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith("lab.workloads") for m in imported), sorted(imported)
    assert roadmap.build(PUBLISHED, HEADERS, None)[2].agent == "", "no index -> no claim"


# ---------------------------------------------------------------- this run's state


def test_state_comes_from_the_run_log_and_an_unstarted_step_is_pending():
    nodes = [{"name": "step_3", "status": "done", "t": 1.0, "attrs": {"elapsed": 2.5}},
             {"name": "step_4", "status": "start", "t": 4.0, "attrs": {}}]
    got = {s.id: s.state for s in _build(nodes=nodes)}
    assert got["E0.1"] == "done" and got["E0.2"] == "running" and got["E0.3"] == "pending"


def test_a_failed_step_carries_its_error_because_that_is_what_a_person_opens_it_for():
    nodes = [{"name": "step_3", "status": "fail", "t": 1.0, "attrs": {"error": "the gate refused"}}]
    step = _build(nodes=nodes)[0]
    assert step.state == "failed" and "gate refused" in step.error


def test_a_defaulted_step_is_neither_done_nor_pending():
    """A declared default is an answer nobody derived. Showing it as `done` would hide the
    assumption; showing it as `pending` would claim the run is unfinished. It is its own state."""
    record = {"defaulted_steps": {"5": "capabilities is not published"}}
    step = {s.id: s for s in _build(record=record)}["E0.3"]
    assert step.state == "defaulted" and "not published" in step.note


def test_the_output_is_the_records_own_section_for_that_step():
    record = {"frame": {"problem": "referrals take too long"}}
    assert _build(record=record)[0].output == {"problem": "referrals take too long"}


def test_gaps_gather_what_the_step_itself_flagged():
    record = {"coverage_map": {"matched": [], "gap_flags": [{"what": "no map is published"}]}}
    step = {s.id: s for s in _build(record=record)}["E0.3"]
    assert any("no map is published" in g for g in step.gaps)


def test_cost_and_model_come_from_the_trace_activity_for_that_step():
    """So a reviewer reads what an answer cost beside the answer, not in another tool."""
    class _A:
        node = "step_5"
        llm = [type("L", (), {"model": "kimi-k3", "seconds": 4.0, "input_tokens": 100,
                              "output_tokens": 20, "cost": 0.01})()]
        tools, errors = [], []
    step = {s.id: s for s in _build(activity=[_A()])}["E0.3"]
    assert step.model == "kimi-k3" and step.tokens == 120 and step.cost == 0.01


# ---------------------------------------------------------------- degrading honestly


def test_no_published_steps_yields_no_roadmap_rather_than_an_invented_one():
    """The methodology is a published artifact. If it cannot be read, the page says so — it does not
    fall back to a list in code, which would be the one thing this design refuses."""
    assert _build(published=[]) == []


def test_a_run_with_no_node_timeline_still_renders_every_step_as_pending():
    """A run whose log expired (7-day TTL) or that never started: the shape of the process is still
    worth showing, and every step honestly reads pending."""
    assert {s.state for s in _build()} == {"pending"}


def test_an_unknown_node_status_does_not_break_the_roadmap():
    """`_node_states` raises KeyError on a status outside start/done/fail. A roadmap that dies
    because a host recorded something new is worse than one that shows an unknown step as running."""
    assert _build(nodes=[{"name": "step_3", "status": "surprise", "t": 1.0}])[0].state == "running"


def test_the_roadmap_is_in_PROCESS_order_whatever_order_the_corpus_returned():
    """A corpus lookup returns records in no particular order — measured on the running app, which
    rendered Q1.1, E0.3, E0.10, E0.4. A roadmap out of process order is a list, and lexical sorting
    cannot rescue it because "E0.10" precedes "E0.2"."""
    shuffled = [PUBLISHED[3], PUBLISHED[1], PUBLISHED[2], PUBLISHED[0]]
    got = [s.id for s in roadmap.build(shuffled, HEADERS, INDEX, order=ORDER)]
    assert got == ["E0.1", "E0.2", "E0.3", "Q0.8–Q0.9"]


def test_without_an_order_the_artifacts_own_row_order_stands():
    """Honest rather than arbitrary: a caller that already has them in order keeps it, and one that
    does not is not given a fabricated sequence."""
    shuffled = [PUBLISHED[3], PUBLISHED[0]]
    assert [s.id for s in roadmap.build(shuffled, HEADERS, INDEX)] == ["Q0.8–Q0.9", "E0.1"]


# ---------------------------------------------------------------- actuals, not the methodology


def test_a_step_reports_what_it_was_actually_SHOWN_not_the_published_prose():
    """The three columns were all published text, identical on every run, so a reviewer read the
    methodology back rather than their own run. `Reads` names the record sections the agent is
    given (`agents.CONTEXT_FOR`, published as data because substrate may not import workloads), so
    the roadmap can resolve the real input from the record."""
    record = {"frame": {"problem": "referrals take too long"},
              "elements": {"functions": ["triage"]}}
    step = {s.id: s for s in _build(record=record)}["E0.2"]     # E0.2 reads `frame`
    assert step.reads == ("frame",)
    assert step.input == {"frame": {"problem": "referrals take too long"}}


def test_a_section_the_record_does_not_carry_is_simply_absent_not_invented():
    """`capabilities` is a CORPUS read, not a record section — it is named in Reads but never
    lands in the record. Showing it as empty would imply the agent saw nothing; omitting it is
    honest about what the record can account for."""
    step = {s.id: s for s in _build(record={"elements": {"a": 1}})}["E0.3"]
    assert step.reads == ("elements", "capabilities")
    assert step.input == {"elements": {"a": 1}}


def test_a_step_with_no_declared_reads_has_no_actual_input():
    assert _build()[0].input is None


def test_the_output_is_still_the_records_own_section():
    """Unchanged — `output` was always the actual. It was invisible only because the record itself
    arrived at the very end of the run."""
    assert _build(record={"frame": {"problem": "x"}})[0].output == {"problem": "x"}


# ---------------------------------------------------------------- one process, not the whole book


def test_a_roadmap_shows_only_the_steps_the_running_process_implements():
    """Screening implements E0.1-E0.10 and the readiness gate; everything from Q1.1 down belongs to
    design, investment and provisioning — separate processes, separate runs. Drawing all nineteen
    made a COMPLETED screening look half-finished, with ten rows permanently pending."""
    rows = PUBLISHED + [["Q1.1–Q1.5 Decide determinism Decision", "x", "y", "z"]]
    got = [s.id for s in roadmap.build(rows, HEADERS, INDEX, process="screening")]
    assert "Q1.1–Q1.5" not in got
    assert got == ["E0.1", "E0.2", "E0.3", "Q0.8–Q0.9"]


def test_the_gate_belongs_to_screening_because_it_is_what_closes_it():
    assert "Q0.8–Q0.9" in [s.id for s in roadmap.build(PUBLISHED, HEADERS, INDEX,
                                                       process="screening")]


def test_no_process_named_means_the_whole_methodology_as_before():
    """A caller that does not know which process it is looking at gets everything, which is the
    old behaviour and the honest default."""
    assert len(roadmap.build(PUBLISHED, HEADERS, INDEX)) == len(PUBLISHED)


def test_an_index_without_the_process_column_does_not_filter_everything_away():
    """An app running against a corpus published before this column existed must still draw a
    roadmap — degrade to showing all steps, never to showing none."""
    old = roadmap.index_from([r[:6] for r in _KEYS["rows"]], _KEYS["headers"][:6])
    assert len(roadmap.build(PUBLISHED, HEADERS, old, process="screening")) == len(PUBLISHED)
