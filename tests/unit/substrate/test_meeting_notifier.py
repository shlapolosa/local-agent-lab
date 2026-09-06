"""The meeting notifier — what turns "the minutes exist" into "the meeting knows about them".

Two things are worth testing here and the second matters more than the first: that it announces a
delivered result, and that it STAYS QUIET the rest of the time. Silence is the common case — an
ad-hoc recording resolves no meeting, a failed run has nothing to say — so a notifier that announced
eagerly would be worse than none, and the quiet paths are where the bugs would hide.

Offline: a fake Redis, no webhook, no tenant.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_meeting_notifier.py
"""
import json

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import TRANSCRIPT_TO_MINUTES, WorkflowStatus
from lab.substrate import meeting_notifier as N

DELIVERED = [{"name": "sync.transcript.md", "handle": "collab://item/b!d/01A",
              "url": "https://lab.sharepoint.example/Recordings/sync.transcript.md"},
             {"name": "sync.minutes.json", "handle": "collab://item/b!d/01B",
              "url": "https://lab.sharepoint.example/Recordings/sync.minutes.json"}]
DONE_RUN = {"status": WorkflowStatus.DONE.value, "chat_id": "19:t@thread.v2",
            "delivered": DELIVERED, "request_id": "wfr-1",
            "summary": {"decisions": 3, "actions": 2, "speakers": 4, "text": "we shipped"}}


# ---------------------------------------------------------------- what it says
def test_it_announces_where_the_outputs_are_never_what_they_say():
    """The outputs live in the tenant behind its own permissions. This says WHERE, not WHAT — a chat
    message carrying the minutes would put them in front of a wider audience than the folder does."""
    said = N.announcement(DONE_RUN)
    assert said["chat_id"] == "19:t@thread.v2"
    assert [f["name"] for f in said["files"]] == ["sync.transcript.md", "sync.minutes.json"]
    # ...and each one with the address a person can open. A message naming two files nobody can
    # reach is a notification in form only, so the link is what makes this worth sending at all.
    assert all(f["url"].startswith("https://") for f in said["files"])
    assert said["decisions"] == 3 and said["actions"] == 2
    body = json.dumps(said)
    assert "we shipped" not in body, "no minutes text"
    assert "@thread" in body and "@contoso" not in body, "ids yes, people no"


# ---------------------------------------------------------------- when it stays quiet
def test_a_run_that_reached_no_meeting_says_nothing():
    """An ad-hoc recording resolves no meeting, so there is no conversation to post to. Inventing a
    destination would be worse than silence."""
    assert N.announcement(DONE_RUN | {"chat_id": ""}) is None


def test_a_run_that_delivered_nothing_says_nothing():
    """Announcing links to files that were never written is the one lie this must not tell."""
    assert N.announcement(DONE_RUN | {"delivered": []}) is None


def test_a_failed_run_says_nothing():
    assert N.announcement(DONE_RUN | {"status": WorkflowStatus.FAILED.value}) is None


# ---------------------------------------------------------------- the loop
def _finish(r, process=TRANSCRIPT_TO_MINUTES.name, **fields):
    # The group is created FIRST, as the running service does: it starts at `$`, so a notifier
    # coming up fresh announces what happens next rather than every run the lab ever completed.
    workflows.ensure_finished_group(N.GROUP, r)
    rid, _ = workflows.submit(process, _inputs(process), "test", client=r)
    workflows.mark(rid, WorkflowStatus.DONE.value, client=r, **fields)
    return rid


def _inputs(process):
    return ({"transcript": "art://t/x.json", "speaker_map": {"S": {"tag": "x"}}}
            if process == TRANSCRIPT_TO_MINUTES.name
            else {"owner": "a@b.c", "recording": "collab://item/d/i"})


def test_a_finished_run_reaches_the_notifier_without_anyone_polling():
    """`mark` appends to the finished stream at the one place a run is closed, so nothing has to
    watch for a result — the same shape as approvals:decisions feeding the continuation runner."""
    r = FakeRedis()
    _finish(r, chat_id="19:t@thread.v2", delivered=DELIVERED, summary={"decisions": 1})
    said = N.run_once(client=r)
    assert len(said) == 1 and said[0]["chat_id"] == "19:t@thread.v2"


def test_it_ignores_a_process_it_is_not_for():
    r = FakeRedis()
    _finish(r, process="meeting_to_transcript", chat_id="19:t@thread.v2", delivered=DELIVERED)
    assert N.run_once(client=r) == []


def test_an_unannounceable_run_is_still_acked():
    """An entry left unacked is redelivered forever and every later meeting queues behind it, so one
    result nobody can announce must not stop the mechanism for the next."""
    r = FakeRedis()
    _finish(r, chat_id="", delivered=[])            # nothing to say
    assert N.run_once(client=r) == []
    assert r.xpending(workflows.DONE, N.GROUP)["pending"] == 0


def test_a_failure_while_announcing_does_not_stop_the_next_meeting(monkeypatch):
    r = FakeRedis()
    a = _finish(r, chat_id="19:a@thread.v2", delivered=DELIVERED)
    _finish(r, chat_id="19:b@thread.v2", delivered=DELIVERED)
    calls = []

    def boom(url, payload):
        calls.append(payload["chat_id"])
        if len(calls) == 1:
            raise RuntimeError("the webhook refused")
        return ""
    monkeypatch.setattr(N, "post_json", boom)
    N.run_once(webhook="https://flow.example/hook", client=r)
    assert calls == ["19:a@thread.v2", "19:b@thread.v2"], "the second was still attempted"
    # ...and the one that FAILED is still pending, so a minute later the reclaim retries it. Acking
    # a failed send would lose the message, which is the one thing Streams were chosen to prevent.
    assert r.xpending(workflows.DONE, N.GROUP)["pending"] == 1
    assert "RuntimeError" in workflows.status(a, client=r)["notify_error"], \
        "and the reason is on the run, where a person looking at it will find it"


def test_a_failed_send_is_retried_and_then_acked(monkeypatch):
    """The point of leaving it unacked. A webhook outage delays a meeting's message; it does not
    drop it. The retry arrives through the reclaim, so it needs no bookkeeping of its own."""
    r = FakeRedis()
    _finish(r, chat_id="19:a@thread.v2", delivered=DELIVERED)
    calls = []

    def flaky(url, payload):
        calls.append(payload["chat_id"])
        if len(calls) == 1:
            raise RuntimeError("the webhook refused")
        return ""
    monkeypatch.setattr(N, "post_json", flaky)
    monkeypatch.setattr(workflows, "RECLAIM_IDLE_MS", 0)      # do not wait a minute for the retry
    N.run_once(webhook="https://flow.example/hook", client=r)
    assert N.run_once(webhook="https://flow.example/hook", client=r), "the retry announced it"
    assert calls == ["19:a@thread.v2", "19:a@thread.v2"]
    assert r.xpending(workflows.DONE, N.GROUP)["pending"] == 0


def test_a_run_already_announced_is_not_announced_twice(monkeypatch):
    """At-least-once delivery: a reclaimed entry whose ack was lost after a send that DID land would
    otherwise post the same links again into the same conversation."""
    r = FakeRedis()
    rid = _finish(r, chat_id="19:a@thread.v2", delivered=DELIVERED)
    calls = []
    monkeypatch.setattr(N, "post_json", lambda url, payload: calls.append(payload) or "")
    assert N.run_once(webhook="https://flow.example/hook", client=r)
    assert len(calls) == 1
    # the same run delivered a second time — what a lost ack looks like from here
    said = N.handle("9-1", {"request_id": rid, "process": TRANSCRIPT_TO_MINUTES.name},
                    webhook="https://flow.example/hook", client=r)
    assert said is None and len(calls) == 1


def test_without_a_webhook_it_logs_rather_than_failing(capsys):
    """Unset is the offline default, and it is what makes this path testable without a tenant."""
    r = FakeRedis()
    _finish(r, chat_id="19:t@thread.v2", delivered=DELIVERED)
    assert len(N.run_once(client=r)) == 1
    assert "would post" in capsys.readouterr().out


def test_a_notifier_starting_fresh_does_not_announce_history():
    """The group starts at `$` on purpose. A service restarting should not post links into every
    meeting the lab has ever processed — which is what starting at 0 would do."""
    r = FakeRedis()
    rid, _ = workflows.submit(TRANSCRIPT_TO_MINUTES.name, _inputs(TRANSCRIPT_TO_MINUTES.name),
                              "test", client=r)
    workflows.mark(rid, WorkflowStatus.DONE.value, client=r,
                   chat_id="19:old@thread.v2", delivered=DELIVERED)
    assert N.run_once(client=r) == [], "the run finished before this notifier existed"


# ---------------------------------------------------------------- the service around it
def test_the_pooled_client_comes_from_the_one_place_that_owns_it(monkeypatch):
    """Never a second pool: it asks the platform's shared client, like every other consumer here."""
    from lab.platform import redis_client
    sentinel = object()
    monkeypatch.setattr(redis_client, "client", lambda: sentinel)
    assert N._client() is sentinel


def test_main_serves_until_stopped_and_says_whether_it_has_a_destination(monkeypatch, capsys):
    """The ready line is the only thing an operator sees. It has to say whether a webhook is
    configured, because "unset" is a working mode (it logs what it would post) and looks identical
    to "running fine and announcing nothing" otherwise."""
    r = FakeRedis()
    monkeypatch.setattr(N, "_client", lambda: r)
    monkeypatch.setattr(N.config, "MEETING_WEBHOOK_URL", "")
    passes = {"n": 0}
    real = workflows.finished_events

    def counting(*a, **kw):
        passes["n"] += 1
        if passes["n"] > 2:
            N._stop = True
        return real(*a, **kw)

    monkeypatch.setattr(workflows, "finished_events", counting)
    monkeypatch.setattr(N, "_stop", False)
    try:
        N.main()
    finally:
        N._stop = False
    out = capsys.readouterr().out
    assert "meeting notifier ready" in out and "NO webhook" in out
    assert "meeting notifier stopped" in out, "a signal stops the loop, it does not kill the process"
    assert passes["n"] > 2


def test_a_redis_blip_backs_off_instead_of_ending_the_service(monkeypatch, capsys):
    """This is the only thing that tells a meeting its minutes exist; a transient read error must
    cost a log line and a pause, never the process."""
    r = FakeRedis()
    monkeypatch.setattr(N, "_client", lambda: r)
    monkeypatch.setattr(N, "BACKOFF_S", 0)
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset")
        N._stop = True
        return []

    monkeypatch.setattr(N, "run_once", flaky)
    monkeypatch.setattr(N, "_stop", False)
    try:
        N.main()
    finally:
        N._stop = False
    assert "connection reset" in capsys.readouterr().err and calls["n"] == 2


def test_recording_a_failure_never_fails_while_failing(capsys):
    """If Redis is what broke, the handler that notes the breakage must not raise on top of it."""
    class Broken:
        def hset(self, *a, **kw):
            raise RuntimeError("redis is down")

    N._note_failure(Broken(), "wfr-1", OSError("connection refused"))   # must not raise
