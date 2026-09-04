"""src/lab/workloads/accumulator.py — the Template Method base behind the BA/Architect accumulator tools,
exercised through a minimal concrete subclass so the skeleton is tested on its own.
Run: .venv/bin/python tests/unit/workloads/test_accumulator.py   (also pytest-compatible)"""
import json


from lab.workloads import accumulator as A
from lab.workloads.accumulator import MAX_BATCH, Accumulator, coerce_items, fmt, nonempty_str


class Names(Accumulator):
    """Smallest useful accumulator: named items keyed by name, update-not-duplicate, a gate that
    wants at least one item and hints when an item is lowercase."""

    def reset(self):
        super().reset()
        self.items: dict[str, dict] = {}
        self.boom = False

    def add(self, items):
        lst, err = self._batch(items, "total_items", len(self.items))
        if err:
            return err
        added, updated, rejected = [], [], []
        for i, it in enumerate(lst):
            if not isinstance(it, dict) or not nonempty_str(it.get("name")):
                rejected.append({"index": i, "errors": ["name is required (non-empty string)"]})
                continue
            name = it["name"].strip()
            (updated if name in self.items else added).append(name)
            self.items.setdefault(name, {}).update(it)
        return {"added": added, "updated": updated, "rejected": rejected, "total_items": len(self.items)}

    def result(self):
        return {"items": [dict(v) for v in self.items.values()]}

    def counts(self):
        return {"items": len(self.items)}

    def _gate(self, doc):
        if self.boom:
            raise RuntimeError("gate exploded")
        errors = [] if doc["items"] else ["no items"]
        lower = [i["name"] for i in doc["items"] if i["name"].islower()]
        return errors, (f"{len(lower)} lowercase item(s)" if lower else None)


def test_helpers():
    assert fmt(("A", "B")) == "A, B"
    assert nonempty_str(" x ") and not nonempty_str("  ") and not nonempty_str(None) and not nonempty_str(3)
    assert coerce_items([{"a": 1}]) == [{"a": 1}]
    assert coerce_items({"a": 1}) == [{"a": 1}]                       # a single dict is a one-item batch
    assert coerce_items(json.dumps([{"a": 1}])) == [{"a": 1}]          # a JSON string is parsed
    assert coerce_items("not json").startswith("items must be a JSON array")
    assert coerce_items(42) == "items must be a list (got int)"
    assert MAX_BATCH == A.MAX_BATCH == 12


def test_batch_cap_and_envelope():
    acc = Names()
    big = [{"name": f"n{i}"} for i in range(MAX_BATCH + 1)]
    r = acc.add(big)
    assert r == {"error": f"batch too large: {MAX_BATCH + 1} items > {MAX_BATCH}. Nothing was added — "
                          f"split into calls of at most {MAX_BATCH} items and resend.",
                 "added": [], "updated": [], "rejected": [], "total_items": 0}
    assert acc.items == {}                                              # nothing was added
    r = acc.add("garbage")
    assert r["error"].startswith("items must be a JSON array") and r["total_items"] == 0
    assert list(r) == ["error", "added", "updated", "rejected", "total_items"]
    # the middle key is per-accumulator (relations report duplicates, elements report updates)
    _, err = Accumulator._batch(big, "total_relations", 3, middle="duplicates")
    assert list(err) == ["error", "added", "duplicates", "rejected", "total_relations"] and err["total_relations"] == 3
    lst, err = Accumulator._batch({"name": "solo"}, "total_items", 0)
    assert lst == [{"name": "solo"}] and err is None


def test_per_item_accept_reject_and_update_not_duplicate():
    acc = Names()
    r = acc.add([{"name": "Portal"}, {"nope": 1}, "str", {"name": "Redis", "doc": "cache"}])
    assert r["added"] == ["Portal", "Redis"] and r["updated"] == []
    assert [x["index"] for x in r["rejected"]] == [1, 2] and r["total_items"] == 2
    r = acc.add([{"name": "Redis", "doc": "limiter state"}])
    assert r["added"] == [] and r["updated"] == ["Redis"] and r["total_items"] == 2
    assert acc.items["Redis"]["doc"] == "limiter state"                 # later fields win
    assert len(acc.result()["items"]) == 2


def test_finish_reset_and_last_finish():
    acc = Names()
    assert acc.last_finish is None
    r = acc.finish()
    assert r == {"ok": False, "counts": {"items": 0}, "errors": ["no items"]} and acc.last_finish is r
    acc.add([{"name": "Portal"}, {"name": "redis"}])
    r = acc.finish()
    assert r == {"ok": True, "counts": {"items": 2}, "hint": "1 lowercase item(s)"} and acc.last_finish is r
    doc = acc.result()
    doc["items"].clear()                                                # result() is a copy
    assert len(acc.result()["items"]) == 2
    acc.reset()
    assert acc.items == {} and acc.last_finish is None


def test_finish_never_raises():
    acc = Names()
    acc.add([{"name": "Portal"}])
    acc.boom = True
    r = acc.finish()
    assert r["ok"] is False and r["errors"] == ["internal: RuntimeError: gate exploded"]
    assert r["counts"] == {"items": 1} and acc.last_finish is r


def test_base_is_abstract():
    try:
        Accumulator()
    except TypeError as e:
        assert "abstract" in str(e)
    else:
        raise AssertionError("Accumulator must not be instantiable without result/counts/_gate")


if __name__ == "__main__":
    test_helpers()
    test_batch_cap_and_envelope()
    test_per_item_accept_reject_and_update_not_duplicate()
    test_finish_reset_and_last_finish()
    test_finish_never_raises()
    test_base_is_abstract()
    print("ALL TESTS PASSED")
