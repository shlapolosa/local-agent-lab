"""Retiring a question nobody is going to answer — `approvals.withdraw`.

A lab that is TESTED leaves open approvals behind: a run raised a question, the test moved on, and
the card sits in the pending set for ever. Measured 9 Sep 2026: twelve open, four of them from runs a
week old, and every one of them announced again by any channel that restarts (`channel_events` reads
its group from `0`, deliberately, so a channel added later still sees what is open).

There was no way to close one. The only closing verbs are a HUMAN'S DECISION — approve, decline —
and using `decline` to tidy up writes a person's name against a judgement they never made, which is
the single thing the audit log exists to prevent ("who released this EA write" is its whole point).

So withdrawal is a THIRD kind of ending, and it is deliberately not a `Decision`:

  * it CLOSES the request — no channel announces it again and nobody can answer it afterwards;
  * it is SOFT — the request, its subject and its payload all survive, and the withdrawal is appended
    to the audit log beside the decisions, so what was asked and why it was retired both stay;
  * it RELEASES NOTHING — `continuations` starts a run on `approve` alone, so a withdrawal cannot
    smuggle in the work an approval would have released.

Offline: a fake Redis, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_approvals_withdraw.py
"""
import pytest

from fixtures.fakes import FakeRedis
from lab.platform.contracts import APPROVAL_FINAL, ApprovalStatus, Decision
from lab.substrate import approvals, continuations

ACTOR = "socrates@contoso.com"


def _asked(r, subject="a stale test run"):
    return approvals.request(kind="speaker-mapping", subject=subject,
                             payload={"question": {"items": [{"label": "SPEAKER_00"}]},
                                      "answer_labels": ["SPEAKER_00"]},
                             requester="tests", client=r)


def test_withdrawing_closes_the_request_without_recording_a_decision():
    r = FakeRedis()
    rid = _asked(r)
    assert rid in {a["request_id"] for a in approvals.pending(client=r)}

    out = approvals.withdraw(rid, ACTOR, "superseded by a fresh test run", client=r)

    st = approvals.status(rid, client=r)
    assert st["status"] == ApprovalStatus.WITHDRAWN.value
    assert st["status"] not in {d.value for d in Decision}, "a withdrawal is not a decision"
    # the SAME field names a decision writes, so every surface that already renders how an approval
    # ended renders this one too — `_already`'s message included
    assert st["decided_by"] == ACTOR and "superseded" in st["comment"]
    assert st["decided_via"] == "cli" and st["decided_at"]
    assert rid not in {a["request_id"] for a in approvals.pending(client=r)}
    assert out["request_id"] == rid and out["decision"] == ApprovalStatus.WITHDRAWN.value


def test_it_is_soft__the_question_and_its_payload_survive():
    """`withdraw`, not `delete`. What was asked is evidence: a fresh run of the same recording is
    only comparable with the one it replaces if the one it replaces is still readable."""
    r = FakeRedis()
    rid = _asked(r, subject="2 test — who is speaking? [munsit]")
    approvals.withdraw(rid, ACTOR, client=r)

    st = approvals.status(rid, client=r)
    assert st["subject"] == "2 test — who is speaking? [munsit]"
    assert st["payload"]["answer_labels"] == ["SPEAKER_00"]
    assert st["requester"] == "tests" and st["created_at"]


def test_the_withdrawal_is_in_the_audit_log_beside_the_decisions():
    """One trail, not two. Everything that ever ENDED an approval is on `approvals:decisions`, so
    reading that stream answers "what became of this request" without a second place to look."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.withdraw(rid, ACTOR, "stale", client=r)

    entries = r.xrange("approvals:decisions")
    assert len(entries) == 1
    fields = entries[0][1]
    assert fields["request_id"] == rid and fields["decision"] == ApprovalStatus.WITHDRAWN.value
    assert fields["actor"] == ACTOR and fields["comment"] == "stale"


def test_a_withdrawn_request_can_no_longer_be_answered():
    """The point of closing it. A card already sent to Teams stays on someone's screen, so the guard
    has to be at the gate, not at the channel."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.withdraw(rid, ACTOR, client=r)

    with pytest.raises(ValueError, match="withdrawn"):
        approvals.human_decision(rid, Decision.APPROVE.value, ACTOR, "review-app",
                                 answer={"SPEAKER_00": {"identity": ACTOR}}, client=r)


def test_a_request_a_human_already_decided_is_not_withdrawn():
    """The reverse guard, and the more important one: a withdrawal must never overwrite a record of
    what a person said."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.human_decision(rid, Decision.DECLINE.value, ACTOR, "review-app", "not now", client=r)

    with pytest.raises(ValueError, match="already"):
        approvals.withdraw(rid, ACTOR, "tidying up", client=r)
    assert approvals.status(rid, client=r)["status"] == ApprovalStatus.DECLINE.value


def test_changes_requested_is_still_open_so_it_can_be_withdrawn():
    """`update` leaves the request open on purpose — a reviewer who cannot tell two voices apart has
    not decided anything. A question left in that state for ever is exactly what wants retiring."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.human_decision(rid, Decision.UPDATE.value, ACTOR, "review-app", "unclear", client=r)
    approvals.withdraw(rid, ACTOR, "abandoned", client=r)
    assert approvals.status(rid, client=r)["status"] == ApprovalStatus.WITHDRAWN.value


def test_an_anonymous_withdrawal_is_refused_for_the_reason_a_decision_is():
    r = FakeRedis()
    rid = _asked(r)
    with pytest.raises(ValueError, match="actor"):
        approvals.withdraw(rid, "  ", "stale", client=r)
    assert approvals.status(rid, client=r)["status"] == ApprovalStatus.PENDING.value


def test_an_unknown_request_is_a_keyerror_not_a_silent_success():
    with pytest.raises(KeyError):
        approvals.withdraw("apr-nope", ACTOR, client=FakeRedis())


def test_a_channel_is_not_told_about_a_withdrawn_request():
    """`channel_events` filters on APPROVAL_FINAL, so withdrawal joins it — the one edit that stops
    every channel announcing retired cards, instead of three."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.withdraw(rid, ACTOR, client=r)
    assert approvals.channel_events("teams", client=r) == []
    assert ApprovalStatus.WITHDRAWN in APPROVAL_FINAL


def test_withdrawing_starts_nothing():
    """The continuation runner is woken by the same stream. A withdrawal that released the run its
    approval was gating would be far worse than leaving the card open."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.withdraw(rid, ACTOR, client=r)

    assert continuations.run_once(client=r) == [], "a withdrawal releases no run"
    # ...and it was ACKED rather than left pending, or it is redelivered forever and every later
    # decision queues up behind it
    assert continuations.run_once(client=r, pending_only=True) == []


def test_a_withdrawal_whose_audit_append_fails_never_happened():
    """The rollback `decide` learned the hard way, applied here for the same reason: the hash is
    written first so a consumer woken by the stream entry can read the request back, which means a
    failed append would otherwise leave a request CLOSED with nothing in the log to say why or by
    whom. A card silently retired and no record of it is worse than a stale card.

    So the prior fields go back, the fields the withdrawal introduced are removed, and the request
    returns to the pending set — still open, still answerable by anyone.
    """
    r = FakeRedis()
    rid = _asked(r)
    r.fail("xadd")
    with pytest.raises(Exception):
        approvals.withdraw(rid, ACTOR, "stale", client=r)
    r.fail("xadd", False)

    st = approvals.status(rid, client=r)
    assert st["status"] == ApprovalStatus.PENDING.value, f"left as {st['status']!r}"
    for gone in ("decided_by", "decided_via", "decided_at", "comment"):
        assert gone not in st, f"{gone} outlived a withdrawal that never landed"
    assert rid in r.s["approvals:pending"]
    # ...and it is still fully usable: answerable by a person, or retirable on a second attempt
    assert approvals.withdraw(rid, ACTOR, "stale", client=r)["request_id"] == rid


class _AnsweredMidWindow(FakeRedis):
    """A Redis that lets a person answer between `withdraw`'s status READ and its write.

    The window is real: several channels write concurrently — the review app, Telegram, the CLI, a
    connector polling the MCP tool — so the status check is a read whose answer can be stale by the
    time the write lands. Modelling it is the only way a single-threaded test can catch it.
    """

    def __init__(self):
        super().__init__()
        self.answer_now = None

    def hgetall(self, k):
        out = super().hgetall(k)
        if self.answer_now and k.startswith("approvals:req:"):
            rid, self.answer_now = self.answer_now, None
            approvals.human_decision(rid, Decision.APPROVE.value, "maria@x.com", "review-app",
                                     answer={"SPEAKER_00": {"tag": "a guest"}}, client=self)
        return out


def test_an_answer_arriving_mid_withdrawal_wins_and_the_withdrawal_is_refused():
    """One request, one ending. Without the atomic claim both writers append to the audit log: the
    hash reads `withdrawn` while carrying the approver's name, and `continuations` — which dispatches
    on the STREAM entry — starts the run behind a question every human surface says was retired.
    That is strictly worse than the stale card withdrawal exists to remove.
    """
    r = _AnsweredMidWindow()
    rid = _asked(r)
    r.answer_now = rid                       # a person approves inside the window

    with pytest.raises(ValueError, match="already"):
        approvals.withdraw(rid, ACTOR, "stale", client=r)

    st = approvals.status(rid, client=r)
    assert st["status"] == ApprovalStatus.APPROVE.value, "the human's answer must win"
    assert st["decided_by"] == "maria@x.com"
    endings = [f["decision"] for _, f in r.xrange("approvals:decisions")]
    assert endings == [Decision.APPROVE.value], f"one request, one ending — got {endings}"


def test_the_refusal_names_who_ended_it_and_when():
    """`_already` reads `decided_by`/`decided_via`/`decided_at`. A withdrawal that wrote its own field
    names would degrade this message to '(by ? via ? at ?)' — and it is read by a person who has just
    been told they cannot answer a question that was on their screen a moment ago."""
    r = FakeRedis()
    rid = _asked(r)
    approvals.withdraw(rid, ACTOR, "superseded", channel="review-app", client=r)

    with pytest.raises(ValueError) as e:
        approvals.withdraw(rid, "someone-else@x.com", "again", client=r)
    assert ACTOR in str(e.value) and "review-app" in str(e.value)
