"""What a CHANNEL is told about — `approvals.channel_events`.

A channel (Teams, Telegram, the CLI) is a NOTIFIER: its job is "what needs a person now". The
request stream is durable and per-channel, so a channel that has been off — never configured,
crashed, or added to CHANNELS later — comes back to a backlog of requests decided long ago through
some other channel. Announcing those is not thoroughness; it buries the few that matter.

That filter lives in `channel_events` rather than in each channel, because every channel needs it and
a second copy is a second thing to get wrong. See tests/unit/substrate/channels/ for what each
channel then DOES with an event.

Offline: a fake Redis, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_approvals.py
"""
from fixtures.fakes import FakeRedis
from lab.substrate import approvals

# ---------------------------------------------------------------- a channel notifies what is OPEN
def test_a_channel_is_not_told_about_approvals_someone_already_decided():
    """A channel that has been off — unconfigured, crashed, or added later — accumulates a backlog of
    requests decided long ago through some OTHER channel. Announcing those on startup buries the few
    that matter. Measured on this lab's own stream when the Teams channel was first configured: 216
    requests, 11 open, so it would have posted 59 cards of which 48 needed nobody."""
    r = FakeRedis()
    open_id = approvals.request("speaker-mapping", "still open", {}, "wf", client=r)
    decided = approvals.request("speaker-mapping", "answered on Monday", {}, "wf", client=r)
    approvals.human_decision(decided, "approve", "ann", "cli", client=r)

    got = approvals.channel_events("teams", client=r)
    assert [f["request_id"] for _eid, f in got] == [open_id], "only the one still awaiting a person"


def test_the_skipped_ones_are_acked_so_they_do_not_look_like_undelivered_work():
    """Skipping without acking leaves them in the group's pending list forever, where they are
    indistinguishable from a channel that is failing to deliver."""
    r = FakeRedis()
    decided = approvals.request("ea-import", "s", {}, "wf", client=r)
    approvals.human_decision(decided, "decline", "ann", "cli", client=r)
    approvals.channel_events("teams", client=r)
    assert r.xpending(approvals.REQ, "teams")["pending"] == 0


def test_a_request_whose_state_is_gone_is_also_acked_rather_than_retried_forever():
    """Nothing to show a human, and nothing to come back for."""
    r = FakeRedis()
    rid = approvals.request("ea-import", "s", {}, "wf", client=r)
    r.delete(f"approvals:req:{rid}")
    assert approvals.channel_events("teams", client=r) == []
    assert r.xpending(approvals.REQ, "teams")["pending"] == 0


def test_an_audit_consumer_can_still_ask_for_every_event():
    """`only_open` is a notifier's default, not a rule — a replay or audit consumer wants the lot."""
    r = FakeRedis()
    approvals.request("ea-import", "a", {}, "wf", client=r)
    d = approvals.request("ea-import", "b", {}, "wf", client=r)
    approvals.human_decision(d, "approve", "ann", "cli", client=r)
    assert len(approvals.channel_events("telegram", only_open=False, client=r)) == 2


def test_an_update_leaves_the_request_open_so_a_channel_still_sees_it():
    """`update` means changes requested — the request stays open and a later approval can complete
    it, so a channel that starts afterwards must still be told about it."""
    r = FakeRedis()
    rid = approvals.request("speaker-mapping", "s", {}, "wf", client=r)
    approvals.human_decision(rid, "update", "ann", "cli", "please redo", client=r)
    assert [f["request_id"] for _e, f in approvals.channel_events("teams", client=r)] == [rid]
