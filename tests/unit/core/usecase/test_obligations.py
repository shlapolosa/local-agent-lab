"""Step 19 — evaluate obligations. Deterministic (D0).

Three things happen here and they are separate on purpose: the guardrail PREDICATES are evaluated
against every step's facet vector (Q3.1); the risk-class MAPPING adds what the step's exposure and
influence classes mandate regardless of any predicate (E.6); and the COMMIT INVARIANT is tested
across the workflow (Q3.2). A control requirement set that missed any one of them would look
complete.
"""
import pytest

from lab.core.usecase import seed
from lab.core.usecase import predicates
from lab.core.usecase.model import Step, Workflow
from lab.core.usecase.obligations import (
    ObligationError,
    Obligation,
    commit_invariant,
    derive,
    mandatory_for,
    triggered_for,
)

ANSWERS = {c: False for c in predicates.NAMED_CONDITIONS}


def s(step_id="s1", **kw):
    base = dict(activity="commit", determinism="D0", effect="record write",
                reversibility="reversible", blast_radius="single record",
                audience="internal group", authorisation="policy-bounded", domain="general")
    return Step(id=step_id, **(base | kw))


# ---------------------------------------------------------------- the class mapping (E.6)

def test_the_baseline_applies_at_every_class_including_the_lowest():
    baseline = {o.guardrail for o in mandatory_for(0, 0) if o.guardrail}
    assert {"G01", "G03", "G04", "G10", "G14", "G15"} <= baseline


def test_a_higher_exposure_class_inherits_the_one_below_it():
    """The artifact writes "All of E1" rather than repeating it, so the inheritance is real and
    an implementation that read each cell literally would drop controls at E2 and E3."""
    e1 = {o.guardrail for o in mandatory_for(1, 0)}
    e2 = {o.guardrail for o in mandatory_for(2, 0)}
    e3 = {o.guardrail for o in mandatory_for(3, 0)}
    assert e1 < e2 < e3
    assert "G02" in e3, "E3 must still carry E1's tool scoping"


def test_influence_classes_inherit_independently_of_exposure():
    i3 = {o.guardrail for o in mandatory_for(0, 3)}
    assert "G18" in i3, "I3 inherits I2's recall target"
    assert "G19" in i3


def test_an_obligation_without_a_guardrail_id_is_still_an_obligation():
    """I1 mandates "an evaluation harness with a stated accuracy target" and cites no G-number.
    Keeping only the ones with ids would silently drop it."""
    narrative = [o for o in mandatory_for(0, 1) if not o.guardrail]
    assert narrative, "I1's evaluation-harness obligation carries no guardrail id"
    assert any("harness" in o.text for o in narrative)


def test_every_obligation_records_which_class_mandated_it():
    for o in mandatory_for(2, 2):
        assert o.source, o


def test_a_class_outside_the_published_scale_refuses():
    with pytest.raises(ObligationError):
        mandatory_for(4, 0)


# ---------------------------------------------------------------- predicates (Q3.1)

def test_a_predicate_that_fires_puts_its_guardrail_in_the_set():
    step = s(effect="external communication", authorisation="policy-bounded")
    fired = triggered_for(Workflow(steps=(step,)), "s1", conditions=ANSWERS)
    assert "G09" in fired          # effect ∈ {external communication} ∧ authorisation ≠ per-action human


def test_a_predicate_that_does_not_fire_stays_out():
    step = s(effect="external communication", authorisation="per-action human")
    assert "G09" not in triggered_for(Workflow(steps=(step,)), "s1", conditions=ANSWERS)


def test_the_always_guardrails_fire_for_every_step():
    fired = triggered_for(Workflow(steps=(s(),)), "s1", conditions=ANSWERS)
    assert {"G01", "G04", "G10", "G14"} <= fired


def test_a_retired_guardrail_never_fires():
    fired = triggered_for(Workflow(steps=(s(),)), "s1", conditions=ANSWERS)
    assert not ({"G11", "G12"} & fired)


def test_an_unanswered_named_condition_refuses_the_whole_step():
    """Step 19 must not quietly produce a short control set. If a condition nobody answered could
    have fired a guardrail, the step cannot be evaluated."""
    with pytest.raises(ObligationError) as e:
        triggered_for(Workflow(steps=(s(activity="retrieve"),)), "s1", conditions={})
    assert "condition" in str(e.value).lower()


def test_the_workflow_level_guardrail_reads_the_workflow():
    quiet = Workflow(steps=(s("s1", effect="none"),))
    loud = Workflow(steps=(s("s1", activity="interpret", effect="none", determines=("s2",)),
                           s("s2", effect="physical or clinical action")))
    assert "G19" not in triggered_for(quiet, "s1", conditions=ANSWERS)
    assert "G19" in triggered_for(loud, "s1", conditions=ANSWERS)


# ---------------------------------------------------------------- the commit invariant (Q3.2)

def test_a_deterministic_commit_satisfies_the_invariant():
    wf = Workflow(steps=(s("s1", determinism="D0", effect="external communication"),))
    assert commit_invariant(wf) == []


def test_a_non_deterministically_informed_irreversible_commit_violates_it():
    wf = Workflow(steps=(s("s1", activity="interpret", determinism="D2", effect="none",
                           determines=("s2",)),
                         s("s2", effect="external communication", authorisation="autonomous")))
    violations = commit_invariant(wf)
    assert [v.step for v in violations] == ["s2"]
    assert "s1" in violations[0].reason


def test_per_action_human_authorisation_satisfies_the_invariant():
    wf = Workflow(steps=(s("s1", activity="interpret", determinism="D2", effect="none",
                           determines=("s2",)),
                         s("s2", effect="external communication",
                           authorisation="per-action human")))
    assert commit_invariant(wf) == []


def test_a_gate_between_the_inference_and_the_commit_satisfies_the_invariant():
    wf = Workflow(steps=(s("s1", activity="interpret", determinism="D2", effect="none",
                           determines=("gate",)),
                         s("gate", activity="decide", effect="none", determines=("s2",),
                           gate_permits=1),
                         s("s2", effect="external communication", authorisation="autonomous")))
    assert commit_invariant(wf) == []


def test_a_reversible_internal_write_is_not_a_commit_for_this_purpose():
    """The invariant is about irreversible or externally visible effects, not about every write."""
    wf = Workflow(steps=(s("s1", activity="interpret", determinism="D2", effect="none",
                           determines=("s2",)),
                         s("s2", effect="record write", reversibility="reversible",
                           authorisation="autonomous")))
    assert commit_invariant(wf) == []


# ---------------------------------------------------------------- the whole set

def test_derive_returns_a_control_requirement_set_per_step():
    wf = Workflow(steps=(s("s1", effect="external communication"),), criticality="business-critical")
    out = derive(wf, conditions=ANSWERS)
    assert set(out.by_step) == {"s1"}
    assert out.by_step["s1"], "every step carries at least the baseline"
    assert out.commit_invariant_holds is True


def test_derive_merges_triggered_and_mandated_without_duplicating():
    wf = Workflow(steps=(s("s1", effect="external communication"),))
    ids = [o.guardrail for o in derive(wf, conditions=ANSWERS).by_step["s1"] if o.guardrail]
    assert len(ids) == len(set(ids)), ids


def test_derive_reports_a_commit_invariant_breach_rather_than_raising():
    """A breach is a finding for the architect, not a crash — the run must still produce the set
    that shows why."""
    wf = Workflow(steps=(s("s1", activity="interpret", determinism="D2", effect="none",
                           determines=("s2",)),
                         s("s2", effect="external communication", authorisation="autonomous")))
    out = derive(wf, conditions=ANSWERS)
    assert out.commit_invariant_holds is False
    assert out.violations


def test_every_obligation_names_the_guardrail_or_the_text_it_came_from():
    wf = Workflow(steps=(s(),))
    for o in derive(wf, conditions=ANSWERS).by_step["s1"]:
        assert isinstance(o, Obligation)
        assert o.guardrail or o.text
        assert o.source
