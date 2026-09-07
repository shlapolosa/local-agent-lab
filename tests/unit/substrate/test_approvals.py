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
from lab.platform import streams
from lab.platform.contracts import ApprovalKind, ApprovalStatus, Decision
from lab.substrate import approvals

# ---------------------------------------------------------------- a channel notifies what is OPEN
class _WakesOnPublish(FakeRedis):
    """A Redis whose stream publish immediately runs whatever the announcement wakes.

    The real consumers are woken by an XADD and read the record back at once, so anything written
    AFTER the publish is not there yet for them. Modelling that is the only way a single-threaded
    test can catch an ordering bug that in production looks like an intermittent lost run.
    """

    def __init__(self, on_publish):
        super().__init__()
        self._on_publish = on_publish

    def xadd(self, stream, fields, **kw):
        eid = super().xadd(stream, fields, **kw)
        self._on_publish(stream, fields)
        return eid


def test_a_failed_announcement_leaves_no_trace_of_the_decision():
    """The other half of the ordering, and the reason the fix is not just a swap.

    Writing the hash first means a failed audit append would otherwise leave the request marked
    decided with NOTHING in the decisions log — a decision that happened for every reader and never
    happened for the record. So the prior fields are restored, the fields this decision introduced
    are removed, and the claim goes back: the request stays answerable, by anyone.
    """
    r = FakeRedis()
    rid = approvals.request(ApprovalKind.SPEAKER_MAPPING, "who spoke?",
                            {"question": {"prompt": "?"}, "answer_labels": ["SPEAKER_00"],
                             "answer_required": True}, "maria@x.com", client=r)
    r.fail("xadd")
    try:
        approvals.human_decision(rid, Decision.APPROVE, "maria@x.com", "teams",
                                 answer={"SPEAKER_00": {"tag": "a guest"}}, client=r)
    except Exception:
        pass
    r.fail("xadd", False)
    st = approvals.status(rid, client=r)
    assert st["status"] == ApprovalStatus.PENDING, f"left as {st['status']!r}"
    assert "answer" not in st, "the answer of a decision that never landed must not be readable"
    assert rid in r.s["approvals:pending"], "and anyone may still answer it"
    # ...and the request really is still answerable
    assert approvals.human_decision(rid, Decision.APPROVE, "omar@x.com", "cli",
                                    answer={"SPEAKER_00": {"tag": "a guest"}},
                                    client=r)["decision"] == Decision.APPROVE


def test_the_answer_is_readable_before_the_decision_is_announced():
    """LOST A RUN LIVE. `decide` announced on `approvals:decisions` and only then wrote the answer to
    the request hash. The continuation runner is woken by that entry and immediately reads
    `status(rid)["answer"]` — so it saw a decision with no answer, refused the run with "speaker_map
    is required", and ACKED, which means no redelivery and no second chance. A human had answered
    correctly; the answer was simply not readable yet.

    `workflows.mark` already states this rule for the finished-runs stream. It is the same rule."""
    seen = {}
    def woken(stream, f):                    # only the DECISIONS stream wakes the continuation runner
        if stream == approvals.DEC:
            seen["answer"] = approvals.status(f["request_id"], client=r).get("answer")

    r = _WakesOnPublish(woken)
    rid = approvals.request(ApprovalKind.SPEAKER_MAPPING, "who spoke?",
                            {"question": {"prompt": "?"}, "answer_labels": ["SPEAKER_00"],
                             "answer_required": True}, "maria@x.com", client=r)
    approvals.decide(rid, Decision.APPROVE, "maria@x.com", "teams",
                     answer={"SPEAKER_00": {"tag": "a guest"}}, client=r)
    assert seen["answer"] == {"SPEAKER_00": {"tag": "a guest"}}, \
        "a consumer woken by the decision must be able to read the answer it is about"


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


# ---------------------------------------------------------------- blocking reads must not kill a channel
class _TimingOutRedis(FakeRedis):
    """A Redis whose blocking read times out — what really happens when the BLOCK duration meets or
    exceeds the client's socket_timeout, which is how the Teams channel died within seconds of being
    configured for the first time."""

    def xreadgroup(self, *a, **k):
        import redis as _redis
        raise _redis.TimeoutError("Timeout reading from 127.0.0.1:6379")


def test_a_blocking_read_that_times_out_means_no_events_not_a_crash():
    """`block_ms=5000` against `socket_timeout=5` is a race the socket usually wins. Unguarded, the
    exception leaves `channel_events` and kills the channel process."""
    r = _TimingOutRedis()
    assert approvals.channel_events("teams", block_ms=5000, client=r) == []
    assert approvals.decision_events("continuations", block_ms=5000, client=r) is not None


def test_the_block_is_clamped_below_the_socket_timeout_so_the_normal_path_never_races():
    """Catching the timeout is the safety net; not provoking it is the fix. A channel asking to block
    for the whole socket timeout must be held under it."""
    from lab.platform import redis_client
    seen = {}

    class _Recording(FakeRedis):
        def xreadgroup(self, *a, **k):
            seen["block"] = k.get("block")
            return []

    r = _Recording()
    approvals.channel_events("teams", block_ms=5000, client=r)
    assert seen["block"] is not None
    assert seen["block"] < redis_client.SOCKET_TIMEOUT_S * 1000, "would race the socket timeout"


def test_no_block_still_means_a_non_blocking_read():
    """block_ms=0 is 'return whatever is there' — it must not become a blocking call."""
    seen = {}

    class _Recording(FakeRedis):
        def xreadgroup(self, *a, **k):
            seen["block"] = k.get("block")
            return []

    approvals.channel_events("teams", block_ms=0, client=_Recording())
    assert seen["block"] is None


def test_a_crashed_channel_does_not_lose_the_approvals_it_had_in_flight():
    """`>` returns only entries NEVER delivered to the group, so whatever a channel took and never
    acked stays in its pending list and is shown to nobody — a crash would silently lose approvals,
    the exact failure Streams were chosen over pub/sub to prevent. Not theoretical: the Teams channel
    died on its first start and stranded ten OPEN approvals."""
    r = FakeRedis()
    rid = approvals.request("speaker-mapping", "in flight when it crashed", {}, "wf", client=r)
    taken = approvals.channel_events("teams", client=r)          # delivered...
    assert [f["request_id"] for _e, f in taken] == [rid]          # ...and deliberately NOT acked

    # a second call moments later must NOT redeliver — the entry is still live work, and a real
    # server would refuse to claim it under RECLAIM_IDLE_MS. Only an ABANDONED one comes back.
    assert approvals.channel_events("teams", client=r) == []
    r.age_pending(approvals.REQ, "teams", streams.RECLAIM_IDLE_MS / 1000 + 1)

    again = approvals.channel_events("teams", client=r)           # the restarted process
    assert [f["request_id"] for _e, f in again] == [rid], "the restart must see it again"


def test_reclaimed_work_still_respects_the_open_filter():
    """A stranded entry for an approval decided in the meantime is acked, not posted."""
    r = FakeRedis()
    rid = approvals.request("ea-import", "stranded then decided", {}, "wf", client=r)
    approvals.channel_events("teams", client=r)                   # stranded, unacked
    r.age_pending(approvals.REQ, "teams", streams.RECLAIM_IDLE_MS / 1000 + 1)
    approvals.human_decision(rid, "approve", "ann", "cli", client=r)
    assert approvals.channel_events("teams", client=r) == []
    assert r.xpending(approvals.REQ, "teams")["pending"] == 0


def test_a_server_without_xautoclaim_still_delivers_what_is_new():
    """Reclaim is best-effort: it must never stop a channel doing its actual job."""
    class _NoClaim(FakeRedis):
        def xautoclaim(self, *a, **k):
            raise Exception("ERR unknown command 'XAUTOCLAIM'")
    r = _NoClaim()
    rid = approvals.request("speaker-mapping", "s", {}, "wf", client=r)
    assert [f["request_id"] for _e, f in approvals.channel_events("teams", client=r)] == [rid]
