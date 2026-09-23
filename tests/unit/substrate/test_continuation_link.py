"""The handover writes the link that lets one page follow it.

Without it, a run that releases another simply stops on the only surface a person has, and an
approval they just gave looks like it did nothing (measured 23 Sep 2026). The link is written
HERE, where the handover actually happens and where both ends are known — the parent's trace from
the approval, the child's id from the submit that just returned.

Best effort, deliberately: the release has already happened by this point. A run log that could
not be written must not undo a submitted continuation — losing the run would be a far worse
outcome than losing the link to it.
"""
from fixtures.fakes import FakeRedis
from lab.platform import runlog
from lab.substrate import continuations


def test_the_parent_run_learns_where_the_work_went():
    redis = FakeRedis()
    runlog.start("trace-parent", process="use_case_screening", input="x", client=redis)
    continuations.link_runs("trace-parent", "wfr-child", "use_case_design", client=redis)
    h = runlog.get("trace-parent", client=redis)
    assert h["continued_as"] == "wfr-child" and h["continued_process"] == "use_case_design"


def test_an_approval_with_no_trace_links_nothing_rather_than_guessing():
    """An approval raised outside a run has no parent to link. Writing to an empty key would
    create a run-log row for a run that does not exist."""
    redis = FakeRedis()
    continuations.link_runs("", "wfr-child", "use_case_design", client=redis)
    assert runlog.get("", client=redis) in ({}, None)


def test_a_run_log_that_refuses_does_not_undo_the_continuation():
    class Broken(FakeRedis):
        def hset(self, *a, **k):
            raise RuntimeError("redis down")
    continuations.link_runs("trace-parent", "wfr-child", "use_case_design", client=Broken())
