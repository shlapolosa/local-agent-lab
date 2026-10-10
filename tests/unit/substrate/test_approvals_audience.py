"""A channel reads only ITS AUDIENCE's approvals — `approvals.channel_events(audience=...)`.

Triage, not dispatch. `channel_events` already drops (and acks) what a person has decided, because
a channel announces what needs somebody NOW; this is the same filter asking the second question a
notifier has to answer — somebody WHO. It lives here for the same reason the open/closed filter
does: every channel needs it and a second copy is a second thing to get wrong.

Offline: a fake Redis, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_approvals_audience.py
"""
from fixtures.fakes import FakeRedis
from lab.platform.contracts import ApprovalAudience, ApprovalKind, Decision
from lab.substrate import approvals


def _ask(r, kind, subject="x"):
    return approvals.request(kind, subject, {"summary": {}}, "wf", client=r)


def _ids(channel, audience, r):
    return [f["request_id"] for _, f in approvals.channel_events(channel, audience=audience, client=r)]


def test_each_audience_is_told_only_about_its_own_kinds():
    r = FakeRedis()
    term = _ask(r, ApprovalKind.CONCEPT_ADMISSION.value, "'Agent' means two things")
    doc = _ask(r, ApprovalKind.DRAFT_REVIEW.value, "BRS.md")
    assert _ids("steward", ApprovalAudience.STEWARD, r) == [term]
    assert _ids("teams", ApprovalAudience.OWNER, r) == [doc]


def test_an_event_for_the_other_audience_is_acked_not_left_pending():
    """Acked for the same measured reason a decided request is: an entry left unacked sits in the
    group's pending list for ever, where it looks like undelivered work and is reclaimed on every
    restart. A card this channel will never show needs no delivery."""
    r = FakeRedis()
    _ask(r, ApprovalKind.CONCEPT_ADMISSION.value)
    assert _ids("teams", ApprovalAudience.OWNER, r) == []
    assert r.xpending(approvals.REQ, "teams")["pending"] == 0


def test_no_audience_means_every_kind_which_is_what_the_review_app_needs():
    """The review app is where everybody DECIDES — every channel's card links to it — so it must
    keep seeing the whole queue. Omitting the argument is therefore the unfiltered behaviour every
    existing caller had."""
    r = FakeRedis()
    ids = {_ask(r, ApprovalKind.CONCEPT_ADMISSION.value), _ask(r, ApprovalKind.EA_IMPORT.value)}
    assert {f["request_id"] for _, f in approvals.channel_events("review-app", client=r)} == ids


def test_the_audience_filter_does_not_replace_the_open_filter():
    """Both filters apply: a steward's question already answered is not re-announced to the steward."""
    r = FakeRedis()
    term = _ask(r, ApprovalKind.CONCEPT_ADMISSION.value)
    open_ = _ask(r, ApprovalKind.CONCEPT_ADMISSION.value)
    approvals.human_decision(term, Decision.DECLINE, "steward@doh", "cli", client=r)
    assert _ids("steward", ApprovalAudience.STEWARD, r) == [open_]


def test_a_legacy_kind_still_reaches_the_owner_channels():
    """`adoit-import` predates the vendor-neutral rename and is in no enum member. It must still be
    announced where it always was, and must NOT appear on the steward's queue."""
    r = FakeRedis()
    rid = _ask(r, "adoit-import", "lab model")
    assert _ids("steward", ApprovalAudience.STEWARD, r) == []
    assert _ids("teams", ApprovalAudience.OWNER, r) == [rid]


def test_an_audit_consumer_asking_for_one_audience_gets_one():
    """`only_open=False` is for a replay/audit consumer that wants every event, decided or not. The
    two filters are INDEPENDENT: asking for an audience there must still narrow by audience, because
    an argument quietly ignored in one combination is worse than one that is not offered."""
    r = FakeRedis()
    term = _ask(r, ApprovalKind.CONCEPT_ADMISSION.value)
    doc = _ask(r, ApprovalKind.DRAFT_REVIEW.value)
    approvals.human_decision(term, Decision.DECLINE, "steward@doh", "cli", client=r)
    got = approvals.channel_events("steward", only_open=False,
                                   audience=ApprovalAudience.STEWARD, client=r)
    assert [f["request_id"] for _, f in got] == [term]        # decided, but still the steward's
    assert doc not in [f["request_id"] for _, f in got]


def test_the_stewards_consumer_group_is_created_with_everyone_elses():
    """`CHANNELS` membership is asserted channel-side (tests/unit/substrate/channels/test_steward.py);
    what belongs here is that `ensure_groups` therefore CREATES the queue it reads."""
    r = FakeRedis()
    approvals.ensure_groups(r)
    assert (approvals.REQ, "steward") in r.groups
