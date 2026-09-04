"""src/lab/core/canon.py — the remaining branches: None inputs to tokens()/canonical()/group(), blank
originals skipped by group(), alias fallbacks (whitespace-padded keys, no match at all, empty dict),
each documented normalisation step in isolation, and squash() on odd inputs. Complements
tests/unit/platform/test_canon.py.
Run: .venv/bin/python tests/unit/platform/test_canon_more.py   (also pytest-compatible)"""


from lab.core.canon import STOP_WORDS, canonical, group, pick_display, same, squash, tokens


def test_none_inputs_are_tolerated():
    assert tokens(None) == [] and canonical(None) == ""
    assert same(None, "") and same(None, None) and not same(None, "x")
    assert group([None, "A", None]) == {"a": ["A"]}
    assert group([]) == {} and group([None]) == {} and group(iter(())) == {}


def test_group_skips_blank_and_whitespace_originals_and_strips_kept_ones():
    assert group(["", "   ", "\t\n", "  API Gateway  ", "api gateway"]) == {"api gateway": ["API Gateway", "api gateway"]}
    g = group(["Kong (API Gateway)", "  Kong (API Gateway)  "])                # stripped duplicates collapse
    assert g == {"api gateway kong": ["Kong (API Gateway)"]}


def test_alias_fallbacks():
    assert tokens("PAS", None) == ["pas"] and tokens("PAS", {}) == ["pas"]    # empty/None aliases: no-op
    al = {"  PAS  ": "Policy Admin System"}                                     # padded key matches case-insensitively
    assert canonical("pas", al) == "admin policy system"
    assert canonical("PAS", al) == "admin policy system"
    assert canonical("PASS", al) == "pass"                                      # no alias -> the name itself
    exact = {"pas": "Point of Sale", "PAS": "Policy Admin System"}
    assert canonical("PAS", exact) == "admin policy system"                    # exact key wins over the casefold scan
    assert canonical("Pas", exact) == "point sale"                             # first casefold match in dict order
    assert canonical("  PAS  ", exact) == "admin policy system"                # the input is stripped before lookup
    # the alias VALUE is itself normalised (stop-words dropped, sorted)
    assert canonical("X", {"X": "The Ledger of Claims"}) == "claims ledger"
    assert group(["PAS", "Policy Admin System"], exact) == {"admin policy system": ["PAS", "Policy Admin System"]}


def test_each_normalisation_step():
    assert tokens("ＡＰＩ ﬁle") == ["api", "file"]                             # NFKC: full-width + ligature
    assert tokens("Café") == ["café"]                                          # accents kept
    assert tokens("R&D") == ["d", "r"]                                         # & -> and (dropped as a stop-word)
    assert tokens("Bob's O’Brien `x`") == ["bobs", "obrien", "x"]              # apostrophes deleted, not split
    assert tokens("k_l-m.n/o\\p(q)[r]{s}") == list("klmnopqrs")               # every other separator -> space
    assert tokens("the a an of for and") == ["a", "an", "and", "for", "of", "the"]   # stop-word-only names survive
    assert tokens("The Gateway") == ["gateway"]
    assert tokens("v2 0 Claims") == ["0", "claims", "v2"]                      # version/number tokens kept
    assert tokens("Providers") == ["providers"]                                # no singularisation
    assert tokens("   ") == [] and tokens("---") == [] and tokens("&") == ["and"]
    assert STOP_WORDS == frozenset({"the", "a", "an", "of", "for", "and"})


def test_pick_display_ranking_and_edges():
    assert pick_display([None, "", "  "]) == ""
    assert pick_display(["  Kong  "]) == "Kong"                                 # stripped
    assert pick_display(["api gateway", "API Gateway"]) == "API Gateway"       # same length: more upper-case wins
    assert pick_display(["API-Gateway", "API Gateway"]) == "API-Gateway"       # same length/case: punctuation wins
    assert pick_display(["Short", "Much Longer Name"]) == "Much Longer Name"   # length first
    assert pick_display(["b", "a", "a"]) == "a"                                # lexicographic final tie-break, deduped


def test_squash_odd_inputs():
    assert squash(True) == "true" and squash(3.5) == "35" and squash(["a"]) == "a"
    assert squash("Á") == "a"                                            # combining mark dropped
    assert squash("日本") == "" and squash("ß") == ""                           # no ASCII base: dropped
    assert squash("  Course_of-Action.v2  ") == "courseofactionv2"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
