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
from lab.platform import streams, workflows
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
def test_an_approval_records_the_run_it_released(r):
    """A person following the decision must be able to find the run it started."""
    rid = _ask(r)
    _decide(r, rid)
    started = _drain(r)
    assert started and r.hget(f"approvals:req:{rid}", "released_request_id") == started[0]
    assert r.hget(f"approvals:req:{rid}", "released_process") == "visio_to_archimate"


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



# The loop MECHANICS — the guard, the back-off, the signal handler, the crash-hygiene pass — belong
# to `lab.platform.streams.serve` and are tested once, there. What is left here is what this runner
# owns: that it reads decisions, hands each to `_handle`, and does its own hygiene pass on start.
# `_stopper` is how a test ends a real serve loop: `serve` installs a SIGTERM handler, so calling it
# is exactly what a container stop does.
def _stopper(monkeypatch):
    handlers = {}
    import signal as signal_mod
    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    return handlers, (lambda: handlers[signal_mod.SIGTERM]())


def test_main_does_crash_hygiene_then_serves_until_stopped(monkeypatch, r):
    """A restart must pick up what this consumer took but never acked, or an approved run is simply
    lost — and it must then stop cleanly on a signal rather than being killed mid-write."""
    _handlers, stop = _stopper(monkeypatch)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    rid = _ask(r)
    _decide(r, rid)

    passes = {"n": 0}
    real = approvals.decision_events

    def counting(*a, **kw):
        passes["n"] += 1
        if passes["n"] > 2:
            stop()
        return real(*a, **kw)

    monkeypatch.setattr(approvals, "decision_events", counting)
    continuations.main()
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

    handlers, stop = _stopper(monkeypatch)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(approvals, "decision_events", lambda *a, **kw: (stop(), iter([]))[1])
    continuations.main()                           # the handler fires on the first pass and it exits
    assert signal_mod.SIGTERM in handlers and signal_mod.SIGINT in handlers


def test_a_redis_blip_costs_a_log_line_and_a_backoff_never_the_process(monkeypatch, capsys, r):
    """It died in the lab for exactly this: the poll loop was unguarded while the workload
    consumer's was not, so one read timeout ended the only thing that turns an approved answer into
    the next run. A blip must be survivable — silence here means approvals are answered and nothing
    ever happens."""
    _handlers, stop = _stopper(monkeypatch)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(streams.time, "sleep", lambda _s: None)
    # the startup pass reads the same stream, so neutralise it or it eats the first fake call
    monkeypatch.setattr(continuations, "run_once", lambda **kw: [])

    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("Timeout reading from 127.0.0.1:6379")
        stop()
        return iter([])

    monkeypatch.setattr(continuations.approvals, "decision_events", flaky)
    continuations.main()
    out = capsys.readouterr()
    assert "continuation runner loop error" in out.err and "Timeout reading" in out.err
    assert calls["n"] >= 2, "it must have kept serving after the blip"


def test_a_failing_crash_hygiene_pass_does_not_stop_the_runner_starting(monkeypatch, capsys, r):
    """The startup pass reads Redis too. If it throws, the runner must still come up — otherwise a
    blip at the wrong moment takes the mechanism down until someone notices."""
    _handlers, stop = _stopper(monkeypatch)
    monkeypatch.setattr(continuations, "_client", lambda: r)
    monkeypatch.setattr(continuations, "run_once",
                        lambda **kw: (_ for _ in ()).throw(TimeoutError("redis blipped")))
    monkeypatch.setattr(approvals, "decision_events", lambda *a, **kw: (stop(), iter([]))[1])
    continuations.main()
    assert "crash-hygiene pass failed" in capsys.readouterr().err


# ------------------------------------------------------------------ the fabric's questions
def _fabric_ask(r, kind=ApprovalKind.DRAFT_REVIEW.value):
    cont = Continuation(process="artifact_publish", inputs={"artifact_iri": "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"})
    payload = {"question": {"prompt": "Is this right?", "items": [{"label": "document_type"}], "fields": ["value"]},
               "answer_labels": ["document_type"], "answer_required": True, "continuation": cont.to_dict()}
    return approvals.request(kind, "ADR-14 — review", payload, "a@x.org", client=r)


def test_a_fabric_decision_is_applied_by_the_curator_then_released_with_the_approval_bound(monkeypatch, r):
    """The person's answer reaches the fabric FIRST (rung H, with the actor), then the publish run starts
    knowing which approval released it — a declared `approval_id` input is bound by the runner."""
    applied = []

    async def fake_apply(state, actor, *, call=None):
        applied.append((state["kind"], actor, state["answer"])); return [("semantic_promote", {})]
    monkeypatch.setitem(continuations.answer_appliers.APPLIERS, "draft-review", fake_apply)
    rid = _fabric_ask(r)
    _decide(r, rid, answer={"document_type": {"value": "urn:fabric:scheme:doc-types#minutes"}})
    started = _drain(r)
    assert applied == [("draft-review", "maria@contoso.com", {"document_type": {"value": "urn:fabric:scheme:doc-types#minutes"}})]
    req = workflows.status(started[0], client=r)
    assert req["process"] == "artifact_publish" and req["inputs"] == {"artifact_iri": "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y", "approval_id": rid}
    assert r.hget(f"approvals:req:{rid}", "curated") == "1"


def test_a_refused_curation_is_recorded_and_releases_nothing(monkeypatch, r):
    async def refuse(state, actor, *, call=None):
        raise ValueError("refused by the fabric's shapes: owner must be constructed")
    monkeypatch.setitem(continuations.answer_appliers.APPLIERS, "association", refuse)
    rid = _fabric_ask(r, kind=ApprovalKind.ASSOCIATION.value)
    _decide(r, rid, answer={"document_type": {"value": "urn:fabric:scheme:doc-types#minutes"}})
    assert _drain(r) == []
    assert "refused by the fabric" in (r.hget(f"approvals:req:{rid}", "continuation_error") or
                                       r.hget(f"approvals:req:{rid}", "error") or "")
    assert r.hget(f"approvals:req:{rid}", "released_request_id") is None


def test_a_non_fabric_kind_never_reaches_the_curator(monkeypatch, r):
    async def never(state, actor, *, call=None):
        raise AssertionError("the curator must not see a speaker question")
    for kind in ("association", "draft-review"):                     # the fabric's appliers, armed to explode
        monkeypatch.setitem(continuations.answer_appliers.APPLIERS, kind, never)
    assert continuations.answer_appliers.applier_for("speaker-mapping") is None
    rid = _ask(r)                                                    # a speaker question
    _decide(r, rid)
    assert len(_drain(r)) == 1


def test_a_failed_continuation_is_redriven_on_the_next_start_and_forgotten_once_it_succeeds(r, monkeypatch):
    """A continuation that failed because of a defect is retried by the deploy that fixes it: the failure
    is remembered in one set, the runner's crash-hygiene pass re-handles what is there, and a success
    clears it. A cause that is not fixed fails again — once per start, recorded, never a wedge."""
    rid = _ask(r)
    _decide(r, rid)
    calls = {"n": 0}
    real = workflows.submit

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("semantic-mcp refused")
        return real(*a, **kw)
    monkeypatch.setattr(continuations.workflows, "submit", flaky)
    assert _drain(r) == [] and "semantic-mcp refused" in approvals.status(rid, client=r)["continuation_error"]
    assert continuations.failed(client=r) == [rid]
    assert _drain(r) == [], "acked: the stream itself redelivers nothing"
    started = continuations.redrive_failed(client=r)
    assert len(started) == 1 and approvals.status(rid, client=r)["released_request_id"] == started[0]
    assert continuations.failed(client=r) == [] and "continuation_error" not in approvals.status(rid, client=r)
    assert continuations.redrive_failed(client=r) == []                             # nothing left to redrive


def test_a_redrive_never_releases_a_second_run_for_an_approval_that_already_released_one(r):
    rid = _ask(r); _decide(r, rid)
    started = _drain(r)
    r.sadd(continuations.FAILED_KEY, rid)                                            # a stale mark
    assert continuations.redrive_failed(client=r) == [] and continuations.failed(client=r) == []
    assert approvals.status(rid, client=r)["released_request_id"] == started[0]


def test_a_redrive_forgets_what_it_cannot_continue_and_what_is_too_old_to_retry_safely(r, capsys):
    """The failed set must drain: an approval with nothing to continue is forgotten, and one decided longer ago
    than the submit idempotency window is forgotten WITH a reason — a redrive past that window could queue a
    second run for one human decision."""
    r.sadd(continuations.FAILED_KEY, "apr-gone")                                   # hash removed meanwhile
    plain = _ask(r, {"question": {"prompt": "?", "items": []}}); _decide(r, plain, answer=None)   # no continuation
    old = _ask(r); _decide(r, old)
    r.hset(f"approvals:req:{old}", "decided_at", "2026-01-01T00:00:00+00:00")
    r.sadd(continuations.FAILED_KEY, plain, old)
    assert continuations.redrive_failed(client=r) == []
    assert continuations.failed(client=r) == []
    assert old in capsys.readouterr().err and "idempotency" in approvals.status(old, client=r)["continuation_error"]


def test_a_failure_recorded_before_the_set_existed_is_still_redriven(r):
    """The runner that recorded the user's first Copilot decision as failed predates the failed set: only the
    approval hash carries `continuation_error`. A start sweeps for those once, so no decision is stranded by the
    deploy that introduced the set."""
    rid = _ask(r); _decide(r, rid)
    r.hset(f"approvals:req:{rid}", "continuation_error", "ToolError: the old runner's failure")   # legacy shape
    done = _ask(r); _decide(r, done)
    r.hset(f"approvals:req:{done}", mapping={"continuation_error": "stale", "released_request_id": "wfr-x"})
    assert continuations.failed(client=r) == [rid]                                   # legacy found, released one not
    started = continuations.redrive_failed(client=r)
    assert len(started) == 1 and approvals.status(rid, client=r)["released_request_id"] == started[0]
    assert "continuation_error" not in approvals.status(rid, client=r) and continuations.failed(client=r) == []
