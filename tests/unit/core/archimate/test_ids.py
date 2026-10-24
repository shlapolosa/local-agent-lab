"""src/lab/workloads/ids.py — the relation-id formula is a CONTRACT (ADOIT matches on it at re-import), so it
is pinned to fixed outputs, not re-derived from the implementation.
Run: .venv/bin/python tests/unit/workloads/test_ids.py   (also pytest-compatible)"""
import hashlib


from lab.workloads.ids import rid, slug


def test_rid_is_the_documented_formula():
    assert rid("a", "Serving", "b") == "r-" + hashlib.md5(b"a|Serving|b").hexdigest()[:10]
    # pinned values: if either changes, every re-imported relation becomes a duplicate in ADOIT
    assert rid("litellm-proxy", "Access", "spend-log") == "r-e054b9d219"
    assert rid("a", "Serving", "b") == "r-ecce01f306"
    assert len(rid("x", "y", "z")) == 12 and rid("x", "y", "z").startswith("r-")


def test_rid_is_a_pure_function_of_endpoints_and_type():
    assert rid("a", "Serving", "b") == rid("a", "Serving", "b")
    assert rid("a", "Serving", "b") != rid("b", "Serving", "a")          # direction matters
    assert rid("a", "Serving", "b") != rid("a", "Realization", "b")      # type matters


def test_slug_rule():
    assert slug("Local Agent Lab") == "local-agent-lab"
    assert slug("  LiteLLM  Proxy (v2)! ") == "litellm-proxy-v2"
    assert slug("Café Ünïcode") == "cafe-unicode"        # accents fold to ASCII
    assert slug("!!!") == "" and slug("") == ""           # nothing survives -> "" (caller picks the default)


def test_workflow_uses_the_shared_rid():
    """One relation-id formula in the repo: workflow.py binds lab.workloads.ids.rid, no private copy."""
    from lab.workloads.visio_to_archimate import workflow
    from lab.workloads import ids
    assert workflow._rid is ids.rid
    assert "def _rid" not in open(workflow.__file__, encoding="utf-8").read()


if __name__ == "__main__":
    test_rid_is_the_documented_formula()
    test_rid_is_a_pure_function_of_endpoints_and_type()
    test_slug_rule()
    print("ALL TESTS PASSED")
