"""Remaining branches of src/lab/platform/runlog.py and src/lab/platform/redis_client.py (the pooled-client seam).
OFFLINE: tests/_fakes.FakeRedis through `client=` / the redis_client seam."""
import io
import json
from contextlib import redirect_stdout


from fixtures.fakes import FakeRedis, capture, patched_client, run_script
from lab.platform import redis_client, runlog


def test_node_tolerates_corrupt_nodes_and_missing_start():
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    r.hset("run:r1", mapping={"nodes": "{not json", "t0": "x"})
    _, out, _ = capture(runlog.node, "r1", "ba", "done", client=r)      # no start entry -> no elapsed
    nodes = json.loads(r.h["run:r1"]["nodes"])
    assert len(nodes) == 1 and nodes[0]["status"] == "done" and "elapsed" not in nodes[0]["attrs"]
    assert out.strip() == "[run r1] ba done"
    _, out, _ = capture(runlog.node, "r1", "ba", "fail", error="E1", client=r)
    assert out.strip() == "[run r1] ba FAIL: E1"
    _, out, _ = capture(runlog.node, "r1", "ba", "fail", elapsed=1.5, client=r)
    assert out.strip() == "[run r1] ba FAIL 1.5s"


def test_span_node_success_records_done_with_elapsed():
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    capture(runlog.start, "r-ok", input="x", client=r)
    with redirect_stdout(io.StringIO()):
        with runlog.span_node("r-ok", "architect", client=r, view="A"):
            pass
    nodes = json.loads(r.h["run:r-ok"]["nodes"])
    assert [n["status"] for n in nodes] == ["start", "done"] and nodes[0]["attrs"] == {"view": "A"}
    assert nodes[1]["attrs"]["elapsed"] >= 0 and r.h["run:r-ok"]["node_status"] == "done"


def test_update_without_fields_is_a_noop():
    r = FakeRedis()
    runlog.update("r2", client=r, a=None)
    assert r.calls == {}, "nothing to write -> Redis untouched"


def test_finish_without_t0_and_readers():
    runlog._RETRY_AT = 0.0
    r = FakeRedis()
    _, out, _ = capture(runlog.finish, "r3", "failed", error="bad", client=r)      # never started
    assert out.strip() == "[run r3] FAILED — bad" and "elapsed" not in r.h["run:r3"]
    # _parse: corrupt nodes -> []; non-numeric t0/elapsed left as-is
    r.hset("run:r3", mapping={"nodes": "[oops", "t0": "n/a", "elapsed": "n/a"})
    g = runlog.get("r3", client=r)
    assert g["nodes"] == [] and g["t0"] == "n/a" and g["elapsed"] == "n/a"
    assert runlog.get("unknown", client=r) == {}
    # active(): an id whose hash expired is pruned from the set
    r.sadd("runs:active", "ghost", "r3")
    assert [h["status"] for h in runlog.active(client=r)] == ["failed"]
    assert r.s["runs:active"] == {"r3"}
    # recent(): ids without a hash are dropped
    r.l["runs:recent"] = ["ghost", "r3"]
    assert [h["status"] for h in runlog.recent(5, client=r)] == ["failed"]


def test_cli():
    runlog._RETRY_AT = 0.0
    fake = FakeRedis()
    with patched_client(fake):
        capture(runlog.start, "cli-1", input="d.vsdx", client=fake)
        capture(runlog.finish, "cli-1", "done", client=fake)
        capture(runlog.start, "cli-2", input="e.vsdx", client=fake)
        code, out, _ = run_script("src/lab/platform/runlog.py", ["list"])
        lines = [l for l in out.splitlines() if l.startswith("cli-")]
        assert code == 0 and lines[0].startswith("cli-2  running") and lines[1].startswith("cli-1  done")
        code, out, _ = run_script("src/lab/platform/runlog.py", [])
        assert "cli-1" in out
        code, out, _ = run_script("src/lab/platform/runlog.py", ["show", "cli-1"])
        assert json.loads(out)["status"] == "done"
        code, _, _ = run_script("src/lab/platform/runlog.py", ["show"])
        assert isinstance(code, str) and "runs:active" in code


# ---------------------------------------------------------------- src/lab/platform/redis_client.py leftovers
def test_reset_survives_a_close_that_raises():
    class Bad:
        def close(self):
            raise RuntimeError("already closed")
    redis_client.reset()
    redis_client._CLIENTS["redis://bad"] = Bad()
    redis_client.reset()
    assert redis_client._CLIENTS == {}


def test_double_checked_lock_second_reader():
    """Two threads racing for the SAME url: the one that loses the lock re-reads the cache and
    returns the client the winner created (the `if r is None` inside the lock is False)."""
    redis_client.reset()
    url = "redis://127.0.0.1:6390/7"
    real_lock, made = redis_client._LOCK, []

    class Gate:
        """A lock whose acquire lets a "winner" plant the client before the caller re-checks the cache
        (the client is built directly — going through client() here would re-enter this gate)."""
        def __enter__(self):
            real_lock.acquire()
            if not made:
                import redis
                made.append(redis.Redis.from_url(url, decode_responses=True))
                redis_client._CLIENTS[url] = made[0]              # what the winning thread does
        def __exit__(self, *a):
            real_lock.release()
    redis_client._LOCK = Gate()
    try:
        assert redis_client.client(url) is made[0]
    finally:
        redis_client._LOCK = real_lock
        redis_client.reset()


def test_script_mode_import_branch():
    code, _, err = run_script("src/lab/platform/redis_client.py", [])
    assert code == 0 and err == ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
