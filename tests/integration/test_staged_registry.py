"""INTEGRATION test of src/lab/platform/staged_registry.py against the LOCAL Redis (REDIS_URL from .env; goes
through lab.platform.redis_client). Skips (prints "SKIP integration: redis unreachable") when no Redis
answers; the offline branches live in tests/unit/platform/test_staged_registry_more.py."""
import json
import os
import subprocess
import sys
import uuid

from lab.platform import staged_registry as sr

import redis


def obj(canonical, name, typ, domain, eid, view):
    return dict(canonical=canonical, name=name, type=typ, domain=domain, element_id=eid, view=view)


def _live():
    try:
        r = sr._r(); r.ping(); return r
    except redis.RedisError:
        return None


def test_staged_registry_integration():
    r = _live()
    if r is None:
        print("SKIP integration: redis unreachable"); return
    wl = f"wltest-{uuid.uuid4().hex[:8]}"
    k = sr.key(wl)
    assert k == f"workload:{wl}:objects", k



    try:
        sr.clear(wl)
        # 1) stage 3 objects from view A
        n = sr.stage(wl, [
            obj("applicationcomponent|api gateway (kong)", "API Gateway (Kong)", "ApplicationComponent", "integration", "el-kong-1", "view-A"),
            obj("node|aks cluster", "AKS Cluster", "Node", "platform", "el-aks-1", "view-A"),
            obj("applicationservice|token service", "Token Service", "ApplicationService", "identity", "el-tok-1", "view-A"),
        ])
        assert n == 3, n
        ttl = r.ttl(k)
        assert 14 * 86400 - 60 < ttl <= 14 * 86400, ttl
        print("1) staged 3, ttl =", ttl)

        # 2) re-stage one from view B with a DIFFERENT element_id -> first id kept, views grew
        n = sr.stage(wl, [obj("applicationcomponent|api gateway (kong)", "API Gateway (Kong)", "ApplicationComponent",
                              "integration", "el-kong-DUP", "view-B")], ttl_days=7)
        assert n == 1, n
        e = sr.lookup(wl, "applicationcomponent|api gateway (kong)")
        assert e["element_id"] == "el-kong-1", e
        assert e["views"] == ["view-A", "view-B"], e
        assert e["view"] == "view-A" and e["status"] == "staged", e
        assert r.ttl(k) <= 7 * 86400, r.ttl(k)  # TTL refreshed by the write
        print("2) re-stage kept element_id:", e["element_id"], "views:", e["views"], "ttl now", r.ttl(k))

        # 2b) same view again -> nothing written (idempotent), still 1 entry
        assert sr.stage(wl, [obj("applicationcomponent|api gateway (kong)", "x", "y", "z", "el-other", "view-B")]) == 0
        assert sr.lookup(wl, "applicationcomponent|api gateway (kong)")["views"] == ["view-A", "view-B"]
        print("2b) idempotent re-stage of same view wrote 0")

        # 3) lookup / lookup_many
        assert sr.lookup(wl, "nope") is None
        m = sr.lookup_many(wl, ["node|aks cluster", "nope", "applicationservice|token service", "node|aks cluster"])
        assert set(m) == {"node|aks cluster", "applicationservice|token service"}, m
        assert m["node|aks cluster"]["element_id"] == "el-aks-1"
        assert sr.lookup_many(wl, []) == {}
        print("3) lookup_many ->", sorted(m))

        # 4) mark_imported one, then all
        assert sr.mark_imported(wl, ["node|aks cluster"]) == 1
        e = sr.lookup(wl, "node|aks cluster")
        assert e["status"] == "imported" and e.get("imported_at"), e
        # imported entries are never overwritten by a later stage
        assert sr.stage(wl, [obj("node|aks cluster", "AKS", "Node", "platform", "el-aks-NEW", "view-C")]) == 0
        e2 = sr.lookup(wl, "node|aks cluster")
        assert e2 == e, (e, e2)
        assert sr.mark_imported(wl) == 2          # remaining two flipped
        assert sr.mark_imported(wl) == 0          # nothing left to flip
        assert sr.mark_imported(wl, ["unknown"]) == 0
        assert sr.mark_imported(wl, []) == 0
        print("4) imported one then all; imported entry untouched by re-stage")

        # 5) list
        lst = sr.list_objects(wl)
        assert len(lst) == 3 and all(x["status"] == "imported" for x in lst), lst
        print("5) list_objects:")
        for x in lst:
            print("   ", json.dumps(x))

        # 6) validation
        for bad in [{"canonical": "c"}, "str", {**obj("c", "n", "t", "d", "", "v")}]:
            try:
                sr.stage(wl, [bad]); raise AssertionError("expected ValueError")
            except ValueError as ex:
                pass
        assert sr.stage(wl, []) == 0
        print("6) validation raises ValueError on incomplete objects; empty stage -> 0")

        # 7) clear
        assert sr.clear(wl) is True
        assert sr.clear(wl) is False
        assert sr.list_objects(wl) == [] and sr.lookup(wl, "x") is None
        print("7) clear ->", r.exists(k) == 0)
    finally:
        r.delete(k)
        left = list(r.scan_iter("workload:wltest-*"))
        assert not left, left
        print("cleanup ok, no wltest keys remain")

    # 8) reads never raise when Redis is unreachable; writes do
    code = r'''
import os, sys, logging; logging.basicConfig(level=logging.WARNING, format="LOG %(message)s")
from lab.platform import staged_registry as sr
print("lookup:", sr.lookup("wltest-dead", "x"))
print("lookup_many:", sr.lookup_many("wltest-dead", ["x"]))
print("list:", sr.list_objects("wltest-dead"))
try:
    sr.stage("wltest-dead", [dict(canonical="c", name="n", type="t", domain="d", element_id="e", view="v")])
    print("stage: NO RAISE (bad)")
except Exception as ex:
    print("stage raised:", type(ex).__name__)
'''
    env = {**os.environ, "REDIS_URL": "redis://127.0.0.1:1/0", "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    print("8) unreachable Redis:\n" + out.stdout + out.stderr)
    assert "lookup: None" in out.stdout and "lookup_many: {}" in out.stdout and "list: []" in out.stdout
    assert "stage raised:" in out.stdout
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
