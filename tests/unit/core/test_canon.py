"""lab.core.canon — canonical names (dedup key), aliases, deterministic grouping and the ONE
punctuation-squash normaliser. Offline. Run: pytest tests/unit/core/test_canon.py (or as a script)."""
import random
import re

from lab.core.canon import canonical, group, pick_display, same, squash, tokens  # noqa: F401

MERGE = [
    ("API Gateway (Kong)", "Kong API Gateway"),
    ("api-gateway kong", "API Gateway (Kong)"),
    ("Master Data Database", "master data database"),
    ("Payer/TPA Systems", "Payer TPA Systems"),
    ("R&D Portal", "R and D Portal"),
    ("Bob's Ledger", "Bobs Ledger"),
    ("ＡＰＩ Gateway", "API Gateway"),          # NFKC full-width
    ("The Claims Engine", "Claims Engine"),    # stop-word
    ("  Claims   Engine  ", "Claims Engine"),  # whitespace
]
NO_MERGE = [
    ("Payment Service", "Payment Gateway"),
    ("Provider Systems", "Providers"),
    ("Anti Fraud Management System (AFM)", "Fraud System"),
    ("Claims Engine", "Claims Engine v2"),
    ("PAS", "Policy Admin System"),            # only merges via aliases
]
NAMES = ["API Gateway (Kong)", "Kong API Gateway", "api-gateway kong", "Payment Service",
         "Payment Gateway", "Master Data Database", "master data database", "Kong API Gateway"]


def test_same_and_canonical():
    for a, b in MERGE:
        assert same(a, b), (a, b, canonical(a), canonical(b))
    for a, b in NO_MERGE:
        assert not same(a, b), (a, b, canonical(a), canonical(b))
    assert canonical("API Gateway (Kong)") == "api gateway kong"
    assert canonical("Anti Fraud Management System (AFM)") == "afm anti fraud management system"
    assert canonical("The") == "the"            # stop-word-only names are not emptied
    assert canonical("") == "" and canonical("   ") == ""


def test_aliases_apply_before_normalisation_exact_then_case_insensitive():
    al = {"PAS": "Policy Admin System"}
    assert same("PAS", "Policy Admin System", aliases=al)
    assert same("pas", "policy admin system", aliases=al)
    assert not same("PAS", "Policy Admin System")


def test_group_and_pick_display_deterministic_across_orderings():
    ref = None
    for seed in range(20):
        shuffled = NAMES[:]
        random.Random(seed).shuffle(shuffled)
        g = group(shuffled)
        norm = {k: sorted(v) for k, v in g.items()}
        disp = {k: pick_display(v) for k, v in g.items()}
        if ref is None:
            ref = (norm, disp)
        assert (norm, disp) == ref, seed
    norm, disp = ref
    assert set(norm) == {"api gateway kong", "payment service", "gateway payment", "data database master"}
    assert norm["api gateway kong"] == ["API Gateway (Kong)", "Kong API Gateway", "api-gateway kong"]
    assert norm["data database master"] == ["Master Data Database", "master data database"]
    assert disp["api gateway kong"] == "API Gateway (Kong)", disp
    assert disp["data database master"] == "Master Data Database", disp
    assert pick_display([]) == ""
    assert pick_display(["b", "a"]) == pick_display(["a", "b"]) == "a"
    # group preserves first-seen order and dedupes exact repeats
    g = group(["Kong API Gateway", "API Gateway (Kong)", "Kong API Gateway"])
    assert g == {"api gateway kong": ["Kong API Gateway", "API Gateway (Kong)"]}
    return disp


def test_squash_is_the_one_punctuation_normaliser():
    assert squash("ApplicationComponent") == squash("Application Component") == squash("application_component") == "applicationcomponent"
    assert squash("Course of Action") == "courseofaction"
    assert squash("com.lucidchart.VirtualMachineAzure2021.109") == "comlucidchartvirtualmachineazure2021109"
    assert squash("Virtual Machine") in squash("com.lucidchart.VirtualMachineAzure2021.109")   # the stencil token match
    # ASCII-fold policy: accents FOLD to their base letter (NFKD, marks dropped) — they do not vanish
    assert squash("Café") == "cafe" and squash("Ünïcode") == "unicode" and squash("naïve") == "naive"
    assert squash("ＡＰＩ Gateway") == "apigateway"        # compatibility forms fold too
    assert squash("Ω-service") == "service"              # a letter with no ASCII base is dropped, not kept
    assert squash("") == "" and squash(None) == "" and squash("   ") == ""
    assert squash(42) == "42"                            # non-strings are stringified (sheet names may be ints)
    # identical results for the three former call sites on one shared fixture
    _regex_norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())       # adoit_excel / architect_tools
    _isalnum_norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())     # read_lucidchart
    for s in ["ApplicationComponent", "Application Component", "Course of Action", "Display as icon",
              "com.lucidchart.ExpressRouteDirectAzure2021.592", "Database.70", "VM Scale Sets", "application component "]:
        assert squash(s) == _regex_norm(s) == _isalnum_norm(s), s
    assert squash("é") == "e" and _regex_norm("é") == "" and _isalnum_norm("é") == "é"   # the documented divergence


if __name__ == "__main__":
    test_same_and_canonical()
    test_aliases_apply_before_normalisation_exact_then_case_insensitive()
    disp = test_group_and_pick_display_deterministic_across_orderings()
    test_squash_is_the_one_punctuation_normaliser()
    print("canonical samples:")
    for n in ["API Gateway (Kong)", "Payer/TPA Systems", "Anti Fraud Management System (AFM)", "R&D Portal", "Bob's Ledger"]:
        print(f"  {n!r:42} -> {canonical(n)!r}")
    print("group:", dict(group(NAMES)))
    print("display:", disp)
    print("ALL TESTS PASSED")
