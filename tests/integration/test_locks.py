"""INTEGRATION test of src/lab/platform/locks.py against the LOCAL Redis (REDIS_URL from .env; goes through
lab.platform.redis_client). Names are locktest-* and every key is cleaned up at the end. Skips (prints
"SKIP integration: redis unreachable") when no Redis answers; the offline branches live in
tests/unit/platform/test_locks_more.py."""
import os, subprocess, sys, time, threading
import redis
from lab.platform import locks
from lab.platform.locks import lock, workload_lock, LockTimeout, LockUnavailable, PREFIX


results = []


def ok(label, cond, detail=""):
    results.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")


def _live():
    try:
        r = locks._r(); r.ping(); return r
    except redis.RedisError:
        return None


def test_locks_integration():
    r = _live()
    if r is None:
        print("SKIP integration: redis unreachable"); return
    results.clear()
    print("redis:", os.environ.get("REDIS_URL"), "->", r.ping())
    N = "locktest-" + os.urandom(3).hex()
    K = PREFIX + N


    try:
        # (1) acquire/release round-trip: key present inside, gone after exit
        print("(1) round-trip")
        with lock(N, ttl=30) as lk:
            inside = r.get(K)
            ok("key holds our token inside", inside == lk.token, f"token={lk.token[:8]}")
            ok("held() true inside", lk.held() is True)
            ttl_in = r.ttl(K)
            ok("EX ttl set", 0 < ttl_in <= 30, f"ttl={ttl_in}")
        ok("key gone after exit", r.exists(K) == 0)
        ok("held() false after exit", lk.held() is False)

        # (2) contention: second lock() times out while held, succeeds after release
        print("(2) contention")
        with lock(N, ttl=30) as lk1:
            t0 = time.monotonic(); raised = False
            try:
                with lock(N, ttl=30, wait=1, poll=0.1):
                    pass
            except LockTimeout as e:
                raised = True; msg = str(e)
            dt = time.monotonic() - t0
            ok("second lock raised LockTimeout", raised, f"after {dt:.2f}s: {msg if raised else '-'}")
            ok("waited ~wait seconds", 0.9 <= dt < 2.0)
            ok("first still holds", r.get(K) == lk1.token)
        with lock(N, ttl=30, wait=1) as lk2:
            ok("acquired after release", r.get(K) == lk2.token and lk2.token != lk1.token)
        # also: a waiter actually gets it once the holder exits (thread)
        got = {}
        def waiter():
            with lock(N, ttl=30, wait=5, poll=0.05) as h:
                got["t"] = time.monotonic(); got["tok"] = h.token
        with lock(N, ttl=30):
            th = threading.Thread(target=waiter); th.start(); time.sleep(0.6); rel = time.monotonic()
        th.join(5)
        ok("waiter acquired after holder exit", "t" in got and got["t"] >= rel, f"+{got.get('t', 0) - rel:.3f}s")
        ok("key gone after waiter exit", r.exists(K) == 0)

        # (3) renew extends TTL (PTTL grows)
        print("(3) renew")
        with lock(N, ttl=5) as lk:
            time.sleep(1.2)
            before = r.pttl(K)
            ext = lk.renew(60)
            after = r.pttl(K)
            ok("renew() returned True", ext is True)
            ok("PTTL grew", after > before and after > 50_000, f"{before}ms -> {after}ms")
            ext2 = lk.renew()      # default = original ttl (5 s)
            ok("renew() default resets to ttl", ext2 is True and 0 < r.pttl(K) <= 5000, f"pttl={r.pttl(K)}ms")
        ok("key gone after exit", r.exists(K) == 0)

        # (4) wrong-token safety: overwrite key with another token; exit must NOT delete it
        print("(4) wrong-token safety")
        with lock(N, ttl=30) as lk:
            r.set(K, "someone-else", ex=30)     # simulates expiry + re-acquire by another replica
            ok("held() false once overwritten", lk.held() is False)
            ok("renew() refuses when not ours", lk.renew(60) is False)
            ok("foreign TTL untouched by renew", r.ttl(K) <= 30)
        ok("foreign lock NOT deleted at exit", r.get(K) == "someone-else")
        ok("explicit release() after exit is a no-op False", lk.release() is False)
        r.delete(K)

        # (4b) workload_lock naming
        with workload_lock("wl-locktest-1", ttl=10) as h:
            ok("workload_lock key", h.key == "lock:workload:wl-locktest-1:write" and r.exists(h.key) == 1, h.key)
        ok("workload key gone", r.exists("lock:workload:wl-locktest-1:write") == 0)

        # (5) Redis unavailable -> LockUnavailable (client kwarg + real config path in a subprocess)
        print("(5) unavailable")
        bogus = redis.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5, socket_timeout=0.5)
        try:
            with lock(N, ttl=5, wait=0, client=bogus):
                ok("entered block on bogus redis", False)
        except LockUnavailable as e:
            ok("client= bogus raises LockUnavailable", True, str(e)[:70])
        code = """
from lab.platform.locks import lock, LockUnavailable
try:
    with lock('locktest-sub', ttl=5, wait=0): print('ENTERED')
except LockUnavailable as e: print('LockUnavailable:', str(e)[:60])
"""
        env = {**os.environ, "REDIS_URL": "redis://127.0.0.1:1/0", "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
        ok("REDIS_URL bogus (subprocess) raises LockUnavailable", out.stdout.startswith("LockUnavailable"),
           out.stdout.strip() or out.stderr.strip()[-200:])

        # bad args are rejected before touching Redis
        for kw in ({"ttl": 0}, {"wait": -1}, {"poll": 0}):
            try:
                with lock(N, **kw): pass
                ok(f"rejects {kw}", False)
            except ValueError:
                ok(f"rejects {kw}", True)
    finally:
        stale = [k for k in r.scan_iter("lock:locktest-*")] + [k for k in r.scan_iter("lock:workload:wl-locktest-*")]
        if stale: r.delete(*stale)
        print("cleanup: removed", len(stale), "stale locktest keys; remaining:",
              list(r.scan_iter("lock:locktest-*")) + list(r.scan_iter("lock:workload:wl-locktest-*")))

    print(f"\n{sum(results)}/{len(results)} checks passed")
    assert all(results), f"{sum(results)}/{len(results)} checks passed"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
