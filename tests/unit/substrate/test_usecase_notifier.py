"""The use-case notifier — what makes FR-12's ordering structural rather than a convention.

The requirement is that an architect sees a rejection BEFORE the submitter does. A workload cannot
guarantee that on its own: it ends at the question, and the decision comes later on somebody else's
schedule. So the architect's decision is the EVENT that releases the message, and there is no code
path that could send one first.
"""
import pytest

from fixtures.fakes import FakeRedis, patched_client
from lab.platform.contracts import USE_CASE_SCREENING, Decision
from lab.substrate import approvals, usecase_notifier as N


@pytest.fixture
def redis():
    fake = FakeRedis()
    with patched_client(fake):
        yield fake


def _raise(redis, *, subject="Confirm the criticality class of a submitted use case",
           requester="ba@x.ae", process=USE_CASE_SCREENING.name):
    """As `approvals_ask` raises one: the process is DECLARED on the payload, not inferred."""
    return approvals.request(kind="usecase", subject=subject, payload={"process": process},
                             requester=requester, trace_id="t" * 32, client=redis)


def _decide(redis, rid, decision=Decision.DECLINE):
    approvals.human_decision(rid, decision, "architect@x.ae", "review-app", comment="no",
                             client=redis)
    return [f for _, f in approvals.decision_events(N.GROUP, client=redis)]


# ---------------------------------------------------------------- the ordering

def test_nothing_is_announced_before_a_decision_exists(redis):
    """The whole requirement. An approval that is still open produces no message at all — and it
    cannot, because the only thing this service reads is the decisions stream."""
    _raise(redis)
    assert approvals.decision_events(N.GROUP, client=redis) == []


def test_a_decision_releases_the_submitters_message(redis, capsys):
    rid = _raise(redis)
    fields = _decide(redis, rid)
    assert fields, "the decision reached the stream"
    assert N.handle(fields[0], client=redis) is True
    assert "ba@x.ae" in capsys.readouterr().out


def test_the_message_says_the_outcome_and_not_the_reasoning(redis):
    """OA-1 wants an architect to SEE every rejection. It does not want their private assessment
    forwarded to the person whose submission it was, and CR-16 is the reason: the submitter is a
    different audience from the reviewer."""
    rid = _raise(redis)
    fields = _decide(redis, rid)
    said = N.payload(approvals.status(rid, client=redis), fields[0])
    assert said["outcome"] == "not proceeding"
    assert "no" not in said.values(), "the architect's comment must not travel"
    assert not any("comment" in k for k in said)


def test_the_message_carries_ids_a_link_and_nothing_else(redis):
    rid = _raise(redis)
    fields = _decide(redis, rid)
    said = N.payload(approvals.status(rid, client=redis), fields[0])
    assert set(said) == {"request_id", "subject", "outcome", "decided_at", "submitter",
                         "review_app"}


@pytest.mark.parametrize("decision,outcome", [
    (Decision.APPROVE, "accepted"),
    (Decision.DECLINE, "not proceeding"),
    (Decision.UPDATE, "returned for changes"),
])
def test_every_decision_has_something_a_submitter_can_act_on(redis, decision, outcome):
    """An `update` is still an OPEN approval, but it is the answer that returns the use case for
    more information — so it is announced too."""
    rid = _raise(redis)
    fields = _decide(redis, rid, decision)
    said = N.payload(approvals.status(rid, client=redis), fields[0])
    assert said["outcome"] == outcome


# ---------------------------------------------------------------- what it stays out of

def test_an_approval_from_another_pipeline_is_not_announced(redis):
    """A channel that announced everything would bury the few messages that matter. A meeting's
    speaker question is not a submitter's business."""
    rid = _raise(redis, subject="meeting recording — who is speaking?",
                 process="meeting_to_transcript")
    fields = _decide(redis, rid)
    assert N.handle(fields[0], client=redis) is False


def test_an_approval_with_nobody_to_tell_is_skipped_rather_than_posted_to_an_empty_address(redis):
    rid = _raise(redis, requester="")
    fields = _decide(redis, rid)
    assert N.handle(fields[0], client=redis) is False


def test_an_unknown_decision_value_is_not_announced(redis):
    assert N.handle({"request_id": "apr-x", "decision": "shrug"}, client=redis) is False


def test_a_request_that_no_longer_exists_is_not_announced(redis):
    assert N.handle({"request_id": "apr-gone", "decision": "approve"}, client=redis) is False


# ---------------------------------------------------------------- delivery is at-least-once

def test_a_failed_send_leaves_the_entry_unacked_so_it_comes_back(redis, monkeypatch):
    """A webhook outage must delay a submitter's message, never drop it — the same bargain the
    meeting notifier makes, and the reason both consume a stream."""
    monkeypatch.setattr(N.config, "USECASE_WEBHOOK_URL", "http://webhook.test/hook")

    def explode(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(N, "post_json", explode)

    rid = _raise(redis)
    approvals.human_decision(rid, Decision.DECLINE, "a@x.ae", "review-app", comment="no",
                             client=redis)
    events = approvals.decision_events(N.GROUP, client=redis)
    with pytest.raises(RuntimeError):
        N._deliver(events[0][0], events[0][1], client=redis)

    # unacked, so a later read brings it back rather than losing the message
    still_pending = approvals.decision_events(N.GROUP, pending_only=True, client=redis)
    assert [f.get("request_id") for _, f in still_pending] == [rid]


def test_a_successful_send_acks_so_a_submitter_is_told_once(redis, monkeypatch):
    posted: list = []
    monkeypatch.setattr(N.config, "USECASE_WEBHOOK_URL", "http://webhook.test/hook")
    monkeypatch.setattr(N, "post_json", lambda url, body: posted.append((url, body)) or "ok")

    rid = _raise(redis)
    approvals.human_decision(rid, Decision.DECLINE, "a@x.ae", "review-app", comment="no",
                             client=redis)
    events = approvals.decision_events(N.GROUP, client=redis)
    N._deliver(events[0][0], events[0][1], client=redis)

    assert posted and posted[0][1]["submitter"] == "ba@x.ae"
    assert approvals.decision_events(N.GROUP, client=redis) == []


def test_with_no_webhook_it_logs_what_it_would_post(redis, capsys):
    """How to watch it before wiring a destination."""
    rid = _raise(redis)
    fields = _decide(redis, rid)
    assert N.handle(fields[0], client=redis) is True
    assert "would post" in capsys.readouterr().out


# ---------------------------------------------------------------- its own consumer group

def test_it_reads_a_group_of_its_own_so_it_cannot_consume_the_continuation_runners_entries():
    assert N.GROUP in approvals.DEC_GROUPS
    assert N.GROUP != "continuations"
