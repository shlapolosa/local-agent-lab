"""src/lab/platform/staged_registry.py branches beyond the INTEGRATION test — OFFLINE via tests/_fakes.FakeRedis
(which emulates the two Lua scripts) routed through the lab.platform.redis_client seam."""
import json
import logging


import redis

from fixtures.fakes import FakeRedis, patched_client, run_script
from lab.platform import staged_registry as sr


def obj(canonical, eid="el-1", view="view-A"):
    return dict(canonical=canonical, name="N", type="ApplicationComponent", domain="d", element_id=eid, view=view)


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    raise AssertionError(f"expected {exc.__name__}")


def _logs(fn):
    records = []
    h = logging.Handler(); h.emit = records.append
    sr.log.addHandler(h)
    try:
        out = fn()
    finally:
        sr.log.removeHandler(h)
    return out, [r.getMessage() for r in records]


def test_key_and_ttl_validation():
    for bad in ("", None, 3):
        _raises(ValueError, sr.key, bad)
    with patched_client(FakeRedis()):
        _raises(ValueError, sr.stage, "wl", [obj("c")], ttl_days=0)


def test_stage_lifecycle_on_fake():
    with patched_client(FakeRedis()) as r:
        assert sr.stage("wl", [obj("a"), obj("b", "el-2")]) == 2
        assert r.ttl[sr.key("wl")] == sr.DEFAULT_TTL_DAYS * 86400
        assert sr.stage("wl", [obj("a", "el-DUP", "view-B")]) == 1
        e = sr.lookup("wl", "a")
        assert e["element_id"] == "el-1" and e["views"] == ["view-A", "view-B"] and e["status"] == "staged"
        assert sr.stage("wl", [obj("a", view="view-B")]) == 0
        # empty stage only refreshes the TTL of an existing hash (and is a no-op otherwise)
        assert sr.stage("wl", [], ttl_days=1) == 0 and r.ttl[sr.key("wl")] == 86400
        assert sr.stage("other", None) == 0 and sr.key("other") not in r.ttl
        assert sr.mark_imported("wl", ["a"]) == 1 and sr.lookup("wl", "a")["status"] == "imported"
        assert sr.stage("wl", [obj("a", "el-NEW", "view-C")]) == 0, "imported entries are never touched"
        assert sr.mark_imported("wl", [None, ""]) == 0, "explicit empty list -> nothing"
        assert sr.mark_imported("wl") == 1 and sr.mark_imported("wl") == 0
        lst = sr.list_objects("wl")
        assert [x["canonical"] for x in lst] == ["a", "b"] and all(x["imported_at"] for x in lst)
        assert sr.lookup_many("wl", ["a", "zz", "b", "a", None]) .keys() == {"a", "b"}
        assert sr.clear("wl") is True and sr.clear("wl") is False


def test_validation_messages():
    with patched_client(FakeRedis()):
        _raises(ValueError, sr.stage, "wl", ["nope"])
        _raises(ValueError, sr.stage, "wl", [{"canonical": "c", "name": " "}])


def test_undecodable_entries_are_skipped_with_a_warning():
    with patched_client(FakeRedis()) as r:
        r.hset(sr.key("wl"), mapping={"good": json.dumps(obj("good") | {"status": "staged", "staged_at": "t"}),
                                      "bad": "{broken", "empty": ""})
        (one, logs) = _logs(lambda: sr.lookup("wl", "bad"))
        assert one is None and any("undecodable" in m for m in logs)
        assert sr.lookup("wl", "empty") is None
        many, _ = _logs(lambda: sr.lookup_many("wl", ["good", "bad", "empty"]))
        assert list(many) == ["good"]
        lst, _ = _logs(lambda: sr.list_objects("wl"))
        assert [e["canonical"] for e in lst] == ["good"]


def test_reads_degrade_writes_raise_when_redis_fails():
    r = FakeRedis()
    r.fail("hget"); r.fail("hmget", OSError("socket")); r.fail("hgetall"); r.fail("eval"); r.fail("delete")
    with patched_client(r):
        out, logs = _logs(lambda: (sr.lookup("wl", "x"), sr.lookup_many("wl", ["x"]), sr.list_objects("wl")))
        assert out == (None, {}, []) and len(logs) == 3 and all("treating as" in m for m in logs)
        _raises(redis.ConnectionError, sr.stage, "wl", [obj("x")])
        _raises(redis.ConnectionError, sr.mark_imported, "wl")
        _raises(redis.ConnectionError, sr.clear, "wl")


def test_cli():
    fake = FakeRedis()
    with patched_client(fake):
        sr.stage("wl-cli", [obj("api gateway (kong)", "el-kong")])
        code, out, _ = run_script("src/lab/platform/staged_registry.py", ["list", "wl-cli"])
        assert code == 0 and "staged" in out and "el-kong" in out and "views=view-A" in out
        code, out, _ = run_script("src/lab/platform/staged_registry.py", ["imported", "wl-cli", "api gateway (kong)"])
        assert out.strip().endswith("1")
        code, out, _ = run_script("src/lab/platform/staged_registry.py", ["imported", "wl-cli"])
        assert out.strip().endswith("0")
        code, out, _ = run_script("src/lab/platform/staged_registry.py", ["clear", "wl-cli"])
        assert out.strip().endswith("True")
        code, _, _ = run_script("src/lab/platform/staged_registry.py", ["list"])
        assert isinstance(code, str) and "workload:<id>:objects" in code


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
