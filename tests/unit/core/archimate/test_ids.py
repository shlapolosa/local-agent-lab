"""src/lab/core/archimate/ids.py — the relation-id formula is a CONTRACT (ADOIT matches on it at re-import), so it
is pinned to fixed outputs, not re-derived from the implementation.
Run: .venv/bin/python tests/unit/workloads/test_ids.py   (also pytest-compatible)"""
import hashlib
import re


from lab.core.archimate.ids import rid, slug


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
    """One relation-id formula in the repo: workflow.py binds lab.core.archimate.ids.rid, no private copy."""
    from lab.workloads.visio_to_archimate import workflow
    from lab.core.archimate import ids
    assert workflow._rid is ids.rid
    assert "def _rid" not in open(workflow.__file__, encoding="utf-8").read()


def test_element_id_keeps_the_prefixes_the_use_case_mappers_already_mint():
    from lab.core.archimate.ids import element_id
    assert element_id("BusinessActor", "Triage Nurse") == "ba-triage-nurse"
    assert element_id("BusinessObject", "Referral") == "bo-referral"
    assert element_id("ApplicationComponent", "Cerner triage module") == "ac-cerner-triage-module"
    assert element_id("Capability", "B1.1.2") == "cap-b1-1-2"


def test_every_other_type_is_prefixed_by_its_full_name_so_no_two_types_collide():
    from lab.core.archimate.engine import _TYPES
    from lab.core.archimate.ids import element_id, prefix_for
    assert element_id("SystemSoftware", "PostgreSQL 16") == "system-software-postgresql-16"
    prefixes = [prefix_for(t) for t in _TYPES]
    assert len(set(prefixes)) == len(prefixes)
    assert all(re.fullmatch(r"[a-z0-9-]+-", p) for p in prefixes)


def test_element_id_is_total_a_wholly_arabic_name_still_gets_a_stable_valid_id():
    """Review finding 2: a bilingual tenant names things in Arabic, and those used to vanish."""
    from lab.core.archimate.ids import element_id
    a = element_id("BusinessObject", "الإحالة")
    assert re.fullmatch(r"bo-h[0-9a-f]{10}", a) and a == element_id("BusinessObject", " الإحالة ")
    assert a != element_id("BusinessObject", "الموعد")
    assert element_id("BusinessActor", "  ") == ""


if __name__ == "__main__":
    test_rid_is_the_documented_formula()
    test_rid_is_a_pure_function_of_endpoints_and_type()
    test_slug_rule()
    print("ALL TESTS PASSED")
