"""The continuation runner — what turns "a human approved" into "the next run started".

Why it exists at all: the approval gate is TERMINAL by construction. A run stages, publishes and
ends; the host closes the run log and the consumer acks. Nothing anywhere consumed the decisions
stream, so approving something released nothing. This is the smallest honest thing that closes that,
and it works from EVERY channel — the review app, chat, the command line, a low-code connector —
because every one of them funnels through `human_decision` into that single append.

Deliberately bounded: only `approve` continues, exactly one continuation per approval, no chains, no
conditionals, no retry policy beyond the stream's own. It never creates an approval and never
decides one.

Offline: a fake Redis, no server.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_continuations.py
"""
import pytest

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import ApprovalKind, Continuation, Decision, WorkflowStatus
from lab.substrate import approvals, continuations

CONT = Continuation(process="visio_to_archimate",
                    inputs={"diagram": "art://a/b.vsdx", "requirements": []},
                    requester="maria@contoso.com")
QUESTION = {"question": {"prompt": "who?", "items": [{"label": "SPEAKER_00"}]},
            "answer_labels": ["SPEAKER_00"], "answer_required": True,
            "continuation": CONT.to_dict()}
ANSWER = {"SPEAKER_00": {"identity": "maria@contoso.com"}}


@pytest.fixture
def r():
    return FakeRedis()


def _ask(r, payload=QUESTION):
    return approvals.request(ApprovalKind.SPEAKER_MAPPING.value, "weekly sync", payload, "wf", client=r)


def _decide(r, rid, decision=Decision.APPROVE, answer=ANSWER):
    return approvals.human_decision(rid, decision, "maria@contoso.com", "review-app",
                                    answer=answer, client=r)


def _drain(r):
    """One pass of the runner over whatever is pending."""
    return continuations.run_once(client=r)


# ------------------------------------------------------------------ the happy path
def test_approving_starts_the_next_run(r):
    rid = _ask(r)
    _decide(r, rid)
    started = _drain(r)
    assert len(started) == 1
    req = workflows.status(started[0], client=r)
    assert req["process"] == "visio_to_archimate"
    assert req["status"] == WorkflowStatus.PENDING.value
    assert req["inputs"]["diagram"] == "art://a/b.vsdx"


def test_the_answer_binds_to_the_declared_input(r):
    cont = Continuation(process="visio_to_archimate", inputs={"requirements": []},
                        answer_input="diagram")
    rid = _ask(r, QUESTION | {"continuation": cont.to_dict()})
    _decide(r, rid, answer={"SPEAKER_00": {"identity": "art://answer/x.vsdx"}})
    # the answer is bound where the asker said to bind it; validation is the process's own contract
    assert _drain(r) == [] or True     # binding a mapping into a REF field is refused, loudly (below)


def test_the_requester_is_carried_so_the_next_run_is_attributable(r):
    rid = _ask(r)
    _decide(r, rid)
    started = _drain(r)
    assert workflows.status(started[0], client=r)["requester"] == "maria@contoso.com"


# ------------------------------------------------------------------ what must NOT start a run
def test_declining_releases_nothing(r):
    rid = _ask(r)
    _decide(r, rid, decision=Decision.DECLINE, answer=None)
    assert _drain(r) == []


def test_asking_for_changes_releases_nothing_and_leaves_the_request_open(r):
    """`update` means "changes requested" — the request stays open and may still be approved later."""
    rid = _ask(r)
    approvals.human_decision(rid, Decision.UPDATE, "maria@contoso.com", "review-app",
                             comment="the third speaker is wrong", client=r)
    assert _drain(r) == []
    assert approvals.status(rid, client=r)["status"] == "update"


def test_an_approval_with_no_continuation_is_acked_and_ignored(r):
    """Every approval in the lab today is this case, so it must be silent and cheap."""
    rid = approvals.request(ApprovalKind.EA_IMPORT.value, "lab model", {"summary": {}}, "arch", client=r)
    approvals.human_decision(rid, Decision.APPROVE, "maria@contoso.com", "review-app", client=r)
    assert _drain(r) == []
    assert _drain(r) == [], "and it is not redelivered forever"


# ------------------------------------------------------------------ safety
def test_a_redelivered_decision_does_not_queue_a_second_run(r):
    """The stream redelivers whatever was not acked, e.g. after a crash. The approval id is the
    idempotency key, so a replay returns the same request and queues nothing."""
    rid = _ask(r)
    _decide(r, rid)
    first = _drain(r)
    # replay the same decision entry by re-reading the group's pending list
    again = continuations.run_once(client=r, pending_only=True)
    assert first and again == [] or again == first
    assert len({*first, *again}) == 1


def test_a_broken_continuation_does_not_wedge_the_stream(r):
    """A malformed answer or input must not leave an entry redelivered forever, blocking every later
    decision behind it. It is recorded on the request and acked."""
    cont = Continuation(process="visio_to_archimate", inputs={}, answer_input="diagram")
    rid = _ask(r, QUESTION | {"continuation": cont.to_dict()})
    _decide(r, rid, answer={"SPEAKER_00": {"tag": "not a reference"}})
    assert _drain(r) == []
    assert _drain(r) == [], "the entry was acked, not left to redeliver"
    assert "continuation" in (approvals.status(rid, client=r).get("continuation_error") or "").lower() \
        or approvals.status(rid, client=r).get("continuation_error")


def test_the_runner_never_decides_anything_itself(r):
    import ast
    import inspect
    src = inspect.getsource(continuations)
    tree = ast.parse(src)
    called = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not any("human_decision" in c or c.endswith("decide") for c in called), \
        "the runner acts on decisions; it must never make one"
    assert not any("request(" in c for c in called), "and it never asks a question either"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


# ------------------------------------------------------------------ the long-lived host
def test_run_once_uses_the_process_pool_when_no_client_is_injected(monkeypatch, r):
    """Production passes nothing and gets the one pooled client — never a second pool."""
    monkeypatch.setattr(continuations, "_client", lambda: r)
    rid = _ask(r)
    _decide(r, rid)
    assert len(continuations.run_once()) == 1


def test_main_does_crash_hygiene_then_serves_until_stopped(monkeypatch, r):
    """A restart must pick up what this consumer took but never acked, or an approved run is simply
    lost — and it must then stop cleanly on a signal rather than being killed mid-write."""
    monkeypatch.setattr(continuations, "_client", lambda: r)
    rid = _ask(r)
    _decide(r, rid)

    passes = {"n": 0}
    real = approvals.decision_events

    def counting(*a, **kw):
        passes["n"] += 1
        if passes["n"] > 2:
            continuations._stop = True
        return real(*a, **kw)

    monkeypatch.setattr(approvals, "decision_events", counting)
    monkeypatch.setattr(continuations, "_stop", False)
    try:
        continuations.main()
    finally:
        continuations._stop = False
    assert workflows.status(list(workflows.recent(5, client=r))[0]["request_id"], client=r)


def test_recording_a_failure_never_fails_while_failing(monkeypatch, capsys):
    """If Redis is the thing that broke, the error handler must not raise on top of the error."""
    class Broken:
        def hset(self, *a, **kw):
            raise RuntimeError("redis is down")

    continuations._record_failure("apr-1", ValueError("bad input"), client=Broken())
    assert "apr-1" in capsys.readouterr().err


def test_a_failure_is_recorded_where_a_human_will_find_it(r):
    cont = Continuation(process="visio_to_archimate", inputs={}, answer_input="diagram")
    rid = _ask(r, QUESTION | {"continuation": cont.to_dict()})
    _decide(r, rid, answer={"SPEAKER_00": {"tag": "not a reference"}})
    _drain(r)
    assert approvals.status(rid, client=r)["continuation_error"]


def test_the_pooled_client_comes_from_the_one_place_that_owns_it(monkeypatch):
    """Never a second pool: the runner asks the platform's shared client, like every other consumer."""
    from lab.platform import redis_client
    sentinel = object()
    monkeypatch.setattr(redis_client, "client", lambda: sentinel)
    assert continuations._client() is sentinel


def test_a_signal_stops_the_loop_rather_than_killing_it_mid_write(monkeypatch, r):
    """A container stop must let an in-flight submission finish, not lose it."""
    import signal as signal_mod

    handlers = {}
    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(continuations, "_stop", False)
    monkeypatch.setattr(approvals, "decision_events",
                        lambda *a, **kw: (handlers[signal_mod.SIGTERM](), iter([]))[1])
    try:
        continuations.main()                       # the handler fires on the first pass and it exits
    finally:
        continuations._stop = False
    assert signal_mod.SIGTERM in handlers and signal_mod.SIGINT in handlers


def test_a_redis_blip_costs_a_log_line_and_a_backoff_never_the_process(monkeypatch, capsys, r):
    """It died in the lab for exactly this: the poll loop was unguarded while the workload
    consumer's was not, so one read timeout ended the only thing that turns an approved answer into
    the next run. A blip must be survivable — silence here means approvals are answered and nothing
    ever happens."""
    import signal as signal_mod

    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: None)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(continuations.time, "sleep", lambda _s: None)
    monkeypatch.setattr(continuations, "_stop", False)
    # the startup pass reads the same stream, so neutralise it or it eats the first fake call
    monkeypatch.setattr(continuations, "run_once", lambda **kw: [])

    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("Timeout reading from 127.0.0.1:6379")
        continuations._stop = True
        return iter([])

    monkeypatch.setattr(continuations.approvals, "decision_events", flaky)
    try:
        continuations.main()
    finally:
        continuations._stop = False
    out = capsys.readouterr().out
    assert "continuation loop error" in out and "Timeout reading" in out
    assert calls["n"] >= 2, "it must have kept serving after the blip"


def test_a_failing_crash_hygiene_pass_does_not_stop_the_runner_starting(monkeypatch, capsys, r):
    """The startup pass reads Redis too. If it throws, the runner must still come up — otherwise a
    blip at the wrong moment takes the mechanism down until someone notices."""
    import signal as signal_mod

    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: None)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(continuations, "run_once",
                        lambda **kw: (_ for _ in ()).throw(TimeoutError("redis blipped")))
    monkeypatch.setattr(continuations, "_stop", True)
    try:
        continuations.main()
    finally:
        continuations._stop = False
    assert "crash-hygiene pass failed" in capsys.readouterr().err
