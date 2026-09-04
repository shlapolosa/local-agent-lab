"""src/lab/workloads/accumulator.py — the remaining shapes of the Template Method skeleton: every `coerce_items`
input form, `_batch` at exactly the cap and with the per-accumulator middle key, `finish()` with
errors + hint together, `last_finish` replaced on every call, and the never-raise contract when the
gate fails in different ways. Complements tests/unit/workloads/test_accumulator.py.
Run: .venv/bin/python tests/unit/workloads/test_accumulator_more.py   (also pytest-compatible)"""
import json


from lab.workloads.accumulator import MAX_BATCH, Accumulator, coerce_items, fmt, nonempty_str


class Tally(Accumulator):
    """A two-collection accumulator: `things` (update-not-duplicate) and `links` (duplicates reported),
    with a gate whose errors and hint are scripted per test."""

    def reset(self):
        super().reset()
        self.things: dict[str, dict] = {}
        self.links: list[tuple] = []
        self.gate_errors: list[str] = []
        self.gate_hint = None
        self.gate_exc = None

    def add_things(self, items):
        lst, err = self._batch(items, "total_things", len(self.things))
        if err:
            return err
        added, updated = [], []
        for it in lst:
            (updated if it["name"] in self.things else added).append(it["name"])
            self.things.setdefault(it["name"], {}).update(it)
        return {"added": added, "updated": updated, "rejected": [], "total_things": len(self.things)}

    def add_links(self, items):
        lst, err = self._batch(items, "total_links", len(self.links), middle="duplicates")
        if err:
            return err
        added, dups = [], []
        for it in lst:
            key = (it["a"], it["b"])
            (dups if key in self.links else added).append(key)
            if key not in self.links:
                self.links.append(key)
        return {"added": added, "duplicates": dups, "rejected": [], "total_links": len(self.links)}

    def result(self):
        return {"things": [dict(v) for v in self.things.values()], "links": [list(k) for k in self.links]}

    def counts(self):
        return {"things": len(self.things), "links": len(self.links)}

    def _gate(self, doc):
        if self.gate_exc:
            raise self.gate_exc
        return list(self.gate_errors), self.gate_hint


def test_coerce_items_every_input_shape():
    assert coerce_items([]) == []
    assert coerce_items([1, "a", None]) == [1, "a", None]                 # a list is returned untouched
    assert coerce_items((1, 2)) == "items must be a list (got tuple)"      # tuples are not tolerated
    assert coerce_items(None) == "items must be a list (got NoneType)"
    assert coerce_items(3.5) == "items must be a list (got float)"
    assert coerce_items({}) == [{}]                                       # an empty dict is a one-item batch
    assert coerce_items("[]") == []                                       # JSON array string
    assert coerce_items('{"a": 1}') == [{"a": 1}]                         # JSON object string -> one-item batch
    assert coerce_items('"just a string"') == "items must be a list (got str)"   # JSON scalar: parsed, not a list
    assert coerce_items("42") == "items must be a list (got int)"
    assert coerce_items("") == "items must be a JSON array of objects (got an unparsable string)"
    assert coerce_items("[1, 2") == "items must be a JSON array of objects (got an unparsable string)"
    assert coerce_items(json.dumps([{"x": [1, {"y": 2}]}])) == [{"x": [1, {"y": 2}]}]


def test_fmt_and_nonempty_str_edges():
    assert fmt([]) == "" and fmt(("only",)) == "only" and fmt(iter(["a", "b", "c"])) == "a, b, c"
    assert nonempty_str("x") and not nonempty_str("") and not nonempty_str("\n\t ")
    assert not nonempty_str(b"bytes") and not nonempty_str(["x"]) and not nonempty_str(0)


def test_batch_exactly_at_the_cap_is_accepted_and_one_over_is_not():
    acc = Tally()
    exact = [{"name": f"t{i}"} for i in range(MAX_BATCH)]
    r = acc.add_things(exact)
    assert len(r["added"]) == MAX_BATCH and r["total_things"] == MAX_BATCH
    r = acc.add_things(exact + [{"name": "one-too-many"}])
    assert r["error"].startswith(f"batch too large: {MAX_BATCH + 1} items > {MAX_BATCH}")
    assert r["added"] == [] and r["updated"] == [] and r["rejected"] == []
    assert r["total_things"] == MAX_BATCH                                 # the running total is reported, unchanged
    assert "one-too-many" not in acc.things


def test_batch_envelope_carries_the_middle_key_and_running_total():
    acc = Tally()
    acc.add_links([{"a": "x", "b": "y"}])
    r = acc.add_links("{oops")
    assert r == {"error": "items must be a JSON array of objects (got an unparsable string)",
                 "added": [], "duplicates": [], "rejected": [], "total_links": 1}
    r = acc.add_links(None)
    assert r["error"] == "items must be a list (got NoneType)" and list(r)[1:] == ["added", "duplicates", "rejected", "total_links"]
    # a single dict and a JSON string reach the loop as a one-item / parsed batch
    assert acc.add_links({"a": "x", "b": "y"}) == {"added": [], "duplicates": [("x", "y")], "rejected": [], "total_links": 1}
    assert acc.add_links(json.dumps([{"a": "p", "b": "q"}]))["added"] == [("p", "q")]
    # the staticmethod is callable on the class with any total
    lst, err = Accumulator._batch("[]", "total_x", 7)
    assert lst == [] and err is None
    _, err = Accumulator._batch([1] * (MAX_BATCH + 5), "total_x", 7, middle="skipped")
    assert err["total_x"] == 7 and err["skipped"] == [] and "split into calls of at most" in err["error"]


def test_finish_reports_errors_and_hint_together_and_replaces_last_finish():
    acc = Tally()
    acc.add_things([{"name": "A"}])
    acc.gate_errors, acc.gate_hint = ["missing B"], "A has no link"
    r1 = acc.finish()
    assert r1 == {"ok": False, "counts": {"things": 1, "links": 0}, "errors": ["missing B"], "hint": "A has no link"}
    assert list(r1) == ["ok", "counts", "errors", "hint"] and acc.last_finish is r1
    acc.gate_errors = []
    r2 = acc.finish()
    assert r2 == {"ok": True, "counts": {"things": 1, "links": 0}, "hint": "A has no link"}
    assert acc.last_finish is r2 and acc.last_finish is not r1            # replaced on every call
    acc.gate_hint = None
    r3 = acc.finish()
    assert r3 == {"ok": True, "counts": {"things": 1, "links": 0}} and "hint" not in r3 and "errors" not in r3
    acc.gate_hint = ""                                                     # a falsy hint is not reported
    assert "hint" not in acc.finish()


def test_finish_never_raises_whatever_the_gate_throws():
    acc = Tally()
    acc.add_things([{"name": "A"}]); acc.add_links([{"a": "A", "b": "A"}])
    for exc, text in ((KeyError("k"), "internal: KeyError: 'k'"),
                      (ValueError("bad value"), "internal: ValueError: bad value"),
                      (ZeroDivisionError("division by zero"), "internal: ZeroDivisionError: division by zero")):
        acc.gate_exc = exc
        r = acc.finish()
        assert r == {"ok": False, "counts": {"things": 1, "links": 1}, "errors": [text]}
        assert "hint" not in r and acc.last_finish is r
    # result() raising inside the gate call is caught too (it runs under the same try)
    acc.gate_exc = None
    acc.result = lambda: (_ for _ in ()).throw(RuntimeError("assembly failed"))
    r = acc.finish()
    assert r["ok"] is False and r["errors"] == ["internal: RuntimeError: assembly failed"]


def test_reset_restores_every_base_and_subclass_field():
    acc = Tally()
    acc.add_things([{"name": "A"}]); acc.add_links([{"a": "A", "b": "A"}])
    acc.gate_errors = ["x"]; acc.finish()
    assert acc.last_finish is not None and acc.things and acc.links
    acc.reset()
    assert acc.last_finish is None and acc.things == {} and acc.links == [] and acc.gate_errors == []
    assert acc.finish() == {"ok": True, "counts": {"things": 0, "links": 0}}


def test_partial_subclass_is_still_abstract():
    class OnlyResult(Accumulator):
        def result(self):
            return {}
    try:
        OnlyResult()
    except TypeError as e:
        assert "counts" in str(e) and "_gate" in str(e)
    else:
        raise AssertionError("counts/_gate are abstract")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
