"""src/lab/substrate/review/app.py main(): page config, the password gate (REVIEW_APP_PASSWORD), the sidebar
reviewer/mode widgets and the PAGES dispatch table — run under the fake streamlit harness of
tests/unit/substrate/review/test_app_pages.py. Offline.
Run: .venv/bin/python tests/unit/substrate/review/test_app_main.py   (also pytest-compatible)"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from fixtures.streamlit import APP, FakeSt, FakeWorkflows, Rerun, Stop, install  # noqa: E402


def _main(st, password=None):
    install(st)
    APP.config = SimpleNamespace(REVIEW_APP_PASSWORD=password)
    APP.main()
    return st


def test_main_without_password_dispatches_the_chosen_mode():
    os.environ["USER"] = "socrates"
    st = _main(FakeSt(Mode="Runs"))
    assert st.calls[0][0] == "set_page_config" and st.calls[0][2]["layout"] == "wide"
    assert ("sidebar.text_input", ("Reviewer",), {"value": "socrates"}) in st.calls
    assert st.said("radio", "Mode ['Review', 'Submit', 'Runs']")
    assert st.said("title", "Runs") and not any(path == "text_input" for path, _, _ in st.calls)  # no gate
    # default mode = first entry of PAGES = Review; Submit reaches the Submit page with the reviewer name
    st = _main(FakeSt())
    assert st.said("title", "Architecture Review")
    wf = FakeWorkflows()
    st = FakeSt(Mode="Submit", Reviewer="ann", **{"▶️ Run visio_to_archimate": True})
    install(st, workflows=wf)
    APP.config = SimpleNamespace(REVIEW_APP_PASSWORD=None)
    st.session_state["submit_refs"] = {"diagram": "art://d/s.vsdx", "requirements": []}
    try:
        APP.main()
        raise AssertionError("Run must rerun")
    except Rerun:
        pass
    assert wf.requests == [("visio_to_archimate", {"diagram": "art://d/s.vsdx", "requirements": []}, "ann")]


def test_password_gate_blocks_wrong_or_empty_password():
    for given in ("", "wrong"):
        st = FakeSt(**{"Review app password": given})
        try:
            _main(st, password="s3cret")
            raise AssertionError("st.stop() expected")
        except Stop:
            pass
        assert st.session_state.get("authed") is not True
        assert ("text_input", ("Review app password",), {"type": "password"}) in st.calls
        assert st.count("title") == 0 and st.count("radio") == 0


def test_password_gate_accepts_then_reruns_and_authed_session_passes_through():
    st = FakeSt(**{"Review app password": "s3cret"})
    try:
        _main(st, password="s3cret")
        raise AssertionError("a correct password reruns the script")
    except Rerun:
        pass
    assert st.session_state["authed"] is True and st.count("title") == 0
    st = FakeSt(Mode="Runs")
    st.session_state["authed"] = True
    _main(st, password="s3cret")
    assert not any(path == "text_input" for path, _, _ in st.calls) and st.said("title", "Runs")


def test_streamlit_entry_point_runs_main():
    """Streamlit executes src/lab/substrate/review/app.py as __main__: main() runs with the real shared modules
    swapped for fakes on the `shared` package (no Redis)."""
    import runpy
    import lab.platform
    shared = lab.platform   # the app rebinds lab.platform.runlog / .config below
    from fixtures.streamlit import FakeRunlog
    fake_st = FakeSt(Mode="Runs")
    saved = {k: getattr(shared, k) for k in ("runlog", "config")}
    real_st = sys.modules.get("streamlit")
    sys.modules["streamlit"] = fake_st
    lab.platform.runlog = FakeRunlog()
    lab.platform.config = SimpleNamespace(REVIEW_APP_PASSWORD=None, JAEGER_UI_URL="http://jaeger.test/")
    try:
        runpy.run_path(os.path.join(ROOT, "src", "lab", "substrate", "review", "app.py"), run_name="__main__")
    finally:
        for k, v in saved.items():
            setattr(shared, k, v)
        if real_st is not None:
            sys.modules["streamlit"] = real_st
        else:
            del sys.modules["streamlit"]
    names = [c[0] for c in fake_st.calls]
    assert names[:2] == ["fragment", "fragment"] and "set_page_config" in names    # module load, then main()
    assert fake_st.said("title", "Runs")
    assert fake_st.said("info", "No runs recorded yet")


def test_pages_table_is_the_only_dispatch():
    assert list(APP.PAGES) == ["Review", "Submit", "Runs"]
    assert APP.PAGES["Review"] is APP._review_page and APP.PAGES["Submit"] is APP._submit_page
    assert APP.PAGES["Runs"] is APP._runs_page


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
