"""A run that hands over to another is watched on ONE page.

Measured 23 Sep 2026: a screening run finished, its criticality approval released a design run,
and the page the person was watching simply stopped. Nothing was wrong — the work had moved to a
run with its own trace — but from the only surface they had, an approval they had just given
looked like it had done nothing. They asked why it was not progressing; it was.

So the handover is DATA on the run (`continued_as`, written where the handover happens) and the
page follows it. The live view still knows only the schema: it renders whatever processes the
chain names and has no idea what a "screening" or a "design" is.
"""
from fixtures.fakes import FakeRedis
from lab.platform import runlog
from lab.substrate.live import server as live


def _run(redis, run_id, process, status="running", **fields):
    runlog.start(run_id, process=process, input="x", client=redis, **fields)
    if status != "running":
        runlog.finish(run_id, status, client=redis)
    return run_id


def test_a_run_with_no_continuation_is_a_chain_of_one():
    redis = FakeRedis()
    _run(redis, "t1", "use_case_screening")
    chain = live.chain("t1", client=redis)
    assert [c["run"] for c in chain] == ["t1"]


def test_the_chain_follows_the_handover_forward():
    redis = FakeRedis()
    _run(redis, "t1", "use_case_screening", status="done")
    _run(redis, "t2", "use_case_design")
    runlog.update("t1", continued_as="t2", continued_process="use_case_design", client=redis)
    chain = live.chain("t1", client=redis)
    assert [c["run"] for c in chain] == ["t1", "t2"]
    assert [c["process"] for c in chain] == ["use_case_screening", "use_case_design"]


def test_opening_the_CHILD_shows_the_whole_chain_too():
    """A link lands a person on the design run. They should still see where it came from —
    otherwise the second page has the same amnesia as the first."""
    redis = FakeRedis()
    _run(redis, "t1", "use_case_screening", status="done")
    _run(redis, "t2", "use_case_design")
    runlog.update("t1", continued_as="t2", client=redis)
    runlog.update("t2", continued_from="t1", client=redis)
    assert [c["run"] for c in live.chain("t2", client=redis)] == ["t1", "t2"]


def test_a_continuation_that_has_not_started_yet_is_still_shown():
    """The gap between an approval releasing a run and a consumer picking it up is exactly when a
    person is staring at the page. Saying nothing there is what this fixes."""
    redis = FakeRedis()
    _run(redis, "t1", "use_case_screening", status="done")
    runlog.update("t1", continued_as="wfr-notyet", continued_process="use_case_design",
                  client=redis)
    chain = live.chain("t1", client=redis)
    assert len(chain) == 2
    assert chain[1]["process"] == "use_case_design" and chain[1]["status"] == "queued"


def test_a_cycle_cannot_hang_the_page():
    """Defensive: two runs naming each other must terminate. A watcher page that never returns is
    worse than one that stops early."""
    redis = FakeRedis()
    _run(redis, "t1", "a")
    _run(redis, "t2", "b")
    runlog.update("t1", continued_as="t2", client=redis)
    runlog.update("t2", continued_as="t1", client=redis)
    assert len(live.chain("t1", client=redis)) <= live.MAX_CHAIN


def test_each_link_carries_what_the_page_renders_and_nothing_more():
    redis = FakeRedis()
    _run(redis, "t1", "use_case_screening")
    assert set(live.chain("t1", client=redis)[0]) == {
        "run", "process", "status", "subject", "elapsed", "error", "steps", "node"}


# ------------------------------------------------- the run points at what it is waiting on

def test_a_run_waiting_on_an_approval_says_where_to_go(monkeypatch):
    """A paused run is the single most common place a person is stuck, and the page said nothing.
    The id is already on the run — it only had to be offered."""
    monkeypatch.setattr(live.config, "REVIEW_APP_URL", "https://review.example")
    redis = FakeRedis()
    runlog.start("t1", process="p", input="x", client=redis)
    runlog.finish("t1", "done", client=redis, approval_id="apr-123")
    f = live.frame(runlog.get("t1", client=redis))
    assert f["approval"]["id"] == "apr-123"
    assert f["approval"]["url"] == "https://review.example/?mode=Review&approval=apr-123"


def test_no_review_app_means_the_id_without_a_link():
    monkeypatch = None
    redis = FakeRedis()
    runlog.start("t1", process="p", input="x", client=redis)
    runlog.finish("t1", "done", client=redis, approval_id="apr-123")
    f = live.frame(runlog.get("t1", client=redis))
    assert f["approval"]["id"] == "apr-123"


def test_a_run_with_no_approval_offers_none():
    redis = FakeRedis()
    runlog.start("t1", process="p", input="x", client=redis)
    assert "approval" not in live.frame(runlog.get("t1", client=redis))


def test_a_request_id_resolves_to_the_trace_so_a_fresh_link_works():
    """A just-released run has a request id and no trace yet — which is exactly when somebody
    follows the link out of an approval. Resolving here means the link works immediately rather
    than after the consumer happens to start."""
    redis = FakeRedis()
    redis.hset("workflow:req:wfr-abc", mapping={"trace_id": "t9", "status": "running"})
    runlog.start("t9", process="p", input="x", client=redis)
    assert live.resolve("wfr-abc", client=redis) == "t9"
    assert live.resolve("t9", client=redis) == "t9"
    assert live.resolve("wfr-unknown", client=redis) == "wfr-unknown"
