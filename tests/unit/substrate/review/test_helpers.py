"""src/lab/substrate/review/app.py pure helpers — importable without a Streamlit runtime because the page (config,
password gate, sidebar, mode dispatch) lives in main(), run only under `__name__ == "__main__"`
(Streamlit executes the script as __main__). Offline: no Redis, no gateway.
Run: .venv/bin/python tests/unit/substrate/review/test_helpers.py   (also pytest-compatible)"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _load():
    spec = importlib.util.spec_from_file_location("review_app", ROOT / "src" / "lab" / "substrate" / "review" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                 # must NOT touch Redis or st.set_page_config
    return mod


APP = _load()
# the shape agent_framework.WorkflowViz.to_mermaid() emits: one declaration line per node, then edges
MERMAID = ("flowchart TD\n  read_input[\"read input\"]\n  ba[\"BA\"]\n  store[\"store spec\"]\n"
           "  read_input --> ba\n  ba --> store")


def test_dispatch_is_a_table_with_no_legacy_branches():
    assert set(APP.PAGES) == {"Review", "Submit", "Runs"}
    assert all(callable(f) for f in APP.PAGES.values())
    src = (ROOT / "src" / "lab" / "substrate" / "review" / "app.py").read_text()
    assert "xml_path" not in src and '"svgs"' not in src, "legacy local-path branches must be gone"
    assert "def _review_page(" in src and 'if __name__ == "__main__"' in src


def test_node_states_from_timeline():
    h = {"nodes": [{"name": "read_input", "status": "start"}, {"name": "read_input", "status": "done"},
                   {"name": "ba", "status": "start"}]}
    assert APP._node_states(h) == {"read_input": "done", "ba": "running"}
    assert APP._node_states({"nodes": [{"name": "render", "status": "fail"}]}) == {"render": "failed"}
    assert APP._node_states({}) == {}


def test_mermaid_with_state_styles_only_declared_nodes():
    out = APP._mermaid_with_state(MERMAID, {"read_input": "done", "ba": "running", "ghost": "failed"})
    lines = out.splitlines()
    assert lines[:len(MERMAID.splitlines())] == MERMAID.splitlines()
    assert f"  style read_input {APP.NODE_STYLE['done']};" in lines
    assert f"  style ba {APP.NODE_STYLE['running']};" in lines
    assert not any("ghost" in l for l in lines), "unknown node ids must not get a style line"
    assert APP._mermaid_with_state(MERMAID, {}) == MERMAID


def test_fmt_elapsed_and_run_row():
    assert APP._fmt_elapsed(12.4) == "12s" and APP._fmt_elapsed(150) == "2.5m"
    assert APP._fmt_elapsed(None) == "—" and APP._fmt_elapsed("x") == "—"
    row = APP._run_row({"run_id": "r1", "process": "p", "input": "/a/b/diagram.vsdx", "status": "running",
                        "node": "ba", "node_status": "start", "started_at": "2026-09-03T10:00:00Z",
                        "elapsed": 5, "trace_id": "abc"})
    assert row["input"] == "diagram.vsdx" and row["current node"] == "ba (start)"
    assert row["started"] == "2026-09-03 10:00:00" and row["trace"].endswith("/trace/abc")
    assert APP._run_row({})["trace"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL TESTS PASSED")


def test_what_is_still_open_reaches_the_reviewer_before_anything_they_would_have_to_open():
    """A conformance approval used to arrive with an EMPTY summary: twenty-five sections, a question,
    and nothing saying four obligations were bound to no enforcement point. The reviewer then judges
    what reads well rather than what is complete."""
    import types
    shown = []
    fake = types.SimpleNamespace(
        columns=lambda n: [types.SimpleNamespace(metric=lambda label, value: shown.append(("metric", label, value)))
                           for _ in range(n)],
        warning=lambda t: shown.append(("warning", t)),
        success=lambda t: shown.append(("success", t)),
        markdown=lambda t: shown.append(("item", t)),
        caption=lambda t: shown.append(("caption", t)))
    original, APP.st = APP.st, fake
    try:
        APP._still_open({"recommendation": "proceed with conditions", "topology": "T4",
                         "components": 16, "year_one_cost": 254740.0,
                         "owed": ["G04 is required by this design and resolved to NO enforcement point",
                                  "benefit: no effort table was captured at intake"]})
        kinds = [s[0] for s in shown]
        assert "warning" in kinds and kinds.count("item") == 2
        assert "2 thing(s) still open" in next(s[1] for s in shown if s[0] == "warning")
        assert ("metric", "Recommendation", "proceed with conditions") in shown
        assert ("metric", "Year-one cost", "254,740") in shown
        shown.clear()
        APP._still_open({"owed": []})
        assert shown == [("success", "Nothing outstanding: every obligation is bound, every figure computed.")]
        shown.clear()
        APP._still_open({"elements": 12})                 # a model approval: unchanged, says nothing
        assert shown == []
    finally:
        APP.st = original
