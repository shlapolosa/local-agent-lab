"""Steps 14 and 16 — the readiness verdict and the feasibility verdict. Both deterministic (D0).

These are the two cheap gates, and they are the only places the process stops a use case before an
architect has spent time on it. Both rule from DERIVED evidence rather than an estimate, which is
what makes them D0 at all — an earlier draft's coarse determinism estimate is exactly what was
removed to get here.
"""
import pytest

from lab.core.usecase.gates import (
    GateError,
    Feasibility,
    Readiness,
    feasibility_verdict,
    readiness_verdict,
)

ALL_EVIDENCED = {"A": True, "B": True, "C": True, "D": True}


# ---------------------------------------------------------------- step 14: readiness

def test_all_four_gates_evidenced_passes():
    out = readiness_verdict(ALL_EVIDENCED, criticality="routine")
    assert out.verdict == Readiness.PASS
    assert out.failed == ()


def test_an_unevidenced_semantic_or_knowledge_gate_without_a_plan_fails():
    out = readiness_verdict({**ALL_EVIDENCED, "B": False}, criticality="routine")
    assert out.verdict == Readiness.FAIL
    assert "B" in out.failed


@pytest.mark.parametrize("gate", ["B", "C"])
def test_a_partial_semantic_or_knowledge_gate_with_an_owner_and_a_date_is_conditional(gate):
    out = readiness_verdict({**ALL_EVIDENCED, gate: "partial"}, criticality="business-critical",
                            conditions={gate: {"owner": "the data steward", "closes": "2026-10-31"}})
    assert out.verdict == Readiness.CONDITIONAL
    assert out.conditions[gate]["owner"]


def test_a_partial_gate_without_a_named_owner_is_a_fail_not_a_conditional():
    """"A named owner and dated closure plan" is the condition, not a formality — a conditional
    pass with nobody accountable is a fail that has been dressed up."""
    out = readiness_verdict({**ALL_EVIDENCED, "B": "partial"}, criticality="routine",
                            conditions={"B": {"closes": "2026-10-31"}})
    assert out.verdict == Readiness.FAIL


def test_a_partial_gate_without_a_closure_date_is_a_fail():
    out = readiness_verdict({**ALL_EVIDENCED, "B": "partial"}, criticality="routine",
                            conditions={"B": {"owner": "the data steward"}})
    assert out.verdict == Readiness.FAIL


def test_conditional_is_unavailable_for_a_safety_of_life_class():
    """Stated outright in the artifact. The class that most needs the ontology settled is the one
    least allowed to proceed without it."""
    out = readiness_verdict({**ALL_EVIDENCED, "B": "partial"}, criticality="safety-of-life",
                            conditions={"B": {"owner": "a steward", "closes": "2026-10-31"}})
    assert out.verdict == Readiness.FAIL


@pytest.mark.parametrize("gate", ["A", "D"])
def test_gates_a_and_d_are_never_conditional(gate):
    """Only B or C may be partial. Business grounding and criticality are load-bearing for
    everything after them."""
    out = readiness_verdict({**ALL_EVIDENCED, gate: "partial"}, criticality="routine",
                            conditions={gate: {"owner": "someone", "closes": "2026-10-31"}})
    assert out.verdict == Readiness.FAIL


def test_a_missing_gate_refuses_rather_than_being_read_as_evidenced():
    with pytest.raises(GateError) as e:
        readiness_verdict({"A": True, "B": True, "C": True}, criticality="routine")
    assert "D" in str(e.value)


def test_the_verdict_names_every_failed_gate_not_just_the_first():
    out = readiness_verdict({"A": True, "B": False, "C": False, "D": True}, criticality="routine")
    assert set(out.failed) == {"B", "C"}


# ---------------------------------------------------------------- step 16: feasibility

def test_no_capability_match_rejects():
    out = feasibility_verdict(capability_matched=False, existing_realisation=False,
                              capability_is_commodity=False, capability_is_mature=False,
                              capability_meets_target=False)
    assert out.verdict == Feasibility.REJECT
    assert "capability" in out.rule.lower()


def test_an_existing_realisation_returns_the_use_case_as_an_integration():
    out = feasibility_verdict(capability_matched=True, existing_realisation=True,
                              capability_is_commodity=False, capability_is_mature=False,
                              capability_meets_target=False)
    assert out.verdict == Feasibility.INTEGRATION


def test_a_commodity_mature_on_target_capability_rejects():
    out = feasibility_verdict(capability_matched=True, existing_realisation=False,
                              capability_is_commodity=True, capability_is_mature=True,
                              capability_meets_target=True)
    assert out.verdict == Feasibility.REJECT


@pytest.mark.parametrize("commodity,mature,on_target", [
    (True, True, False), (True, False, True), (False, True, True),
])
def test_the_commodity_rejection_needs_all_three_heat_map_conditions(commodity, mature, on_target):
    out = feasibility_verdict(capability_matched=True, existing_realisation=False,
                              capability_is_commodity=commodity, capability_is_mature=mature,
                              capability_meets_target=on_target)
    assert out.verdict == Feasibility.PROCEED


def test_otherwise_it_proceeds():
    out = feasibility_verdict(capability_matched=True, existing_realisation=False,
                              capability_is_commodity=False, capability_is_mature=False,
                              capability_meets_target=False)
    assert out.verdict == Feasibility.PROCEED


def test_no_capability_match_beats_an_existing_realisation():
    """Order matters: the rules are applied as published, and the first that fires decides."""
    out = feasibility_verdict(capability_matched=False, existing_realisation=True,
                              capability_is_commodity=False, capability_is_mature=False,
                              capability_meets_target=False)
    assert out.verdict == Feasibility.REJECT


def test_every_verdict_records_the_rule_that_fired():
    """FR-10 and the design pack both need it: "the feasibility verdict with the rule that fired"
    is a persisted output, because a rejection an architect cannot interrogate is not reviewable."""
    for kwargs in [
        dict(capability_matched=False, existing_realisation=False, capability_is_commodity=False,
             capability_is_mature=False, capability_meets_target=False),
        dict(capability_matched=True, existing_realisation=True, capability_is_commodity=False,
             capability_is_mature=False, capability_meets_target=False),
        dict(capability_matched=True, existing_realisation=False, capability_is_commodity=False,
             capability_is_mature=False, capability_meets_target=False),
    ]:
        assert feasibility_verdict(**kwargs).rule


def test_a_halting_verdict_says_so_so_the_workflow_can_stop():
    """FR-11: a reject or integration halts the run; steps 17-25 are not attempted."""
    reject = feasibility_verdict(capability_matched=False, existing_realisation=False,
                                 capability_is_commodity=False, capability_is_mature=False,
                                 capability_meets_target=False)
    proceed = feasibility_verdict(capability_matched=True, existing_realisation=False,
                                  capability_is_commodity=False, capability_is_mature=False,
                                  capability_meets_target=False)
    assert reject.halts is True
    assert proceed.halts is False
