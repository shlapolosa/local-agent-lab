"""src/lab/substrate/specref.py — spec by value | JSON string | art:// ref | path, and the empty-input error.
OFFLINE: the ref case uses a LocalStore in a temp dir, never the configured artifact store."""
import json
import os
import tempfile


from lab.substrate import artifacts, specref
from lab.substrate.specref import load_spec

SPEC = {"name": "m", "id": "m1", "elements": [{"id": "a", "type": "Node", "name": "A"}], "relations": []}


def test_by_value_dict():
    assert load_spec(SPEC) == SPEC
    assert load_spec(spec=SPEC) is SPEC


def test_by_value_json_string():
    assert load_spec(json.dumps(SPEC)) == SPEC
    assert load_spec(json.dumps(SPEC).encode()) == SPEC          # bytes too


def test_bad_string_is_a_clear_error():
    try:
        load_spec("{not json")
    except ValueError as e:
        assert "not valid JSON" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_non_object_rejected():
    for bad in ([1, 2], "[1,2]", 42):
        try:
            load_spec(bad)
        except ValueError as e:
            assert "JSON object" in str(e), e
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_empty_input_error_is_helpful():
    # "{}" is the same empty spec as {} — agents emit nested objects as strings, so the string
    # form must fail HERE with the helpful message, not later with KeyError('name') in the engine
    for empty in ((), (None,), ("",), ({},), ("{}",), (b"{}",)):
        try:
            load_spec(*empty)
        except ValueError as e:
            msg = str(e)
            assert "spec_ref" in msg and "spec_path" in msg and "spec" in msg, msg
        else:
            raise AssertionError(f"expected ValueError for {empty!r}")


def test_by_path_and_by_ref_and_precedence():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        json.dump(SPEC, open(p, "w"))
        assert load_spec(spec_path=p) == SPEC
        store = artifacts.LocalStore(os.path.join(d, "store"))
        other = {**SPEC, "name": "from-ref"}
        ref = store.put("s.spec.json", json.dumps(other).encode(), "application/json")
        assert ref.startswith("art://")
        assert load_spec(spec_ref=ref, store=store)["name"] == "from-ref"
        # precedence: ref > path > value
        assert load_spec({"name": "v"}, spec_path=p, spec_ref=ref, store=store)["name"] == "from-ref"
        assert load_spec({"name": "v"}, spec_path=p)["name"] == "m"
        # a ref that holds a JSON string of a string is still coerced from bytes
        assert specref.coerce(store.get(ref)) == other
        try:
            load_spec(spec_ref=ref)                        # no hidden global store: the caller injects it
        except TypeError as e:
            assert "store" in str(e)
        else:
            raise AssertionError("spec_ref without a store must be a TypeError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [PASS] {name}")
    print("test_specref: ALL PASSED")
