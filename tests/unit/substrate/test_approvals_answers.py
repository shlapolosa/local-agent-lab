"""Threading a human's ANSWER back through the gate, and the decisions-stream consumer groups that
let something act on it.

Today a decision carries approve/decline/update, an actor, a channel and a comment — enough to
RELEASE a staged write, not enough to ANSWER a question. These tests pin the addition and, more
importantly, pin that it changes nothing for the approvals that ask nothing, which is all of them
so far.

Offline: a fake Redis, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_approvals_answers.py
"""
import json

import pytest

from fixtures.fakes import FakeRedis
from lab.platform.contracts import ApprovalKind, Continuation, Decision
from lab.substrate import approvals

QUESTION = {"question": {"prompt": "Who is each speaker?",
                         "items": [{"label": "SPEAKER_00"}, {"label": "SPEAKER_01"}]},
            "answer_labels": ["SPEAKER_00", "SPEAKER_01"], "answer_required": True}
ANSWER = {"SPEAKER_00": {"identity": "maria@contoso.com"}, "SPEAKER_01": {"tag": "guest"}}


@pytest.fixture
def r():
    return FakeRedis()


def _ask(r, payload=None):
    return approvals.request(kind=ApprovalKind.SPEAKER_MAPPING.value, subject="weekly sync",
                             payload=payload if payload is not None else QUESTION,
                             requester="wf-meeting", client=r)


# ------------------------------------------------------------------ the answer travels
def test_a_human_decision_carries_a_structured_answer_onto_the_request():
    r = FakeRedis()
    rid = _ask(r)
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app",
                             answer=ANSWER, client=r)
    st = approvals.status(rid, client=r)
    assert st["status"] == "approve" and st["answer"] == ANSWER


def test_the_answer_is_also_on_the_audit_log_not_only_the_current_state():
    """The request hash is current state and can be overwritten; the decisions stream is the record
    of what a named person actually said, which is the whole point of the gate."""
    r = FakeRedis()
    rid = _ask(r)
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "teams", answer=ANSWER, client=r)
    entries = r.xrange(approvals.DEC)
    assert json.loads(entries[-1][1]["answer"]) == ANSWER
    assert entries[-1][1]["actor"] == "maria@contoso.com"


def test_an_incomplete_answer_is_refused_and_the_request_stays_open():
    """And — the subtle part — the atomic claim on the pending set must NOT be burned by a refusal,
    or one bad submission would lock everyone else out of answering."""
    r = FakeRedis()
    rid = _ask(r)
    with pytest.raises(ValueError):
        approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app",
                                 answer={"SPEAKER_00": {"tag": "x"}}, client=r)
    assert approvals.status(rid, client=r)["status"] == "pending"
    assert rid in r.smembers("approvals:pending"), "the claim must survive a rejected answer"
    # and the same person can now answer properly
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app",
                             answer=ANSWER, client=r)
    assert approvals.status(rid, client=r)["status"] == "approve"


def test_an_approval_that_asks_a_question_cannot_be_approved_without_answering_it():
    r = FakeRedis()
    rid = _ask(r)
    with pytest.raises(ValueError):
        approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "telegram", client=r)


def test_asking_for_changes_needs_no_answer_either():
    """`update` is "changes requested" — a reviewer saying the question is wrong, or that they cannot
    tell two voices apart. Forcing them to invent a complete answer first would make the only honest
    response unavailable, and the request stays open for a real answer later."""
    r = FakeRedis()
    rid = _ask(r)
    approvals.human_decision(rid, Decision.UPDATE, "maria@contoso.com", "review-app",
                             comment="speakers 2 and 3 sound identical", client=r)
    assert approvals.status(rid, client=r)["status"] == "update"
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app",
                             answer=ANSWER, client=r)
    assert approvals.status(rid, client=r)["answer"] == ANSWER


def test_declining_a_question_needs_no_answer():
    """Declining is refusing to answer, which is a legitimate outcome and must not be blocked."""
    r = FakeRedis()
    rid = _ask(r)
    approvals.human_decision(rid, Decision.DECLINE, "maria@contoso.com", "review-app",
                             comment="cannot identify these voices", client=r)
    assert approvals.status(rid, client=r)["status"] == "decline"


def test_every_existing_approval_is_unaffected():
    """The whole change must be invisible to the approvals that ask nothing — which is all of them
    until a meeting run stages one."""
    r = FakeRedis()
    rid = approvals.request(kind=ApprovalKind.EA_IMPORT.value, subject="lab model",
                            payload={"summary": {"elements": 3}}, requester="architect", client=r)
    fields = approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app", client=r)
    assert fields["decision"] == "approve"
    assert approvals.status(rid, client=r).get("answer") in (None, {}, "")


def test_an_answer_to_an_approval_that_asked_nothing_is_refused():
    r = FakeRedis()
    rid = approvals.request(kind=ApprovalKind.EA_IMPORT.value, subject="lab model",
                            payload={"summary": {}}, requester="architect", client=r)
    with pytest.raises(ValueError):
        approvals.human_decision(rid, Decision.APPROVE, "a@b.com", "review-app",
                                 answer={"anything": {"tag": "x"}}, client=r)


def test_the_raw_recorder_still_records_without_ceremony():
    """`decide()` is the raw append and must stay usable by the one thing that is not a human."""
    r = FakeRedis()
    rid = _ask(r)
    fields = approvals.decide(rid, Decision.APPROVE, "system", "cli", answer=ANSWER, client=r)
    assert json.loads(fields["answer"]) == ANSWER


def test_a_decision_with_no_answer_carries_no_answer_key_at_all():
    """The wire shape of an ordinary decision is UNCHANGED — no empty key in the audit log forever,
    and nothing that already reads a decision sees a new field. This is what makes the addition
    safe to land on a gate that is already in use."""
    r = FakeRedis()
    rid = approvals.request(kind=ApprovalKind.EA_IMPORT.value, subject="lab model",
                            payload={"summary": {}}, requester="architect", client=r)
    fields = approvals.human_decision(rid, Decision.APPROVE, "a@b.com", "review-app", client=r)
    assert "answer" not in fields
    assert "answer" not in r.hgetall(f"approvals:req:{rid}")


# ------------------------------------------------------------------ acting on a decision
def test_the_decisions_stream_has_its_own_consumer_groups():
    """The request stream feeds humans; the DECISIONS stream is where something acts on what they
    said. It needs its own groups, and nothing consumed it before now."""
    r = FakeRedis()
    approvals.ensure_decision_groups(r)
    assert approvals.DEC_GROUPS, "at least one consumer of decisions must be declared"
    approvals.ensure_decision_groups(r)          # idempotent, like the request-side groups


def test_a_decision_is_delivered_once_and_acked():
    r = FakeRedis()
    group = approvals.DEC_GROUPS[0]
    approvals.ensure_decision_groups(r)
    rid = _ask(r)
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app",
                             answer=ANSWER, client=r)
    got = list(approvals.decision_events(group, block_ms=0, client=r))
    assert [f["request_id"] for _, f in got] == [rid]
    for eid, _ in got:
        approvals.ack_decision(group, eid, client=r)
    assert list(approvals.decision_events(group, block_ms=0, client=r)) == []


def test_a_continuation_rides_on_the_payload_and_survives_the_round_trip():
    """What approving releases is written by the run that asked, and read back by whatever acts."""
    r = FakeRedis()
    cont = Continuation(process="visio_to_archimate", inputs={"diagram": "art://a/b.vsdx"},
                        requester="maria@contoso.com")
    rid = _ask(r, payload=QUESTION | {"continuation": cont.to_dict()})
    from lab.platform.contracts import continuation_of
    assert continuation_of(approvals.status(rid, client=r)["payload"]) == cont


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
