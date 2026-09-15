"""What a design owes, said out loud — the run-8 package is the fixture, because it is the one that
proceeded with four obligations bound to nothing and a reviewer summary that was empty."""
from lab.workloads.usecase.owed import counts, owed

PACKAGE = {
    "composition": {"topology": "T4", "families": ["F1", "F2"], "unbound": ["G04", "G08"]},
    "obligations": {"violations": [{"step": "n3", "reason": "commits without a human"}]},
    "component_selection": {"selected": [{"component_id": "cmp-1"}],
                            "unresolved": ["G23 has no enforcement point in the landscape"]},
    "cost": {"year_one": {"expected": 254740.0}, "gap_flags": ["cmp-1", "cmp-2"],
             "requires_input": ["price catalogue: no line at the 'expected' envelope"]},
    "benefit": {"summary": {"annual_benefit": 0.0, "payback_months": None,
                            "requires_input": ["no effort table was captured at intake"]},
                "recommendation": {"verdict": "proceed with conditions"}},
    "views": {"cafe_unplaced": ["bb-one", "bb-two"], "warnings": []},
    "pending_steps": {}, "defaulted_steps": {"6": "landscape is not published"},
    "model": {"elements": [1, 2, 3], "relations": [1]},
}


def test_an_obligation_nobody_enforces_is_the_first_thing_a_reviewer_hears():
    lines = owed(PACKAGE)
    assert lines[0].startswith("G04") and "NO enforcement point" in lines[0]
    assert lines[1].startswith("G08")
    assert "n3" in lines[2] and "commits without a human" in lines[2]


def test_every_kind_of_shortfall_reaches_the_line_list():
    lines = " | ".join(owed(PACKAGE))
    for needle in ("G23 has no enforcement point", "price catalogue", "2 selected component(s) have no line",
                   "no effort table", "step 6 recorded a declared default",
                   "2 building block(s) are not in the solution view"):
        assert needle in lines, needle


def test_a_complete_design_owes_nothing_and_says_so_by_being_empty():
    clean = {"composition": {"unbound": []}, "component_selection": {"unresolved": []},
             "cost": {"requires_input": [], "gap_flags": []},
             "benefit": {"summary": {"requires_input": []}}, "views": {}, "pending_steps": {},
             "defaulted_steps": {}}
    assert owed(clean) == []
    assert owed({}) == []


def test_the_headline_carries_the_figures_the_lines_are_judged_against():
    head = counts(PACKAGE)
    assert head["recommendation"] == "proceed with conditions" and head["topology"] == "T4"
    assert head["year_one_cost"] == 254740.0 and head["annual_benefit"] == 0.0
    assert head["components"] == 1 and head["families"] == 2
    assert head["elements"] == 3 and head["relations"] == 1
    assert head["owed"] == owed(PACKAGE)
