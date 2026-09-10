"""Step 22 — compose the architecture. Deterministic (D0).

Five published moves, of which only the topology is a judgement (it arrives from step 21). The rest
is derivation: the family set is the union over every step's facet vector, the modifiers come from
the facets and the criticality class, and every obligation must land on a named enforcement point.

"A composition carrying a family no step calls for is over-built" — so the test that matters most
is the one asserting a family is ABSENT.
"""
import pytest

from lab.core.usecase import seed
from lab.core.usecase import predicates
from lab.core.usecase.composition import CompositionError, compose, families_for
from lab.core.usecase.model import Step, Workflow

ANSWERS = {c: False for c in predicates.NAMED_CONDITIONS}


def s(step_id="s1", **kw):
    base = dict(activity="commit", determinism="D0", effect="none",
                reversibility="reversible", blast_radius="single record",
                audience="internal group", authorisation="autonomous", domain="general")
    return Step(id=step_id, **(base | kw))


def wf(*steps, criticality="routine"):
    return Workflow(steps=steps or (s(),), criticality=criticality)


# ---------------------------------------------------------------- always-on families

def test_the_always_families_are_present_for_any_workflow():
    present = families_for(wf(), topology="T2", conditions=ANSWERS)
    assert {"F6", "F7", "F8"} <= present


# ---------------------------------------------------------------- derived families

def test_inference_appears_only_when_a_step_is_d1_or_above():
    assert "F2" not in families_for(wf(s(determinism="D0")), topology="T2", conditions=ANSWERS)
    assert "F2" in families_for(wf(s(determinism="D1")), topology="T2", conditions=ANSWERS)


def test_action_and_transaction_appears_at_record_write_or_above():
    assert "F4" not in families_for(wf(s(effect="advisory")), topology="T2", conditions=ANSWERS)
    assert "F4" in families_for(wf(s(effect="record write")), topology="T2", conditions=ANSWERS)


def test_release_control_appears_only_at_cohort_scale_or_wider():
    assert "F13" not in families_for(wf(s(blast_radius="single subject")),
                                     topology="T2", conditions=ANSWERS)
    assert "F13" in families_for(wf(s(blast_radius="cohort")), topology="T2", conditions=ANSWERS)


def test_a_family_is_present_if_ANY_step_calls_for_it():
    """The set is the union over the whole workflow, not a property of one step."""
    quiet, loud = s("s1", determinism="D0"), s("s2", determinism="D2")
    assert "F2" in families_for(wf(quiet, loud), topology="T2", conditions=ANSWERS)


def test_egress_control_is_absent_when_nothing_leaves_and_nothing_sensitive_is_read():
    assert "F12" not in families_for(wf(s(effect="record write", sensitivity="internal")),
                                     topology="T2", conditions=ANSWERS)


def test_egress_control_appears_when_a_step_reads_restricted_data():
    assert "F12" in families_for(wf(s(sensitivity="restricted")),
                                 topology="T2", conditions=ANSWERS)


# ---------------------------------------------------------------- topology-gated families

def test_delegation_is_present_only_in_the_delegated_topology():
    assert "F14" not in families_for(wf(), topology="T2", conditions=ANSWERS)
    assert "F14" in families_for(wf(), topology="T4", conditions=ANSWERS)


def test_an_unpublished_topology_refuses():
    with pytest.raises(CompositionError):
        families_for(wf(), topology="T9", conditions=ANSWERS)


# ---------------------------------------------------------------- the F1 federated variant

def test_grounding_is_federated_only_when_sources_exceed_one():
    reading = {"step reads any grounding source": True}
    one = compose(wf(), topology="T2", conditions={**ANSWERS, **reading}, grounding_sources=1)
    many = compose(wf(), topology="T2", conditions={**ANSWERS, **reading}, grounding_sources=4)
    assert one.variants.get("F1") is None
    assert many.variants.get("F1") == "federated"


def test_the_federated_variant_needs_the_family_first():
    out = compose(wf(), topology="T2", conditions=ANSWERS, grounding_sources=4)
    assert "F1" not in out.families
    assert "F1" not in out.variants


# ---------------------------------------------------------------- modifiers

def test_criticality_travels_into_the_composition_as_a_modifier():
    out = compose(wf(criticality="safety-of-life"), topology="T2", conditions=ANSWERS)
    assert out.modifiers["criticality"] == "safety-of-life"


def test_the_human_position_modifier_is_read_from_the_authorisations_present():
    in_loop = compose(wf(s(activity="commit", authorisation="per-action human")),
                      topology="T2", conditions=ANSWERS)
    out_of_loop = compose(wf(s(activity="commit", authorisation="autonomous")),
                          topology="T2", conditions=ANSWERS)
    assert in_loop.modifiers["human_position"] == "in-loop"
    assert out_of_loop.modifiers["human_position"] == "out-of-loop"


# ---------------------------------------------------------------- enforcement points (move 5)

def test_every_family_present_names_the_guardrails_it_enforces():
    out = compose(wf(s(effect="record write")), topology="T2", conditions=ANSWERS)
    assert out.enforcement["F4"], "F4 binds G02 and G23"
    assert set(out.enforcement) == set(out.families)


def test_an_obligation_with_nowhere_to_land_is_reported_not_dropped():
    """Q5.3: every obligation resolves to a named enforcement point, or STOP. An unbound
    obligation that vanished from the composition is the failure this reports."""
    out = compose(wf(s(effect="record write")), topology="T2", conditions=ANSWERS,
                  obligations={"G02", "G23", "G99"})
    assert "G99" in out.unbound
    assert "G02" not in out.unbound


def test_a_composition_with_every_obligation_bound_reports_none_unbound():
    out = compose(wf(s(effect="record write")), topology="T2", conditions=ANSWERS,
                  obligations={"G02"})
    assert out.unbound == frozenset()


# ---------------------------------------------------------------- the translation is reviewable

def test_every_family_trigger_keeps_the_prose_it_was_translated_from():
    """The predicates here are OUR restatement of the artifact's prose. A reviewer has to be able
    to check the translation, so the original travels with it."""
    for family in seed.artifact("family_triggers")["families"]:
        assert family["prose"], family["id"]
        assert family.get("predicate") or family.get("topology"), family["id"]


def test_the_translated_families_are_exactly_the_published_ones():
    published = {r[0] for r in seed.artifact("component_families")["families"]["rows"]}
    translated = {f["id"] for f in seed.artifact("family_triggers")["families"]}
    assert translated == published


def test_a_family_predicate_reads_the_step_s_own_answers():
    """A family predicate asks a question ABOUT A STEP ("step reads any grounding source"), so
    answering it workflow-wide answers it for every step at once.

    Found live: a run whose facet vectors carried their own conditions derived its whole control
    set at step 19 and then refused at step 22, because composition passed only the workflow-wide
    answers through. The tests could not see it because they stub the derivation."""
    from lab.core.usecase import seed
    from lab.core.usecase.composition import families_for
    from lab.core.usecase.model import Step, Workflow

    # Every published condition answered — anything less is refused, by design, so a fixture that
    # answered only the one under test would be testing the refusal instead.
    no = {c: False for c in predicates.NAMED_CONDITIONS}
    grounding = Step(id="n1", activity="retrieve", determinism="D1", effect="none",
                     conditions={**no, "step reads any grounding source": True})
    plain = Step(id="n2", activity="commit", determinism="D0", effect="record write",
                 conditions=no)

    families = families_for(Workflow(steps=(grounding, plain), criticality="routine"),
                            topology="T2", conditions={})
    assert "F1" in families, "the step that answered TRUE must switch its family on"

    # ... and a workflow where nobody reads a source does not get it.
    quiet = families_for(Workflow(steps=(plain,), criticality="routine"),
                         topology="T2", conditions={})
    assert "F1" not in quiet
