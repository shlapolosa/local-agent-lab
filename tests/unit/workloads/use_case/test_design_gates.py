"""The eight design-side completeness rules — what each one REFUSES.

These rules are the deterministic gate. They are the only thing between a model under length
pressure and a decision record that names nothing sacrificed, a service level with no source, or a
facet vector that leaves a guardrail's condition unanswered. A rule that has never been observed to
reject is a rule nobody has checked, so each one gets an accepting case and a rejecting case, and
the rejection is asserted by its SUBJECT rather than its wording.
"""
import pytest

from lab.core.usecase import seed
from lab.core.usecase import predicates
from lab.workloads.usecase.steps import BUSINESS_CASE_SECTIONS, step_for

from fixtures.usecase_answers import (ASSERTIONS, BENEFIT_INPUTS, BUILD_SURFACE, COMPONENTS,
                                      COST_INPUTS, DELIVERY, DETERMINISM, FACETS, without)


def gated(number, out):
    """The rule alone — schema validation is tested next door; this is about MEANING."""
    return step_for(number).complete(out)


def rejects(number, out, *needles):
    problems = " ".join(gated(number, out))
    assert problems, "the rule accepted something it should refuse"
    for needle in needles:
        assert needle in problems, problems


# ---------------------------------------------------------------- 13 · assertions

def test_a_well_formed_assertion_set_is_accepted():
    assert gated("13", ASSERTIONS) == []


def test_an_assertion_evaluated_against_the_workflows_own_output_is_refused():
    """"The workflow says it worked" is true whenever the workflow says it is. It measures nothing."""
    rejects("13", {"assertions": [dict(ASSERTIONS["assertions"][0], reads_workflow_output=True)]},
            "workflow")


# ---------------------------------------------------------------- 15 · determinism

def test_a_well_formed_determinism_classification_is_accepted():
    assert gated("15", DETERMINISM) == []


def test_a_non_deterministic_step_with_no_necessity_test_is_refused():
    """Every non-D0 step is asked ONCE whether it is irreducible. Skipping it is how a lookup table
    becomes an agent."""
    rejects("15", {"steps": [{"id": "n1", "tier": "D2"}], "governance_tier": "D2",
                   "graph_is_explicit": True}, "necessity")


def test_non_determinism_by_default_re_tiers_to_d0():
    rejects("15", {"steps": [{"id": "n1", "tier": "D2", "necessity": "by default"}],
                   "governance_tier": "D2", "graph_is_explicit": True}, "BY DEFAULT")


def test_the_governance_tier_must_be_the_maximum_of_the_step_tiers():
    rejects("15", {"steps": [{"id": "a", "tier": "D0"}, {"id": "b", "tier": "D2",
                                                         "necessity": "by necessity"}],
                   "governance_tier": "D0", "graph_is_explicit": True}, "MAXIMUM")


def test_an_inexplicit_graph_must_be_said_rather_than_scored_around():
    rejects("15", dict(DETERMINISM, graph_is_explicit=False), "escalation")


# ---------------------------------------------------------------- 17 · facet vectors

def test_a_well_formed_facet_vector_set_is_accepted():
    assert gated("17", FACETS) == []


def test_an_unjustified_override_is_refused():
    step = dict(FACETS["steps"][0], overrides=[{"facet": "blast_radius", "justification": "n/a"}])
    rejects("17", {"steps": [step]}, "justification")


def test_a_facet_vector_that_decides_its_own_exposure_is_refused():
    """Exposure follows from these facets by a published derivation. Deciding it here would make
    the derivation an opinion."""
    rejects("17", {"steps": [dict(FACETS["steps"][0], exposure=2)]}, "derived")


def test_a_step_leaving_a_published_condition_unanswered_is_refused():
    step = dict(FACETS["steps"][0])
    step["conditions"] = {c: False for c in list(predicates.NAMED_CONDITIONS)[:-1]}
    rejects("17", {"steps": [step]}, "unanswered")


def test_no_step_at_all_is_refused():
    rejects("17", {"steps": []}, "no step")


# ---------------------------------------------------------------- 20 · build surface

def test_a_well_formed_build_surface_is_accepted():
    assert gated("20", BUILD_SURFACE) == []


def test_a_surface_chosen_without_asking_the_incumbent_question_is_refused():
    """An incumbent that satisfies the obligations is usually the right answer, and the question
    stops being asked the moment nothing checks that it was."""
    rejects("20", dict(BUILD_SURFACE, incumbent_considered=False), "incumbent")


def test_rejecting_an_incumbent_without_naming_what_it_failed_is_refused():
    """"We chose something else" is not a decision record."""
    rejects("20", dict(BUILD_SURFACE, incumbent="the referrals platform",
                       incumbent_failed_obligations=[]), "failed")


# ---------------------------------------------------------------- 21 · component selection

def test_a_well_formed_component_selection_is_accepted():
    assert gated("21", COMPONENTS) == []


def test_a_component_chosen_with_no_rejected_alternative_is_refused():
    selected = [dict(COMPONENTS["selected"][0], rejected_alternatives=[])]
    rejects("21", dict(COMPONENTS, selected=selected), "alternative")


def test_a_tradeoff_with_no_compensating_control_is_refused():
    rejects("21", dict(COMPONENTS, tradeoffs=[{"sacrificed": "latency", "for": "cost",
                                               "compensating_control": "",
                                               "review_trigger": "10k/day"}]), "compensating")


def test_a_tradeoff_with_no_review_trigger_is_refused():
    """A sacrifice with no condition for revisiting it is permanent by accident."""
    rejects("21", dict(COMPONENTS, tradeoffs=[{"sacrificed": "latency", "for": "cost",
                                               "compensating_control": "a queue",
                                               "review_trigger": ""}]), "review")


# ---------------------------------------------------------------- 23 · cost inputs

def test_a_well_formed_cost_selection_is_accepted():
    assert gated("23", COST_INPUTS) == []


def test_a_resource_that_names_nothing_that_switched_it_on_is_refused():
    """A bill nobody can audit is a bill nobody should approve."""
    rejects("23", dict(COST_INPUTS, switched_on_by={}), "audit")


def test_a_build_cost_with_no_provenance_is_refused():
    rejects("23", dict(COST_INPUTS, build_amount=250000), "provenance")


def test_a_provenance_with_no_amount_is_refused():
    rejects("23", dict(COST_INPUTS, build_provenance="vendor quote"), "no amount")


def test_costing_nothing_at_all_is_refused():
    rejects("23", {"resources": [], "switched_on_by": {}, "envelope": "expected",
                   "unpriceable": []}, "cost of nothing")


def test_a_design_that_switched_nothing_on_but_flagged_a_gap_is_accepted():
    """The honest empty case: nothing could be priced and it SAYS so."""
    assert gated("23", {"resources": [], "switched_on_by": {}, "envelope": "expected",
                        "unpriceable": ["an agent runtime nobody has a line for"]}) == []


# ---------------------------------------------------------------- 24 · benefit inputs

def test_a_well_formed_benefit_evidence_set_is_accepted():
    assert gated("24", BENEFIT_INPUTS) == []


def test_an_effort_figure_with_no_source_is_refused():
    rejects("24", {"effort": [without(BENEFIT_INPUTS["effort"][0], "source")],
                   "sensitivity_flags": [], "data_fully_digital": True,
                   "excluded_value": [], "unsupplied": []}, "source")


def test_a_change_that_makes_the_task_take_longer_is_refused_as_a_benefit():
    row = dict(BENEFIT_INPUTS["effort"][0], current_minutes=10, expected_minutes=30)
    rejects("24", dict(BENEFIT_INPUTS, effort=[row]), "LONGER")


def test_no_evidence_and_nothing_declared_unsupplied_is_refused():
    """A case with no evidence either way is not a case worth nothing, and only one of them should
    reach a funding decision."""
    rejects("24", {"effort": [], "sensitivity_flags": [], "data_fully_digital": True,
                   "excluded_value": [], "unsupplied": []}, "unsupplied")


def test_no_evidence_but_an_honest_declaration_is_accepted():
    assert gated("24", {"effort": [], "sensitivity_flags": [], "data_fully_digital": True,
                        "excluded_value": [],
                        "unsupplied": ["nobody gave a headcount for the nursing team"]}) == []


# ---------------------------------------------------------------- 25 · delivery artifacts

def test_a_well_formed_delivery_set_is_accepted():
    assert gated("25", DELIVERY) == []


@pytest.mark.parametrize("missing", BUSINESS_CASE_SECTIONS)
def test_a_business_case_missing_any_one_section_is_refused(missing):
    """Named, not counted: an approver reading seven of eight sections cannot tell which is absent."""
    sections = [s for s in DELIVERY["business_case"]
                if s["section"].lower() != missing]
    rejects("25", dict(DELIVERY, business_case=sections), missing)


def test_the_sections_this_rule_requires_are_the_ones_the_corpus_publishes():
    """The tuple is a copy of a governed artifact and would drift silently the moment one was
    corrected."""
    published = {row[1].strip().lower()
                 for row in seed.artifact("business_case_sections")["sections"]["rows"] if row[1]}
    assert set(BUSINESS_CASE_SECTIONS) == published


def test_a_decision_record_that_sacrificed_nothing_is_refused():
    """The field that makes the record worth keeping. A decision that cost nothing was a preference."""
    record = without(DELIVERY["decision_records"][0], "sacrificed")
    rejects("25", dict(DELIVERY, decision_records=[record]), "sacrificed")


def test_a_decision_record_considering_one_option_is_refused():
    record = dict(DELIVERY["decision_records"][0], options=["the only thing we thought of"])
    rejects("25", dict(DELIVERY, decision_records=[record]), "two options")


def test_a_service_level_with_no_source_is_refused():
    """An invented latency target is a promise somebody will be held to."""
    contract = without(DELIVERY["service_contracts"][0], "service_level_source")
    rejects("25", dict(DELIVERY, service_contracts=[contract]), "source")


def test_a_work_item_with_no_owner_is_refused():
    item = without(DELIVERY["work_items"][0], "owner")
    rejects("25", dict(DELIVERY, work_items=[item]), "owner")
