"""src/lab/platform/locks.py branches the INTEGRATION test (tests/integration/test_locks.py) does not reach — all OFFLINE
through tests/_fakes.FakeRedis (`client=` seam) and the redis_client seam."""
import logging


import redis

from fixtures.fakes import FakeRedis, patched_client
from lab.platform import locks
from lab.platform.locks import LockTimeout, LockUnavailable, lock, workload_lock


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}")


def test_round_trip_and_handle_on_fake():
    r = FakeRedis()
    with lock("wl-x", ttl=30, client=r) as lk:
        assert r.kv["lock:wl-x"] == lk.token and r.ttl["lock:wl-x"] == 30
        assert lk.held() is True
        assert lk.renew(60) is True and r.ttl["lock:wl-x"] == 60
        assert lk.renew() is True and r.ttl["lock:wl-x"] == 30
        assert repr(lk).startswith("LockHandle('wl-x', token=") and "ttl=30" in repr(lk)
    assert "lock:wl-x" not in r.kv and lk.held() is False and lk.release() is False


def test_argument_validation():
    r = FakeRedis()
    for bad in ("", None, 5):
        _raises(ValueError, lambda: lock(bad, client=r).__enter__())
    _raises(ValueError, lambda: workload_lock(""))
    with lock("v", client=r) as lk:
        _raises(ValueError, lk.renew, 0)
        _raises(ValueError, lk.renew, -3)


def test_contention_timeout_and_takeover():
    r = FakeRedis()
    with lock("c", ttl=30, client=r) as first:
        e = _raises(LockTimeout, lambda: lock("c", ttl=30, wait=0.05, poll=0.01, client=r).__enter__())
        assert "still held" in str(e) and "attempts" in str(e)
        assert r.kv["lock:c"] == first.token
        # someone else takes over (our key expired + re-acquired): exit must NOT delete theirs
        r.kv["lock:c"] = "theirs"
        assert first.held() is False and first.renew() is False
    assert r.kv["lock:c"] == "theirs"
    r.delete("lock:c")
    with lock("c", ttl=30, wait=0, client=r) as lk:                 # wait=0: one attempt, free -> ok
        assert lk.held()


def test_unavailable_paths():
    r = FakeRedis()
    r.fail("set")
    _raises(LockUnavailable, lambda: lock("u", client=r).__enter__())
    r.fail("set", False)
    with lock("u", client=r) as lk:
        r.fail("eval")
        _raises(LockUnavailable, lk.renew)
        r.fail("get", redis.TimeoutError("slow"))
        _raises(LockUnavailable, lk.held)
        # release at exit swallows the outage (TTL bounds the key) — logged, never raised
    assert r.kv.get("lock:u") is not None, "could not release: key left to expire by ttl"
    r.fail("eval", False)
    # a foreign/expired key at exit is logged, not raised
    with lock("w", ttl=5, client=r) as lk:
        r.delete("lock:w")
    assert lk.release() is False


def test_uses_shared_pool_by_default():
    fake = FakeRedis()
    with patched_client(fake):
        with workload_lock("wl-1", ttl=10) as lk:
            assert lk.key == "lock:workload:wl-1:write" and fake.kv[lk.key] == lk.token
        assert lk.key not in fake.kv


def test_script_mode_import_branch():
    from fixtures.fakes import run_script
    code, _, err = run_script("src/lab/platform/locks.py", [])
    assert code == 0 and err == ""


def test_release_warning_is_logged():
    r = FakeRedis()
    records = []
    h = logging.Handler(); h.emit = records.append
    locks.log.addHandler(h)
    try:
        with lock("lg", client=r):
            r.kv["lock:lg"] = "other"
        r.fail("eval")
        with lock("lg2", client=r):
            pass
    finally:
        locks.log.removeHandler(h)
    msgs = [rec.getMessage() for rec in records]
    assert any("not ours at exit" in m for m in msgs) and any("unreachable at release" in m for m in msgs), msgs


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
