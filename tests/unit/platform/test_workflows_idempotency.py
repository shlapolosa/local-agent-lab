"""Retrying a submission whose run FAILED.

The claim exists to stop the same work being done twice. A failed run did no work, so honouring its
key for the rest of the TTL makes the submission unretryable — and for a producer whose key is
derived from its input (a flow keyed on the file id), one transient error puts that input out of
reach for a day. Found live: a Power Automate flow resubmitted a failed recording and was handed the
same failure back, with nothing having run.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_workflows_idempotency.py
"""
from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import WorkflowStatus

GOOD = {"owner": "maria@contoso.com", "recording": "collab://item/drive-1/item-9"}
PROC = "meeting_to_transcript"


def _submit(r, key="the-file-id"):
    return workflows.submit(PROC, dict(GOOD), "power-automate", idempotency_key=key, client=r)


def test_a_failed_run_does_not_block_a_retry_on_the_same_key():
    r = FakeRedis()
    first, dup = _submit(r)
    assert dup is False
    workflows.finish(first, WorkflowStatus.FAILED.value, {"error": "transient"}, client=r) \
        if hasattr(workflows, "finish") else r.hset(f"workflow:req:{first}", mapping={"status": "failed"})

    second, dup2 = _submit(r)
    assert dup2 is False, "a failed run protected no work — the key must be reclaimable"
    assert second != first, "and it is a genuinely new run"


def test_a_live_or_finished_run_still_deduplicates():
    """The narrowness is the point: pending and running are live work, and a DONE run is exactly what
    idempotency protects — re-running it would stage a second human approval for an answer that
    already exists."""
    for status in ("pending", "running", WorkflowStatus.DONE.value):
        r = FakeRedis()
        first, _ = _submit(r)
        r.hset(f"workflow:req:{first}", mapping={"status": status})
        again, dup = _submit(r)
        assert (again, dup) == (first, True), f"{status} must still de-duplicate"


def test_a_run_whose_state_vanished_is_reclaimable():
    """A key outliving its run's state protects nothing."""
    r = FakeRedis()
    first, _ = _submit(r)
    r.delete(f"workflow:req:{first}")
    again, dup = _submit(r)
    assert dup is False and again != first


def test_submitting_without_a_key_is_unchanged():
    r = FakeRedis()
    a, dup_a = workflows.submit(PROC, dict(GOOD), "cli", client=r)
    b, dup_b = workflows.submit(PROC, dict(GOOD), "cli", client=r)
    assert a != b and dup_a is False and dup_b is False
