"""Offline test doubles shared by the tests (not a test module itself — `tests/run.sh` and pytest only
collect `test_*.py`).

FakeRedis  the subset of redis.Redis (decode_responses=True) the Redis-backed lab modules use: strings,
           hashes, sets, lists, Streams (XADD / XGROUP CREATE / XREADGROUP / XACK / XREVRANGE /
           XPENDING) and `eval` for the lab's four Lua scripts (locks + staged_registry), emulated in
           Python. Records every call in `calls` and can be told to raise per method (`fail(...)`).
DeadRedis  every call raises redis.ConnectionError — the "Redis unreachable" double.
capture        run a callable with stdout/stderr captured -> (result, out, err).
patched_client route lab.platform.redis_client.client() to a fake for the duration of a block — the ONE seam
               every Redis-backed lab module goes through (`_r()`), so no module needs patching.
run_script     run a lab module file as `__main__` in-process (its CLI + script-mode import branch),
               argv swapped, SystemExit caught -> (exit code, stdout, stderr).
"""
import functools
import io
import json
import os
import runpy
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout

import redis

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextmanager
def patched_client(fake):
    from lab.platform import redis_client
    real = redis_client.client
    redis_client.client = lambda url=None, **kw: fake
    try:
        yield fake
    finally:
        redis_client.client = real


def run_script(relpath, argv):
    """`python <relpath> <argv…>` without a subprocess (so coverage sees it): returns (code, out, err)."""
    saved, sys.argv = sys.argv, [relpath, *argv]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            runpy.run_path(os.path.join(ROOT, relpath), run_name="__main__")
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def capture(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue(), err.getvalue()


def _op(fn):
    """Count the call and raise the configured failure (if any) before running the fake op."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        self.calls[fn.__name__] = self.calls.get(fn.__name__, 0) + 1
        exc = self.errors.get(fn.__name__)
        if exc is not None:
            raise exc
        return fn(self, *a, **kw)
    return wrapper


class FakeRedis:
    def __init__(self):
        self.kv, self.h, self.s, self.l = {}, {}, {}, {}
        self.x, self.groups = {}, {}            # stream -> [(id, fields)]; (stream, group) -> {last, pel}
        self.ttl, self.calls, self.errors = {}, {}, {}
        self._seq = 0

    def fail(self, method, exc=None):
        """Make `method` raise `exc` (default: a refused connection) until `fail(method, None)`."""
        if exc is None:
            exc = redis.ConnectionError("Error 61 connecting to 127.0.0.1:1. Connection refused.")
        if exc is False:
            self.errors.pop(method, None)
        else:
            self.errors[method] = exc

    # --- keys / strings
    def _has(self, k):
        return any(k in d for d in (self.kv, self.h, self.s, self.l, self.x))

    @_op
    def ping(self):
        return True

    @_op
    def set(self, k, v, nx=False, ex=None, **kw):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        if ex:
            self.ttl[k] = ex
        return True

    @_op
    def get(self, k):
        return self.kv.get(k)

    @_op
    def delete(self, *keys):
        n = 0
        for k in keys:
            for d in (self.kv, self.h, self.s, self.l, self.x):
                if k in d:
                    del d[k]; n += 1
            self.ttl.pop(k, None)
        return n

    @_op
    def exists(self, *keys):
        return sum(1 for k in keys if self._has(k))

    @_op
    def expire(self, k, t):
        if not self._has(k):
            return False
        self.ttl[k] = int(t)
        return True

    @_op
    def pttl(self, k):
        return self.ttl.get(k, -1) * 1000 if k in self.ttl else -1

    @_op
    def scan_iter(self, match="*"):
        import fnmatch
        for d in (self.kv, self.h, self.s, self.l, self.x):
            for k in list(d):
                if fnmatch.fnmatch(k, match):
                    yield k

    # --- hashes
    @_op
    def hset(self, k, key=None, value=None, mapping=None):
        m = dict(mapping or {})
        if key is not None:
            m[key] = value
        d = self.h.setdefault(k, {})
        new = sum(1 for f in m if f not in d)
        d.update({f: ("" if v is None else str(v)) for f, v in m.items()})
        return new

    @_op
    def hget(self, k, f):
        return self.h.get(k, {}).get(f)

    @_op
    def hgetall(self, k):
        return dict(self.h.get(k, {}))

    @_op
    def hmget(self, k, fields):
        d = self.h.get(k, {})
        return [d.get(f) for f in fields]

    @_op
    def hkeys(self, k):
        return list(self.h.get(k, {}))

    # --- sets
    @_op
    def sadd(self, k, *m):
        st = self.s.setdefault(k, set()); n = len(set(m) - st); st.update(m); return n

    @_op
    def srem(self, k, *m):
        st = self.s.setdefault(k, set()); n = len(st & set(m)); st.difference_update(m); return n

    @_op
    def smembers(self, k):
        return set(self.s.get(k, set()))

    # --- lists
    @_op
    def lrem(self, k, n, v):
        lst = self.l.setdefault(k, []); c = lst.count(v); self.l[k] = [x for x in lst if x != v]; return c

    @_op
    def lpush(self, k, v):
        self.l.setdefault(k, []).insert(0, v); return len(self.l[k])

    @_op
    def ltrim(self, k, a, b):
        self.l[k] = self.l.get(k, [])[a:b + 1]; return True

    @_op
    def lrange(self, k, a, b):
        return self.l.get(k, [])[a:b + 1]

    # --- streams
    @_op
    def xadd(self, stream, fields, **kw):
        self._seq += 1
        eid = f"{1700000000000 + self._seq}-0"
        self.x.setdefault(stream, []).append((eid, {f: str(v) for f, v in fields.items()}))
        return eid

    @_op
    def xlen(self, stream):
        return len(self.x.get(stream, []))

    @_op
    def xgroup_create(self, stream, group, id="$", mkstream=False):
        if stream not in self.x:
            if not mkstream:
                raise redis.ResponseError("ERR The XGROUP subcommand requires the key to exist")
            self.x[stream] = []
        if (stream, group) in self.groups:
            raise redis.ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups[(stream, group)] = {"last": 0 if id == "0" else len(self.x[stream]), "pel": {}}
        return True

    @_op
    def xreadgroup(self, group, consumer, streams, count=None, block=None, **kw):
        out = []
        for stream, sid in streams.items():
            g = self.groups.get((stream, group))
            if g is None:
                raise redis.ResponseError(f"NOGROUP No such key '{stream}' or consumer group '{group}'")
            entries = self.x.get(stream, [])
            if sid == ">":
                take = entries[g["last"]:][: count or None]
                for eid, _ in take:
                    g["pel"][eid] = consumer
                g["last"] += len(take)
            else:                                   # "0" / an id: this consumer's pending entries
                take = [(eid, f) for eid, f in entries if g["pel"].get(eid) == consumer][: count or None]
            if take:
                out.append([stream, [(eid, dict(f)) for eid, f in take]])
        return out

    @_op
    def xack(self, stream, group, *ids):
        g = self.groups.get((stream, group), {"pel": {}})
        return sum(1 for i in ids if g["pel"].pop(i, None) is not None)

    @_op
    def xpending(self, stream, group):
        pel = self.groups.get((stream, group), {"pel": {}})["pel"]
        return {"pending": len(pel), "min": min(pel) if pel else None, "max": max(pel) if pel else None,
                "consumers": [{"name": c, "pending": sum(1 for v in pel.values() if v == c)} for c in set(pel.values())]}

    @_op
    def xrange(self, stream, min="-", max="+", count=None):
        """Oldest-first, the way an audit log is read."""
        entries = list(self.x.get(stream, []))
        return [(eid, dict(f)) for eid, f in entries[: count or None]]

    def xrevrange(self, stream, max="+", min="-", count=None):
        entries = list(reversed(self.x.get(stream, [])))
        return [(eid, dict(f)) for eid, f in entries[: count or None]]

    # --- Lua (the lab's scripts, emulated)
    @_op
    def eval(self, script, numkeys, *args):
        keys, argv = list(args[:numkeys]), list(args[numkeys:])
        from lab.platform import locks, staged_registry
        s = script.strip()
        if s == locks.RELEASE_SCRIPT.strip():
            return self.delete.__wrapped__(self, keys[0]) if self.kv.get(keys[0]) == argv[0] else 0
        if s == locks.RENEW_SCRIPT.strip():
            if self.kv.get(keys[0]) != argv[0]:
                return 0
            self.ttl[keys[0]] = int(argv[1]); return 1
        if s == staged_registry._STAGE.strip():
            return self._stage(keys[0], int(argv[0]), argv[1:])
        if s == staged_registry._MARK_IMPORTED.strip():
            return self._mark_imported(keys[0], int(argv[0]), argv[1], argv[2:])
        raise NotImplementedError("FakeRedis.eval: unknown script")

    def _stage(self, key, ttl, raws):
        written = 0
        for raw in raws:
            new = json.loads(raw); d = self.h.setdefault(key, {}); cur = d.get(new["canonical"])
            if cur is None:
                d[new["canonical"]] = raw; written += 1
            else:
                old = json.loads(cur)
                if old.get("status") != "imported":
                    views = old.get("views") or []
                    if new["view"] not in views:
                        old["views"] = views + [new["view"]]; d[new["canonical"]] = json.dumps(old); written += 1
        self.ttl[key] = ttl
        return written

    def _mark_imported(self, key, ttl, at, fields):
        d = self.h.get(key, {}); n = 0
        for f in (fields or list(d)):
            cur = d.get(f)
            if cur is not None:
                e = json.loads(cur)
                if e.get("status") != "imported":
                    e.update(status="imported", imported_at=at); d[f] = json.dumps(e); n += 1
        if key in self.h:
            self.ttl[key] = ttl
        return n

    # --- pipeline: record, then replay on execute()
    def pipeline(self):
        fake = self

        class P:
            def __init__(self): self.ops = []
            def __getattr__(self, name):
                def rec(*a, **kw): self.ops.append((name, a, kw)); return self
                return rec
            def execute(self):
                return [getattr(fake, n)(*a, **kw) for n, a, kw in self.ops]
        return P()


class DeadRedis:
    """Every call raises like a refused connection; counts attempts so a retry latch is observable."""

    def __init__(self):
        self.attempts = 0

    def __getattr__(self, name):
        def boom(*a, **kw):
            self.attempts += 1
            raise redis.ConnectionError("Error 61 connecting to 127.0.0.1:1. Connection refused.")
        return boom


__all__ = ["FakeRedis", "DeadRedis", "capture", "patched_client", "run_script", "ROOT"]
