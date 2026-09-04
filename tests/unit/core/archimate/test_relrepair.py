"""Reproduces the live-run defect (16 illegal relations) and checks relrepair fixes exactly them.
Run from the repo root:  .venv/bin/python tests/unit/core/archimate/test_relrepair.py
"""
import copy
import sys

from lab.core.archimate.engine import Model
from lab.core.archimate import relrepair


def build():
    m = Model("repair-fixture", mid="fix")
    m.el("comp", "ApplicationComponent", "Claims Engine")
    m.el("sys", "SystemSoftware", "JBoss")
    m.el("sys2", "SystemSoftware", "Postgres")
    m.el("actor", "BusinessActor", "Claims Handler")
    for i in range(7):
        m.el(f"svc{i}", "ApplicationService", f"Service {i}")
        m.el(f"fn{i}", "ApplicationFunction", f"Function {i}")
    # 14x the LLM's "this box groups these" aggregation
    for i in range(7):
        m.rel("Aggregation", "comp", f"svc{i}", rid=f"agg-svc{i}")
        m.rel("Aggregation", "comp", f"fn{i}", rid=f"agg-fn{i}")
    # 2x technology 'assigned to' the component
    m.rel("Assignment", "sys", "comp", rid="asg-sys1")
    m.rel("Assignment", "sys2", "comp", rid="asg-sys2")
    # 3 legal relations that must be untouched
    m.el("fnX", "ApplicationFunction", "Legal fn")
    m.el("svcX", "ApplicationService", "Legal svc")
    m.rel("Assignment", "comp", "fnX", rid="ok-asg")
    m.rel("Realization", "comp", "svcX", rid="ok-real")
    m.rel("Serving", "svcX", "actor", rid="ok-serv")
    return m


def not_permitted(model):
    return [w for w in model.validate_relations() if "not permitted" in w]


def main():
    assert relrepair._sem() is not None, "semantic layer must be importable for this test (exact matrix)"
    m = build()
    before = not_permitted(m)
    print(f"before: {len(before)} 'not permitted' findings")
    assert len(before) == 16, before
    snapshot = {rid: (s, g, dict(x)) for rid, (_, s, g, x) in m.relations.items()}

    same, report = relrepair.repair(m)
    assert same is m, "repair must be in place"
    after = not_permitted(m)
    print(f"after:  {len(after)} 'not permitted' findings")
    assert after == [], after

    # exactly 16 entries, correct original/replaced
    assert len(report) == 16, len(report)
    by = {e["rid"]: e for e in report}
    for i in range(7):
        e = by[f"agg-svc{i}"]; assert (e["original"], e["replaced"], e["rule"]) == ("Aggregation", "Realization", "intent"), e
        e = by[f"agg-fn{i}"]; assert (e["original"], e["replaced"], e["rule"]) == ("Aggregation", "Assignment", "intent"), e
    for rid in ("asg-sys1", "asg-sys2"):
        e = by[rid]; assert (e["original"], e["replaced"], e["rule"]) == ("Assignment", "Realization", "intent"), e
    for e in report:
        for k in ("rid", "src", "tgt", "src_type", "tgt_type", "original", "replaced", "reason"):
            assert e.get(k), (k, e)

    # model state: types rewritten, legal untouched, ids/direction/extras preserved
    for i in range(7):
        assert m.relations[f"agg-svc{i}"][0] == "Realization"
        assert m.relations[f"agg-fn{i}"][0] == "Assignment"
    assert m.relations["asg-sys1"][0] == m.relations["asg-sys2"][0] == "Realization"
    assert m.relations["ok-asg"][0] == "Assignment"
    assert m.relations["ok-real"][0] == "Realization"
    assert m.relations["ok-serv"][0] == "Serving"
    assert set(m.relations) == set(snapshot), "relation ids must be preserved (none dropped/added)"
    for rid, (_, s, g, x) in m.relations.items():
        assert (s, g, dict(x)) == snapshot[rid], f"direction/extras changed on {rid}"

    # spec API: copy, not in place, same decisions
    spec = build().to_spec()
    orig = copy.deepcopy(spec)
    fixed, rep2 = relrepair.repair_spec(spec)
    assert spec == orig, "repair_spec must not modify its input"
    assert len(rep2) == 16 and {e["rid"]: e["replaced"] for e in rep2} == {e["rid"]: e["replaced"] for e in report}
    types = {r["id"]: r["type"] for r in fixed["relations"]}
    assert types["agg-svc0"] == "Realization" and types["agg-fn0"] == "Assignment" and types["asg-sys1"] == "Realization"
    assert not relrepair._sem().validate_model(fixed)["illegal"]

    # unrepairable-by-intent -> Association fallback, flagged
    f = Model("fallback", mid="fb")
    f.el("obj", "BusinessObject", "Claim form"); f.el("act", "BusinessActor", "Clerk")
    f.rel("Serving", "obj", "act", rid="bad-serving")     # passive -> active Serving: no dependency alternative
    _, frep = relrepair.repair(f)
    assert len(frep) == 1 and frep[0]["replaced"] == "Association", frep
    assert frep[0]["rule"] == "fallback_association" and "fallback_association" in frep[0]["reason"], frep
    assert f.relations["bad-serving"][0] == "Association" and not_permitted(f) == []

    print("sample report lines:")
    for line in relrepair.summarize(report)[:3] + relrepair.summarize(frep):
        print("  " + line)
    print("OK: 16 repaired (14 intent Aggregation->Realization/Assignment, 2 intent Assignment->Realization), "
          "3 legal untouched, 0 'not permitted' after repair, fallback_association flagged")


def test_relrepair_end_to_end():
    """pytest entry — the script-mode `main()` is the test."""
    main()


if __name__ == "__main__":
    main()
