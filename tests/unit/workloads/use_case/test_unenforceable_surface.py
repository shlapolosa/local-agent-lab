"""An obligation the chosen SURFACE cannot enforce must reach the reviewer.

Audited 23 Sep 2026. Step 20 is required to return `unenforceable_obligations` — the obligations
the surface it chose cannot carry — and nothing anywhere read the field: not the step's own gate,
not `owed()`, not the conformance summary. FR-26 ("return to step 17 and re-scope") was asserted
in the prompt and implemented nowhere.

The failure is quiet and it is the one this assessment exists to stop: the agent honestly reports
that its chosen surface cannot enforce G19, the design proceeds through 22, 21, 23, 24 and 25, and
the approver is shown a design with a known-unenforceable obligation and no line saying so.

This is a LOGIC gap, not a corpus one: `surface-enforceability` is published and is already in
step 20's context.
"""
from lab.workloads.usecase import owed


def test_an_obligation_the_surface_cannot_enforce_is_owed():
    package = {"build_surface": {
        "surface": "Foundry hosted agent",
        "unenforceable_obligations": ["G19 independent outcome monitoring"]}}
    lines = owed.owed(package)
    assert any("G19" in line for line in lines), lines
    assert any("surface" in line.lower() for line in lines), "say WHICH choice cannot carry it"


def test_it_is_reported_near_the_top_because_it_is_a_design_defect():
    """Ranked with the other enforcement failures rather than among the cost notes — an obligation
    nothing enforces is not an outstanding item, it is a design that does not hold."""
    package = {"build_surface": {"surface": "S", "unenforceable_obligations": ["G19 x"]},
               "cost": {"requires_input": ["a line could not be placed"]}}
    lines = owed.owed(package)
    assert lines.index(next(l for l in lines if "G19" in l)) < \
           lines.index(next(l for l in lines if l.startswith("cost:")))


def test_a_surface_that_enforces_everything_owes_nothing_for_it():
    assert owed.owed({"build_surface": {"surface": "S", "unenforceable_obligations": []}}) == []


def test_the_count_a_reviewer_sees_includes_it():
    counts = owed.counts({"build_surface": {"surface": "S",
                                            "unenforceable_obligations": ["G19 x", "G13 y"]}})
    assert len(counts["owed"]) >= 2 and any("G19" in line for line in counts["owed"])


def test_an_unexplicit_graph_reaches_the_reviewer_as_an_escalation():
    """Removed from the gate, so it has to arrive somewhere. A finding that is neither refused nor
    reported is one nobody ever sees."""
    lines = owed.owed({"determinism": {"graph_is_explicit": False, "governance_tier": "D2"}})
    assert any("explicit" in line.lower() for line in lines), lines
    assert any("board" in line.lower() or "escalat" in line.lower() for line in lines), lines


def test_an_explicit_graph_owes_nothing():
    assert owed.owed({"determinism": {"graph_is_explicit": True}}) == []
