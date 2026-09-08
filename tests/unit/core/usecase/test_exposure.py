"""Step 18 — derive exposure and influence per step.

Deterministic (D0), and the doc publishes the derivation as four moves, so these are not judgement
calls: every assertion below is the artifact's own rule. The pair matters because they answer
different questions — exposure is "how bad when this step WORKS", influence is "how bad when it is
WRONG" — and the guardrail mapping selects different controls from each.
"""
import pytest

from lab.core.usecase.exposure import derive, influence_of, exposure_of
from lab.core.usecase.model import Step, Workflow


def s(step_id="s1", **kw):
    base = dict(activity="commit", determinism="D0", effect="record write",
                reversibility="reversible", blast_radius="single record",
                audience="internal group", authorisation="policy-bounded", domain="general")
    return Step(id=step_id, **(base | kw))


# ---------------------------------------------------------------- move 1: base from effect

@pytest.mark.parametrize("effect,expected", [
    ("none", 0),
    ("advisory", 0),
    ("record write", 1),
    ("external communication", 2),
    ("financial or contractual commitment", 3),
    ("physical or clinical action", 3),
])
def test_exposure_starts_from_the_effect_class(effect, expected):
    assert exposure_of(s(effect=effect)) == expected


# ---------------------------------------------------------------- move 2: modifiers

def test_irreversibility_adds_one():
    assert exposure_of(s(effect="record write", reversibility="irreversible")) == 2


def test_reversible_with_cost_is_not_irreversible():
    assert exposure_of(s(effect="record write", reversibility="reversible with cost")) == 1


@pytest.mark.parametrize("radius,expected", [
    ("single record", 1), ("single subject", 1), ("cohort", 2), ("population", 3),
])
def test_blast_radius_adds_one_for_a_cohort_and_two_for_the_population(radius, expected):
    assert exposure_of(s(effect="record write", blast_radius=radius)) == expected


@pytest.mark.parametrize("audience,expected", [
    ("internal group", 1), ("customer", 1), ("public", 2), ("regulator", 2),
])
def test_a_public_or_regulator_audience_adds_one(audience, expected):
    assert exposure_of(s(effect="record write", audience=audience)) == expected


def test_modifiers_accumulate():
    assert exposure_of(s(effect="record write", reversibility="irreversible",
                         blast_radius="cohort")) == 3


# ---------------------------------------------------------------- move 3: domain floor

@pytest.mark.parametrize("domain,expected", [
    ("clinical", 2), ("safety", 2), ("financial", 1), ("HR", 1), ("general", 0),
])
def test_a_domain_raises_the_floor(domain, expected):
    assert exposure_of(s(effect="none", domain=domain)) == expected


def test_a_domain_floor_never_adds_on_top_of_a_score_already_above_it():
    """The rule says so explicitly: "Domain raises a floor; it never adds a class on top of one".
    Adding would double-count the very risk the floor exists to guarantee."""
    plain = s(effect="external communication", domain="general")
    clinical = s(effect="external communication", domain="clinical")
    assert exposure_of(plain) == 2
    assert exposure_of(clinical) == 2


# ---------------------------------------------------------------- move 4: cap

def test_class_three_is_the_ceiling():
    saturated = s(effect="physical or clinical action", reversibility="irreversible",
                  blast_radius="population", audience="public", domain="clinical")
    assert exposure_of(saturated) == 3


def test_a_step_that_saturates_is_not_worse_than_another_that_saturates():
    a = s(effect="financial or contractual commitment")
    b = s(effect="physical or clinical action", reversibility="irreversible",
          blast_radius="population")
    assert exposure_of(a) == exposure_of(b) == 3


# ---------------------------------------------------------------- influence

def test_a_step_that_determines_nothing_has_no_influence():
    wf = Workflow(steps=(s("s1", effect="none"),), criticality="routine")
    assert influence_of(wf, "s1") == 0


def test_influence_is_the_highest_exposure_it_determines_not_its_own():
    """The doc's own example: an interpretive step with effect none whose output selects a branch.
    Its exposure is 0 and its influence is whatever the branch does."""
    interpret = s("s1", activity="interpret", effect="none", determines=("s2",))
    commits = s("s2", effect="financial or contractual commitment")
    wf = Workflow(steps=(interpret, commits), criticality="routine")
    assert exposure_of(interpret) == 0
    assert influence_of(wf, "s1") == 3


def test_influence_walks_the_whole_data_flow_forward_not_just_one_hop():
    wf = Workflow(steps=(s("s1", effect="none", determines=("s2",)),
                         s("s2", effect="none", determines=("s3",)),
                         s("s3", effect="physical or clinical action")),
                  criticality="routine")
    assert influence_of(wf, "s1") == 3


def test_a_cycle_in_the_data_flow_does_not_hang_the_walk():
    wf = Workflow(steps=(s("s1", effect="none", determines=("s2",)),
                         s("s2", effect="record write", determines=("s1",))),
                  criticality="routine")
    assert influence_of(wf, "s1") == 1


def test_influence_reaches_an_effect_this_workflow_does_not_contain():
    """The Intake Agent's own classification is the case: exposure E1, influence I3, because "its
    outputs determine the controls a downstream system will carry". That system is not a step here,
    so an in-graph-only walk scores it 0 — wrong, in the direction that drops controls."""
    advisory = s("s1", activity="interpret", effect="none", determines_externally=3)
    wf = Workflow(steps=(advisory,), criticality="business-critical")
    assert exposure_of(advisory) == 0
    assert influence_of(wf, "s1") == 3


def test_an_external_effect_and_an_in_graph_one_take_the_higher():
    wf = Workflow(steps=(s("s1", effect="none", determines=("s2",), determines_externally=2),
                         s("s2", effect="record write")),
                  criticality="routine")
    assert influence_of(wf, "s1") == 2


def test_an_external_effect_outside_the_published_scale_refuses():
    with pytest.raises(ValueError):
        s(determines_externally=4)


# ---------------------------------------------------------------- gate attenuation (Q3.3)

def test_a_gate_attenuates_a_step_it_does_not_depend_on():
    """Q3.3: a gate attenuates upstream steps to what the gate permits — a human approving the
    commit means the interpretive step no longer solely determines a class-3 effect."""
    wf = Workflow(
        steps=(s("s1", effect="none", determines=("gate",)),
               s("gate", activity="decide", effect="none", determines=("s3",),
                 gate_permits=1),
               s("s3", effect="physical or clinical action")),
        criticality="routine")
    assert influence_of(wf, "s1") == 1


def test_a_gate_does_not_attenuate_the_steps_that_supply_its_predicate_inputs():
    """The exception that makes the rule safe: if the gate decides using THIS step's output, the
    step can mislead the gate, so the gate is no protection against it."""
    wf = Workflow(
        steps=(s("s1", effect="none", determines=("gate",)),
               s("gate", activity="decide", effect="none", determines=("s3",),
                 gate_permits=1, predicate_inputs=("s1",)),
               s("s3", effect="physical or clinical action")),
        criticality="routine")
    assert influence_of(wf, "s1") == 3


# ---------------------------------------------------------------- the whole workflow

def test_derive_returns_both_classes_for_every_step():
    wf = Workflow(steps=(s("s1", activity="interpret", effect="none", determines=("s2",)),
                         s("s2", effect="record write")),
                  criticality="routine")
    out = derive(wf)
    assert set(out) == {"s1", "s2"}
    assert out["s1"] == {"exposure": 0, "influence": 1}
    assert out["s2"] == {"exposure": 1, "influence": 0}


def test_an_unknown_step_id_refuses_rather_than_scoring_zero():
    wf = Workflow(steps=(s("s1"),), criticality="routine")
    with pytest.raises(KeyError):
        influence_of(wf, "nope")


def test_a_dangling_data_flow_edge_refuses_rather_than_being_ignored():
    """A `determines` naming a step that is not in the workflow means the graph is wrong. Skipping
    it would silently under-score influence, which is the direction that loses controls."""
    wf = Workflow(steps=(s("s1", effect="none", determines=("ghost",)),), criticality="routine")
    with pytest.raises(KeyError) as e:
        influence_of(wf, "s1")
    assert "ghost" in str(e.value)


# ---------------------------------------------------------------- the model's own invariants

def test_a_step_refuses_a_facet_value_outside_the_published_vocabulary():
    with pytest.raises(ValueError) as e:
        s(effect="mild inconvenience")
    assert "mild inconvenience" in str(e.value)


def test_facet_values_are_accepted_however_the_schema_spells_them():
    assert s(blast_radius="a cohort").blast_radius == "cohort"
    assert s(blast_radius="the whole population").blast_radius == "population"


def test_a_step_exposes_its_facets_for_a_predicate_to_read():
    facts = s(effect="record write", domain="clinical").facets()
    assert facts["effect"] == "record write"
    assert facts["domain"] == "clinical"
    assert facts["activity"] == "commit"
