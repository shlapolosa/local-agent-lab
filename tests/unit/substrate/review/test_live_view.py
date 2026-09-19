"""The Runs page updates itself while a run is going, and costs nothing while nothing changes.

Two separate defects sat behind "the UI does not update": the auto-rerun mechanism, and what a
rerun COSTS. `st.fragment(run_every=…)` has known upstream defects (streamlit#9080, #11660) and
could not be verified from here without a browser, so the page no longer depends on it. And every
tick re-read ~21 Redis keys, re-downloaded the record from the artifact store, and re-rendered every
expander — which is why it felt bad even when it did fire.
"""
from lab.substrate.review import app


# ---------------------------------------------------------------- when to refresh at all


def test_a_finished_run_stops_refreshing():
    """Nothing will change again. A page that keeps reloading a finished run is spending a
    round trip a second to redraw the same thing, and stealing the scroll position while it does."""
    assert app._should_refresh({"status": "done"}) is False
    assert app._should_refresh({"status": "failed"}) is False


def test_a_run_still_going_refreshes():
    assert app._should_refresh({"status": "running"}) is True
    assert app._should_refresh({"status": "pending"}) is True


def test_an_unknown_status_refreshes_rather_than_freezing():
    """A host that records something new must not leave the page permanently stale — the failure
    that cannot be noticed is worse than one extra reload."""
    assert app._should_refresh({"status": "surprise"}) is True
    assert app._should_refresh({}) is True


# ---------------------------------------------------------------- what counts as a change


def test_the_token_moves_when_the_run_moves():
    a = {"status": "running", "node": "step_3", "nodes": [1, 2, 3], "record_ref": "art://a/x.json"}
    assert app._change_token(a) != app._change_token({**a, "node": "step_4"})
    assert app._change_token(a) != app._change_token({**a, "nodes": [1, 2, 3, 4]})
    assert app._change_token(a) != app._change_token({**a, "status": "done"})
    assert app._change_token(a) != app._change_token({**a, "record_ref": "art://a/y.json"})


def test_the_token_ignores_what_only_looks_like_change():
    """`elapsed` is recomputed live on every read for a running run, so including it would make
    every tick a change and defeat the whole point."""
    a = {"status": "running", "node": "step_3", "nodes": [1], "elapsed": 12.0}
    assert app._change_token(a) == app._change_token({**a, "elapsed": 13.5})


# ---------------------------------------------------------------- what a tick costs


def test_the_record_is_fetched_once_per_ref_not_once_per_tick():
    """The record moved from "written once at the end" to "republished after every step", so a
    5-second tick now re-downloads it from the artifact store each time. Cached on the REF, which
    changes exactly when the record does."""
    calls = []

    class _Store:
        def get(self, ref):
            calls.append(ref)
            return b'{"frame": {"problem": "x"}}'

    state = {}
    h = {"record_ref": "art://a/partial.json"}
    for _ in range(4):
        app._record_cached(h, store=_Store(), cache=state)
    assert calls == ["art://a/partial.json"], "one fetch for four reads of the same ref"
    app._record_cached({"record_ref": "art://a/next.json"}, store=_Store(), cache=state)
    assert len(calls) == 2, "a new ref is a new fetch"


def test_a_record_that_cannot_be_read_is_an_empty_record_not_a_broken_page():
    class _Boom:
        def get(self, ref):
            raise KeyError(ref)

    assert app._record_cached({"record_ref": "art://gone/x.json"}, store=_Boom(), cache={}) == {}


def test_no_ref_means_no_fetch_at_all():
    class _Never:
        def get(self, ref):
            raise AssertionError("must not be called")

    assert app._record_cached({}, store=_Never(), cache={}) == {}


# ---------------------------------------------------------------- surviving a page reload

def test_the_cache_outlives_a_session_because_a_reload_starts_a_new_one():
    """The refresh mechanism is a page RELOAD, and a reload begins a fresh Streamlit session with
    empty `st.session_state`. Every cache kept there is therefore thrown away three seconds after
    it is filled — which defeats the point of having it, and for the corpus means taking a NEW
    reference PIN on every reload, writing a `ref_consumption` row every three seconds for a page
    nobody is reading.

    So the cache is process-global: the Streamlit server outlives the sessions connected to it."""
    calls = []
    app._CACHE.clear()
    for _ in range(3):
        assert app._cached("k", 60, lambda: calls.append(1) or "v") == "v"
    assert calls == [1], "produced once across three separate reads"


def test_an_expired_entry_is_produced_again():
    calls = []
    app._CACHE.clear()
    app._cached("k", 0, lambda: calls.append(1) or "v")
    app._cached("k", 0, lambda: calls.append(1) or "v")
    assert len(calls) == 2, "ttl 0 means never reuse"


def test_different_keys_do_not_share_an_entry():
    app._CACHE.clear()
    assert app._cached("a", 60, lambda: "A") == "A"
    assert app._cached("b", 60, lambda: "B") == "B"


def test_the_cache_is_bounded_so_a_long_lived_server_cannot_grow_without_limit():
    """One entry per (artifact, run, ref) and the server runs for weeks. Unbounded, it is a slow
    leak nobody attributes to a cache."""
    app._CACHE.clear()
    for i in range(app._CACHE_MAX + 25):
        app._cached(f"k{i}", 60, lambda i=i: i)
    assert len(app._CACHE) <= app._CACHE_MAX


# ---------------------------------------------------------------- the page survives a reload

def test_the_open_page_is_remembered_in_the_url():
    """A reload starts a NEW session, so a sidebar radio with no key resets to its first option —
    which is `Review`. The Runs page therefore threw the reader back to Review every three seconds
    and was, in their words, completely unusable.

    The URL is the only thing that survives a reload, so the open page lives there. It also makes
    a page linkable, which is what somebody wants when they say "look at the Runs board"."""
    assert app._mode_from({"mode": "Runs"}, ["Review", "Submit", "Runs"]) == "Runs"


def test_an_unknown_or_forbidden_page_in_the_url_falls_back_rather_than_failing():
    """A stale link, or a page this principal's roles do not reach. Neither is an error worth a
    stack trace — the offered list is the authority and the first entry is the safe default."""
    assert app._mode_from({"mode": "Artifacts"}, ["Review", "Runs"]) == "Review"
    assert app._mode_from({"mode": "nonsense"}, ["Review", "Runs"]) == "Review"
    assert app._mode_from({}, ["Review", "Runs"]) == "Review"


def test_no_pages_offered_is_not_a_crash():
    assert app._mode_from({"mode": "Runs"}, []) == ""
