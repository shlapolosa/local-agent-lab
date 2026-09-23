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
