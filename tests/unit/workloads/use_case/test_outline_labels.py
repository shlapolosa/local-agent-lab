"""What the live view shows for a row that RELATES two things.

Measured on wfr-886957c31872 (29 Sep 2026): step 5's 42 matches were 42 distinct (function,
capability) pairs, but each row showed only the capability label — so "Custom agent hosting"
appeared four times with nothing to tell the rows apart, and read as duplicated output. Step 6's
shortlist showed bare L3 ids — "COG.02" three times — hiding the route and the product that made
each row different. A row that pairs two things names both.
"""
from lab.workloads.usecase.derivation import outline


def _rows(out, key):
    return outline(out)[key]["items"]


def test_a_match_names_its_function_AND_its_capability_and_status():
    out = {"matched": [{"function": "review packet", "capability_id": "COG.02",
                        "capability_label": "Custom agent hosting", "status": "new"},
                       {"function": "apply criteria", "capability_id": "COG.02",
                        "capability_label": "Custom agent hosting", "status": "new"}]}
    rows = _rows(out, "matched")
    assert rows == ["review packet → Custom agent hosting · new",
                    "apply criteria → Custom agent hosting · new"]
    assert len(set(rows)) == 2, "two different matches never render as the same line"


def test_a_shortlisted_realisation_names_its_capability_route_and_product():
    out = {"shortlist": [{"capability_id": "COG.02", "route": "microsoft",
                          "realisation": "Foundry Agent Service", "preferred": True},
                         {"capability_id": "COG.02", "route": "sovereign",
                          "realisation": "Core42 Compass"}]}
    assert _rows(out, "shortlist") == ["COG.02 · microsoft: Foundry Agent Service (preferred)",
                                       "COG.02 · sovereign: Core42 Compass"]


def test_a_row_naming_ONE_thing_is_unchanged():
    assert _rows({"x": [{"name": "Clinical reviewer"}]}, "x") == ["Clinical reviewer"]
