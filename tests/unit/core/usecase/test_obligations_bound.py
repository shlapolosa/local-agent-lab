"""Step 21's third soft rule — an obligation with no selected component that enforces it.

CAFÉ M4: "Selection is not complete until every obligation resolves to a named enforcement point on
a selected component." It is the Stage 5 EXIT GATE, and until now nothing checked it — the design
recorded which families were present and stopped, which is a shape rather than an enforcement point.

Soft, like its two siblings: one corrective attempt, then recorded under `unresolved` and the run
proceeds. A design that owes a control is a design a reviewer must see, not a run that vanishes.
"""
from lab.workloads.usecase import steps

CANDIDATES = {"G02": ["cmp-reg"], "G09": ["cmp-appr", "cmp-pa"], "G24": ["cmp-apim"], "G99": []}


def context(**over):
    return {"obligations": {"guardrails": ["G02", "G09"]},
            "enforcement_points": CANDIDATES} | over


def selection(*ids, unresolved=()):
    return {"selected": [{"capability": "c", "component_id": i, "component": i} for i in ids],
            "unresolved": list(unresolved), "tradeoffs": []}


def test_a_selection_that_enforces_every_obligation_is_silent():
    assert steps._obligations_bound(selection("cmp-reg", "cmp-pa"), context()) == []


def test_an_obligation_no_selected_component_enforces_is_named_with_what_would_enforce_it():
    """Naming the guardrail alone would leave an architect to search the catalogue. The candidates
    are already in the prompt — the finding says which of them to take."""
    found = steps._obligations_bound(selection("cmp-reg"), context())
    assert len(found) == 1
    assert "G09" in found[0]
    assert "cmp-appr" in found[0] and "cmp-pa" in found[0], "say what WOULD enforce it"


def test_an_obligation_the_corpus_cannot_bind_is_never_the_designs_fault():
    """`unenforceable` means the guardrail names a capability the map lacks or one reaching no
    component. No selection repairs that, and failing a design for it charges an architect for a
    gap in the framework — measured 18 Sep 2026 at 20 of 24 live guardrails before the repair."""
    assert steps._obligations_bound(
        selection("cmp-reg"), context(obligations={"guardrails": ["G02", "G99"]})) == []


def test_an_obligation_named_under_unresolved_is_accepted():
    """The same escape its sibling rules give: the design may OWE a control, as long as it says so."""
    assert steps._obligations_bound(
        selection("cmp-reg", unresolved=["G09 — the approval surface is not yet chosen"]),
        context()) == []


def test_the_rule_is_silent_without_the_candidates_rather_than_failing_every_obligation():
    """`_compose` defers by name when the corpora are absent. Refusing here too would fail the
    design for a plumbing problem, and say nothing true about the selection."""
    assert steps._obligations_bound(selection("cmp-reg"), context(enforcement_points=None)) == []
    assert steps._obligations_bound(selection("cmp-reg"), {}) == []


def test_the_rule_is_silent_when_this_design_carries_no_obligations():
    assert steps._obligations_bound(selection(), context(obligations={"guardrails": []})) == []


def test_it_is_part_of_step_21s_soft_findings():
    """Wired, not merely defined — the defect the sibling rules would never have caught."""
    found = steps._soft_21(selection("cmp-reg"), context(
        component_families={}, model_summary={}, component_catalogue=[]))
    assert any("G09" in f for f in found)


# ------------------------------------------------- what the person at the gate is actually told

def package(**over):
    return {"composition": {"unbound": ["G17"], "topology": "T2", "families": ["F1"]},
            "enforcement": {"bound": {"G02": ["cmp-reg"]}, "unbound": ["G09"],
                            "unenforceable": ["G22"], "complete": False}} | over


def test_the_summary_distinguishes_a_design_gap_from_a_framework_gap():
    """These have different owners and different fixes, and the reviewer is the person who has to
    act on the difference. One is "select the component"; the other is "the corpus cannot bind this
    at the version you pinned" and no selection repairs it."""
    from lab.workloads.usecase import owed
    lines = owed.owed(package())
    assert any("G09" in l and "SELECTED COMPONENT" in l for l in lines)
    assert any("G22" in l and ("corpus" in l or "framework" in l) for l in lines)


def test_the_family_level_finding_no_longer_claims_to_be_an_enforcement_point():
    """`composition.unbound` names an obligation no present FAMILY carries — a shape, not something
    anyone can point at in a deployment. Reporting it as "resolved to NO enforcement point" told the
    reviewer a stronger thing than the data supports, while the real answer sat unread."""
    from lab.workloads.usecase import owed
    line = next(l for l in owed.owed(package()) if "G17" in l)
    assert "family" in line.lower()


def test_the_headline_says_whether_every_obligation_is_bound():
    from lab.workloads.usecase import owed
    assert owed.counts(package())["obligations_bound"] is False
    assert owed.counts(package(enforcement={"bound": {}, "unbound": [], "unenforceable": [],
                                            "complete": True}))["obligations_bound"] is True


def test_a_package_from_before_the_binding_existed_still_reads():
    """Approvals staged earlier stay open, so the summary must not require the new section."""
    from lab.workloads.usecase import owed
    out = owed.counts({"composition": {"unbound": ["G17"]}})
    assert out["obligations_bound"] is None and any("G17" in l for l in out["owed"])


def test_an_id_that_merely_looks_like_this_one_does_not_suppress_it():
    """Regression: the rule matched the id ANYWHERE in the free text, so "G090" or "G09-annex" in a
    note about something else deleted G09's finding — and this is the only rule that would have
    raised it. Whole ids only.

    What it still cannot do is tell a note that OWNS an obligation from one that cites it; free text
    carries no such distinction, and the structured answer (`enforcement.bind(advisory=...)`) needs
    the step-21 schema to name the obligation each note answers."""
    found = steps._obligations_bound(
        selection("cmp-reg", unresolved=["deferred pending review G090 of the standard"]),
        context())
    assert any("G09" in f for f in found)


def test_an_exact_id_in_a_note_still_suppresses():
    assert steps._obligations_bound(
        selection("cmp-reg", unresolved=["G09 — the approval surface is not chosen yet"]),
        context()) == []
