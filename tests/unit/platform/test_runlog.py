"""src/lab/platform/runlog.py through the `client=` seam. OFFLINE: an in-memory fake covers the Redis subset
runlog uses; a raising client exercises the retry-after latch (review A-F13: a Redis blip must not
disable the Runs board for the life of the process)."""
import io
import json
import time
from contextlib import redirect_stdout


from lab.platform import runlog


from fixtures.fakes import DeadRedis, FakeRedis, capture as _quiet  # (tests/fixtures/fakes.py)


def test_start_node_finish_via_client():
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    _, out, _ = _quiet(runlog.start, "run-1", input="d.vsdx", trace_id="t1", mermaid="graph TD", client=r)
    assert "[run run-1] started visio_to_archimate input=d.vsdx trace=t1" in out
    h = r.h["run:run-1"]
    assert h["status"] == "running" and h["nodes"] == "[]" and h["mermaid"] == "graph TD"
    assert "run-1" in r.s["runs:active"] and r.ttl["run:run-1"] == runlog.TTL_S

    _quiet(runlog.node, "run-1", "ba", "start", client=r)
    time.sleep(0.01)
    _quiet(runlog.node, "run-1", "ba", "done", client=r)
    nodes = json.loads(r.h["run:run-1"]["nodes"])
    assert [n["status"] for n in nodes] == ["start", "done"] and nodes[1]["name"] == "ba"
    assert nodes[1]["attrs"]["elapsed"] >= 0                     # derived from the start entry
    assert r.h["run:run-1"]["node"] == "ba" and r.h["run:run-1"]["node_status"] == "done"

    _quiet(runlog.update, "run-1", request_id="wfr-1", client=r)
    assert r.h["run:run-1"]["request_id"] == "wfr-1"

    got = runlog.get("run-1", client=r)
    assert got["status"] == "running" and isinstance(got["nodes"], list) and isinstance(got["elapsed"], float)
    assert [x["run_id"] for x in runlog.active(client=r)] == ["run-1"]

    _, out, _ = _quiet(runlog.finish, "run-1", "done", approval_id="apr-1", client=r)
    assert "[run run-1] DONE" in out
    h = r.h["run:run-1"]
    assert h["status"] == "done" and h["approval_id"] == "apr-1" and float(h["elapsed"]) >= 0
    assert "run-1" not in r.s["runs:active"] and r.l["runs:recent"] == ["run-1"]
    assert [x["run_id"] for x in runlog.recent(client=r)] == ["run-1"]
    assert runlog.active(client=r) == []


def test_span_node_records_failure():
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    _quiet(runlog.start, "run-2", input="x", client=r)
    try:
        with redirect_stdout(io.StringIO()):
            with runlog.span_node("run-2", "architect", client=r):
                raise RuntimeError("boom")
    except RuntimeError:
        pass
    nodes = json.loads(r.h["run:run-2"]["nodes"])
    assert nodes[-1]["status"] == "fail" and nodes[-1]["attrs"]["error"].startswith("RuntimeError: boom")


def test_error_text_is_the_one_phrasing_of_a_failure():
    assert runlog.error_text(ValueError("bad diagram")) == "ValueError: bad diagram"
    long = runlog.error_text(RuntimeError("x" * 900))
    assert long.startswith("RuntimeError: ") and len(long) == len("RuntimeError: ") + runlog.ERROR_CHARS
    assert runlog.error_text(KeyError("k")) == "KeyError: 'k'"     # whatever str() gives, nothing more


def test_finish_from_closes_a_run_the_same_way_for_every_host():
    """ONE implementation of "the run is over" (host, DevUI, any future host): an exception fails it,
    a `fail` NODE fails it even when nothing raised, and the artifacts ride along either way."""
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    _quiet(runlog.start, "fin-ok", input="x", client=r)
    assert _quiet(runlog.finish_from, "fin-ok", client=r, approval_id="apr-9",
                  xml_ref="art://x/m.xml", xlsx_ref=None)[0] == "done"
    h = r.h["run:fin-ok"]
    assert h["status"] == "done" and h["approval_id"] == "apr-9" and h["xml_ref"] == "art://x/m.xml"
    assert "xlsx_ref" not in h                                   # None fields are dropped, as in finish()

    _quiet(runlog.start, "fin-raise", input="x", client=r)
    assert _quiet(runlog.finish_from, "fin-raise", RuntimeError("gateway down"), client=r)[0] == "failed"
    assert r.h["run:fin-raise"]["error"] == "RuntimeError: gateway down"

    # a node failed but the call itself returned (Agent Framework can surface an executor error as
    # an event) — the run is still a failure, and it says which node's error
    _quiet(runlog.start, "fin-node", input="x", client=r)
    _quiet(runlog.node, "fin-node", "ba", "fail", error="ValueError: bad diagram", client=r)
    assert _quiet(runlog.finish_from, "fin-node", client=r, approval_id="apr-8")[0] == "failed"
    assert r.h["run:fin-node"]["error"] == "ValueError: bad diagram"
    assert r.h["run:fin-node"]["approval_id"] == "apr-8"         # whatever it produced is still linked

    # a fail node with no error attribute still fails the run
    _quiet(runlog.start, "fin-bare", input="x", client=r)
    _quiet(runlog.node, "fin-bare", "ba", "fail", client=r)
    assert _quiet(runlog.finish_from, "fin-bare", client=r)[0] == "failed"
    assert r.h["run:fin-bare"]["error"] == "node failed"


def test_bad_statuses_rejected():
    for call in (lambda: runlog.node("r", "n", "nope"), lambda: runlog.finish("r", "running")):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


def test_retry_after_latch():
    """First failure -> one stderr notice, print-only for RETRY_AFTER_S; then Redis is tried again."""
    runlog._RETRY_AT = 0.0
    dead = DeadRedis()
    _, out, err = _quiet(runlog.start, "run-3", input="x", client=dead)
    assert dead.attempts == 1 and "redis unavailable" in err and "[run run-3] started" in out
    assert runlog._RETRY_AT > time.time() and runlog._RETRY_AT <= time.time() + runlog.RETRY_AFTER_S + 1
    _, out, err = _quiet(runlog.node, "run-3", "ba", "start", client=dead)
    _, _, _ = _quiet(runlog.finish, "run-3", "failed", error="e", client=dead)
    assert dead.attempts == 1, "inside the retry window Redis must not be touched"
    assert err == "" and "[run run-3] ba" in out, "stdout progress continues; no repeated notice"
    assert runlog.get("run-3", client=dead) == {}
    # the window elapses -> the next call tries Redis again (a healthy client now succeeds)
    runlog._RETRY_AT = time.time() - 1
    ok = FakeRedis()
    _quiet(runlog.start, "run-4", input="y", client=ok)
    assert "run:run-4" in ok.h and runlog._RETRY_AT == 0.0, "success clears the latch"
    # and a failure after that re-arms it (not a permanent flag either way)
    _, _, err = _quiet(runlog.update, "run-4", k="v", client=dead)
    assert dead.attempts == 2 and "redis unavailable" in err and runlog._RETRY_AT > time.time()
    runlog._RETRY_AT = 0.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [PASS] {name}")
    print("test_runlog: ALL PASSED")
