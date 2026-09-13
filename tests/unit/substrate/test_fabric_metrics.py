"""Published measurements: every number has a known answer over a fixture, the page renders them, and a tick
remembers them where the read tool looks and writes the page through the gateway."""
import asyncio
import json

from fixtures.fakes import FakeRedis
from lab.platform.contracts import CollabTools, SemanticTools
from lab.substrate import fabric_metrics as M

TABLES = {
    "states": {"columns": ["state", "n"], "rows": [["urn:fabric:state:published", "4"], ["urn:fabric:state:pending", "6"]]},
    "owned": {"columns": ["n"], "rows": [["7"]]},
    "labelled": {"columns": ["n"], "rows": [["10"]]},
    "delivery": {"columns": ["rung", "n"], "rows": [["C", "6"], ["X", "2"], ["H", "2"], ["D", "2"]]},
    "duplicates": {"columns": ["n"], "rows": [["1"]]},
}


def _facts():
    return {"tables": TABLES, "decisions": {"draft-review": {"approve": 3, "decline": 0, "update": 0, "reworked": 1, "pending": 2},
                                            "impact-notice": {"approve": 1, "decline": 0, "update": 0, "reworked": 0, "pending": 1},
                                            "association": {"approve": 2, "decline": 0, "update": 0, "reworked": 0, "pending": 0}}}


def test_every_number_has_a_known_answer():
    m = M.compute(_facts())
    assert m["records"] == {"total": 10, "published": 4, "pending": 6}
    assert m["auto_association_ratio"] == {"value": 0.833, "auto": 10, "asked": 2, "derived": 2}      # C+X+D over asked
    assert m["approved_without_rewrite"] == {"value": 0.667, "approved": 2, "reworked": 1, "open": 2}  # an approve after an update is a rewrite
    assert m["impact_acknowledged"]["value"] == 1.0 and m["impact_acknowledged"]["unacknowledged_changes"] == 1
    assert m["duplicate_rate"] == {"value": 0.25, "duplicates": 1, "published": 4}
    assert m["labelled_share"]["value"] == 1.0 and m["owned_share"]["value"] == 0.7
    empty = M.compute({"tables": {}, "decisions": {}})
    assert empty["records"]["total"] == 0 and empty["auto_association_ratio"]["value"] is None


def test_the_page_carries_every_measure_with_its_basis():
    text = M.render(M.compute(_facts()))
    assert "| Auto-association ratio | 83 % | 10 established" in text and "2 of them derived" in text and "| Owned | 70 % | 7 of 10 |" in text
    assert "| Duplicate rate | 25 %" in text and "n/a" not in text and text.startswith("---\ntitle:")


def test_a_tick_gathers_through_the_gateway_remembers_and_publishes_the_page():
    from lab.substrate import approvals
    r = FakeRedis()
    a = approvals.request("draft-review", "a", {}, "wf", client=r); approvals.human_decision(a, "approve", "p@x", "review-app", client=r)
    approvals.request("draft-review", "b", {}, "wf", client=r)
    s_ = approvals.request("speaker-mapping", "s", {}, "wf", client=r); approvals.human_decision(s_, "approve", "p@x", "review-app", client=r)
    calls = []

    async def call(cs):
        calls.extend(cs)
        out = []
        for suffix, args in cs:
            if suffix == SemanticTools.query:
                name = next(k for k, q in M.QUERIES.items() if q == args["sparql"])
                out.append(TABLES[name])
            elif suffix == SemanticTools.store_spec:
                out.append({"spec_ref": "art://m/fabric-metrics.md"})
            elif suffix == CollabTools.put:
                out.append({"handle": "collab://item/d/page", "name": args["name"]})
        return out
    m = asyncio.run(M.tick(folder="collab://item/d/root", client=r, call=call))
    assert m["approved_without_rewrite"] == {"value": 1.0, "approved": 1, "reworked": 0, "open": 1}
    assert json.loads(r.get(M.KEY))["records"]["total"] == 10
    assert r.get("fabric:written:collab:collab://item/d/page")                 # the page is loop-guarded
    put = next(a for s, a in calls if s == CollabTools.put)
    assert put == {"folder": "collab://item/d/root", "ref": "art://m/fabric-metrics.md", "name": "fabric-metrics.md"}
    assert len([s for s, _ in calls if s == SemanticTools.query]) == len(M.QUERIES)
