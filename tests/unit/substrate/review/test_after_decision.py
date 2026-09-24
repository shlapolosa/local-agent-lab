"""What happens after a decision — the other half of the handover.

Asked three times in one session, in three places: "why is it not progressing", "I approved it
and have no idea what to do next". Each time the answer was that the work had moved somewhere the
person was never told about. A decision that releases a run must SAY which run, and take them
there.

The release is asynchronous — a consumer picks the approval up off a stream — so the released id
appears a moment after the decision, not with it. Waiting a bounded moment for it is the whole
trick; waiting forever, or not at all, are both worse.
"""
from fixtures.streamlit import APP, FakeSt, install


def test_the_released_run_is_reported_once_the_continuation_records_it():
    st = install(FakeSt())
    APP.approvals.released = {"apr-1": ("wfr-next", "use_case_design")}
    got = APP.released_run("apr-1", tries=3, wait=0)
    assert got == ("wfr-next", "use_case_design")


def test_a_decision_that_releases_nothing_reports_nothing_rather_than_waiting():
    """A final approval — or a declined one — releases no run. Blocking the page on a handover
    that is never coming is worse than saying nothing."""
    st = install(FakeSt())
    APP.approvals.released = {}
    assert APP.released_run("apr-1", tries=2, wait=0) == ("", "")


# ---------------------------------------------------- where the handover SENDS the person
def _releasing(monkeypatch, live_url):
    """A pending approval whose approval releases a design run, with LIVE_APP_URL set or not."""
    from fixtures.streamlit import FakeApprovals, _request, _store_for
    monkeypatch.setattr(APP.config, "LIVE_APP_URL", live_url)
    req = _request(request_id="apr-1", subject="Confirm the criticality class of a submitted use case",
                   created_at="2026-09-23T09:00:00+00:00")
    ap = FakeApprovals(items=[req])
    ap.released = {"apr-1": ("wfr-605ea4d76571", "use_case_design")}
    st = install(FakeSt(**{"✅ Approve — release for import": True}),
                 approvals=ap, store=_store_for(req))
    return st


def test_the_handover_sends_the_person_to_the_LIVE_view_of_the_released_run(monkeypatch):
    """The review app renders on the server and cannot update in place; the live view does. A run
    that has just STARTED is watched, not reviewed — so the handover goes to the live service.

    It used to route in-app to `?mode=Runs&run=…`, which is the surface for reading what a run
    PRODUCED. Reported 23 Sep 2026: "after approval we go to review…?mode=Runs&run=… but should
    be to live…/run/…"."""
    from fixtures.streamlit import FakeApprovals, Rerun, _request, _store_for
    st = _releasing(monkeypatch, "https://live-production-6940.up.railway.app")
    try:
        APP._review_page("ann")
        raise AssertionError("a decision must st.rerun()")
    except Rerun:
        pass
    # `_decide` ends by rerunning, so the handover is rendered on the NEXT pass — with the
    # decision recorded and nothing left pending, which is exactly the state a reviewer lands in.
    after = FakeSt()
    after.session_state = st.session_state          # what survives a Streamlit rerun
    install(after, approvals=FakeApprovals(), store=_store_for(_request()))
    APP._review_page("ann")
    wanted = "https://live-production-6940.up.railway.app/run/wfr-605ea4d76571"
    assert any(wanted in str(c) for c in after.calls), \
        f"no link to the live run; calls were {[c[0] for c in after.calls][-12:]}"


def test_with_no_live_view_configured_the_handover_still_works_in_app(monkeypatch):
    """`LIVE_APP_URL` unset is a supported deployment (the role comment says "absent = no link
    offered"), and a handover that vanishes because an optional service is not deployed is worse
    than one that stays on the page it is already on."""
    from fixtures.streamlit import Rerun
    st = _releasing(monkeypatch, "")
    try:
        APP._review_page("ann")
    except Rerun:
        pass
    assert any("wfr-605ea4d76571" in str(c) for c in st.calls), "the released run is still named"
