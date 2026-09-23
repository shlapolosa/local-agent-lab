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

from fixtures.usecase_answers import (ASSERTIONS, BENEFIT_INPUTS, BUILD_SURFACE, CATALOGUE,
                                      COMPONENTS, COST_INPUTS, DELIVERY, DETERMINISM, FACETS,
                                      without)


def gated(number, out, context=None):
    """The rule alone — schema validation is tested next door; this is about MEANING. Every rule
    takes the context the agent was shown; step 21's reads it."""
    return step_for(number).complete(out, context=context)


def rejects(number, out, *needles, context=None):
    problems = " ".join(gated(number, out, context))
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
    """The name was right and the assertion was the opposite of it. REJECTING the answer is how it
    gets scored around: the model is told it was wrong and given one retry, so it either flips to
    `true` (and the Board escalation disappears) or holds and the run dies with no record at all.

    An unexplicit graph is a finding the framework has a route for — D3 at orchestration level —
    not a defect in the answer. It is accepted here and carried to the reviewer by `owed()`."""
    assert gated("15", dict(DETERMINISM, graph_is_explicit=False)) == []


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
    assert gated("21", COMPONENTS, CATALOGUE) == []


def test_a_component_not_in_the_catalogue_is_refused_by_its_id():
    """G04 as a gate: a component named in prose costs nothing in the join and looks free."""
    selected = [dict(COMPONENTS["selected"][0], component_id="cmp-made-up")]
    rejects("21", dict(COMPONENTS, selected=selected), "catalogue", "cmp-made-up",
            context=CATALOGUE)


def test_a_catalogue_with_no_ids_fails_the_gate_rather_than_switching_it_off():
    """A renamed column is exactly when the refusal is most wanted."""
    rejects("21", COMPONENTS, "G04", context={"component_catalogue": [{"component_id": "x"}]})


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

def test_a_well_formed_build_statement_is_accepted():
    assert gated("23", COST_INPUTS) == []
    assert gated("23", {"build_provenance": "", "notes": []}) == [], "nothing captured is honest"


def test_a_build_cost_with_no_provenance_is_refused():
    rejects("23", dict(COST_INPUTS, build_provenance=""), "provenance")


def test_a_provenance_with_no_amount_is_refused():
    rejects("23", {"build_provenance": "vendor quote", "notes": []}, "no amount")


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


# ---------------------------------------------------------------- 21 · the families still owed (soft)

def soft(number, out, context):
    return step_for(number).soft(out, context=context)


#: What the design DERIVED from the published chain (family -> guardrail -> capability -> component),
#: which is where family membership comes from — the catalogue has no such column.
WITH_FAMILIES = {"component_families": {"by_component": {"cmp-model": ["F2"], "cmp-vault": ["F4", "F5"]},
                                        "unclaimed": []},
                 "component_catalogue": [{"id": "cmp-model", "zone": "mod", "name": "Foundry model catalog"},
                                         {"id": "cmp-vault", "zone": "ident", "name": "Key Vault"}],
                 "model_summary": {"required_families": ["F2", "F4"]}}


def test_a_required_family_no_selected_component_carries_is_named_with_both_ways_out():
    problems = soft("21", COMPONENTS, WITH_FAMILIES)
    assert len(problems) == 1 and "F4" in problems[0]
    assert "select a catalogue" not in problems[0], "the finding is a record a person reads, not an instruction"
    assert "`unresolved`" in step_for("21").soft_remedy and "`families`" in step_for("21").soft_remedy


def test_a_family_named_under_unresolved_is_accepted_as_owed_rather_than_refused():
    out = dict(COMPONENTS) | {"unresolved": ["F4: no catalogue component enforces it yet"]}
    assert soft("21", out, WITH_FAMILIES) == []


def test_selecting_a_component_that_carries_the_family_satisfies_it():
    out = dict(COMPONENTS) | {"selected": COMPONENTS["selected"] + [
        {"capability": "secrets", "component_id": "cmp-vault", "component": "Key Vault",
         "rejected_alternatives": ["env vars"]}]}
    assert soft("21", out, WITH_FAMILIES) == []


def test_without_a_derivation_or_a_column_the_rule_makes_no_claim():
    """Neither derived nor published means nothing is known; a rule that refused here would refuse
    work nobody could have done."""
    assert soft("21", COMPONENTS, dict(CATALOGUE) | {"model_summary": {"required_families": ["F2"]}}) == []


def test_a_family_the_corpus_is_silent_about_is_not_demanded():
    """Ten of twenty-six published guardrails name a capability, so some families resolve to no
    component at all — the corpus being silent, not the design failing."""
    ctx = dict(WITH_FAMILIES)
    ctx["component_families"] = {"by_component": {"cmp-model": ["F2"]}, "unclaimed": ["F4"]}
    assert soft("21", COMPONENTS, ctx) == []


def test_a_published_catalogue_column_is_believed_over_the_derivation():
    ctx = dict(WITH_FAMILIES)
    ctx["component_catalogue"] = [{"id": "cmp-model", "zone": "mod", "families": ["F2", "F4"]}]
    assert soft("21", COMPONENTS, ctx) == []


def test_a_run_with_no_composition_requires_nothing():
    assert soft("21", COMPONENTS, dict(WITH_FAMILIES) | {"model_summary": {}}) == []
    assert step_for("21").soft_key == "unresolved"


# ---------------------------------------------------------------- 15 and 17 · every node, or none

GRAPH = {"workflow_graph": {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]}}


def test_a_facet_set_covering_one_node_of_three_is_refused_naming_the_nodes_it_skipped():
    """Run 5, 15 Sep 2026: ONE vector for a ten-node graph. It derived cleanly, and the exposure,
    the obligations and the composition all came back describing that one node."""
    out = {"steps": [dict(FACETS["steps"][0], id="n2")]}
    problems = " ".join(gated("17", out, context=GRAPH))
    assert "'n1'" in problems and "'n3'" in problems and "covers 1" in problems


def test_a_vector_for_a_node_the_graph_does_not_have_is_refused():
    out = {"steps": [dict(FACETS["steps"][0], id=i) for i in ("n1", "n2", "n3", "n9")]}
    assert any("n9" in p and "not nodes" in p for p in gated("17", out, context=GRAPH))


def test_one_vector_per_node_passes_and_a_duplicate_does_not():
    full = {"steps": [dict(FACETS["steps"][0], id=i) for i in ("n1", "n2", "n3")]}
    assert gated("17", full, context=GRAPH) == []
    twice = {"steps": full["steps"] + [dict(FACETS["steps"][0], id="n1")]}
    assert any("more than once" in p for p in gated("17", twice, context=GRAPH))


def test_without_a_graph_in_context_the_coverage_rule_says_nothing():
    assert gated("17", FACETS) == []


def test_the_determinism_tiering_is_held_to_the_same_coverage():
    out = {"steps": [{"id": "n1", "tier": "D1", "necessity": "by necessity"}],
           "governance_tier": "D1", "graph_is_explicit": True}
    assert any("no determinism tier" in p and "'n2'" in p for p in gated("15", out, context=GRAPH))
    full = {"steps": [{"id": i, "tier": "D1", "necessity": "by necessity"} for i in ("n1", "n2", "n3")],
            "governance_tier": "D1", "graph_is_explicit": True}
    assert gated("15", full, context=GRAPH) == []


# ---------------------------------------------------------------- 21 · something runs the use case

CROSS_CUTTING = {"component_catalogue": [{"id": "cmp-entra", "zone": "ident", "name": "Entra"},
                                         {"id": "cmp-sentinel", "zone": "obs", "name": "Sentinel"},
                                         {"id": "cmp-model", "zone": "mod", "name": "Model catalog"}]}


def _picked(*ids):
    return {"selected": [{"capability": "c", "component_id": i, "component": i,
                          "rejected_alternatives": ["x"]} for i in ids],
            "tradeoffs": [], "unresolved": []}


def test_a_selection_of_only_cross_cutting_components_is_a_control_plane_with_nothing_inside_it():
    """Run 5: sixteen components, every one identity, observability, platform or gateway — and a
    solution view that was a parts list."""
    problems = soft("21", _picked("cmp-entra", "cmp-sentinel"), CROSS_CUTTING)
    assert any("control plane with nothing inside it" in p for p in problems)
    assert "ident" in problems[0] and "obs" in problems[0]


def test_one_component_that_runs_the_use_case_satisfies_it():
    assert soft("21", _picked("cmp-entra", "cmp-model"), CROSS_CUTTING) == []


def test_a_catalogue_with_no_zone_column_makes_no_claim_and_a_named_reason_is_accepted():
    bare = {"component_catalogue": [{"id": "cmp-entra", "name": "Entra"}]}
    assert soft("21", _picked("cmp-entra"), bare) == []
    named = dict(_picked("cmp-entra"), unresolved=["no runtime component: the agent runtime is a "
                                                   "zone this tenant has not catalogued"])
    assert soft("21", named, CROSS_CUTTING) == []
