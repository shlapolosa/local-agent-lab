"""Opening one artifact by ref — the other end of the live page's link.

The live view holds no store credential and never will, so it hands out a link and the review app
serves the bytes: it already reads the store, and it already authenticates the person first. That
split is the whole reason the link exists rather than a download button on the watcher.
"""
from fixtures.streamlit import APP, FakeSt, FakeStore, install


def _downloads(st):
    return [k for path, a, k in st.calls if path.endswith("download_button")]


def _warned(st):
    return [a for path, a, k in st.calls if path.endswith("warning")]


def test_a_ref_on_the_url_is_offered_as_a_download():
    st = install(FakeSt(), store=FakeStore({"art://abc/screening.json": b"{}"}))
    APP._artifact_download("art://abc/screening.json")
    assert [d["file_name"] for d in _downloads(st)] == ["screening.json"]


def test_an_artifact_that_has_expired_says_so_instead_of_breaking_the_page():
    """A run's artifacts outlive the run log by a different clock. A reader following an old link
    must be told, not shown a stack trace."""
    st = install(FakeSt(), store=FakeStore())          # the ref is simply not there
    APP._artifact_download("art://abc/screening.json")
    assert _warned(st) and not _downloads(st)


def test_a_malformed_ref_is_refused_before_the_store_is_touched():
    st = install(FakeSt(), store=FakeStore())
    APP._artifact_download("not-a-ref")
    assert _warned(st) and not _downloads(st)


def test_no_ref_renders_nothing_at_all():
    st = install(FakeSt(), store=FakeStore())
    APP._artifact_download("")
    assert not _downloads(st) and not _warned(st)


def test_the_runs_page_opens_whatever_ref_the_url_named():
    """The link the live page emits is `?mode=Runs&artifact=<ref>`, so the Runs page is where it
    lands and the download must be offered there without any further click."""
    st = install(FakeSt(query_params={"mode": "Runs", "artifact": "art://abc/screening.json"}),
                 store=FakeStore({"art://abc/screening.json": b"{}"}))
    APP._runs_page(None)
    assert [d["file_name"] for d in _downloads(st)] == ["screening.json"]
