"""The screening agents: their gate, their context, and the anchoring control.

The agents themselves are not tested here — a model's judgement is not a unit test's business. What
IS tested is everything deterministic around them: the schema each answer must satisfy, the
completeness rules a schema cannot express, what each step is allowed to read, and the one retry.

Every completeness rule below quotes the sentence of the specification it enforces, because a rule
whose reason is not written down gets relaxed by whoever meets it next.
"""
import asyncio

import pytest

from lab.workloads.usecase import agents as A
from lab.workloads.usecase.gates import GateFailed, gate, json_of, run_gated
from lab.workloads.usecase.steps import STEPS, schema, step_for


class FakeAgent:
    """Replies in order. Records what it was asked, so a test can assert on the retry's message."""

    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    async def run(self, message):
        self.asked.append(message)
        return self.replies.pop(0) if self.replies else "{}"


def gated(step_number, out):
    step = step_for(step_number)
    return gate(out, validator=step.validator(), normalise=step.normalise,
                complete=step.complete)


# ---------------------------------------------------------------- the registry

def test_every_step_has_a_schema_a_prompt_and_a_completeness_rule():
    for step in STEPS:
        assert schema(step.key)["title"] == step.key
        assert step.prompt().strip()
        assert callable(step.complete)


def test_every_step_belongs_to_a_named_bounded_context():
    """Grouped by the domain they reason about, not the verb they perform — one vocabulary, one
    corpus, one owning role."""
    assert {s.service for s in STEPS} == {
        "Business Analyst", "Business Architect", "Application Architect",
        "Product Owner", "Data Architect", "Risk Officer"}


def test_the_schema_travels_in_the_prompt_the_gate_validates_against():
    """A model that has read the schema is being asked for the thing that will be checked, rather
    than for a description of it."""
    body = A.instructions(step_for("4"))
    assert "behavioural" in body and "additionalProperties" in body


# ---------------------------------------------------------------- step 3: framing

def test_a_problem_stated_as_a_solution_is_rejected():
    """FR-05. The problem is whatever the proposed answer was meant to fix, and finding it is the
    whole job — a use case framed as its solution has skipped the assessment it came for."""
    bad = gated("3", {"problem": "We need a chatbot to answer referral questions from clinicians",
                      "for_whom": "clinicians", "expected_change": "fewer calls",
                      "accountable_owner": "Dr Aisha Khan"})
    assert any("solution" in p for p in bad)


def test_shared_accountability_is_rejected():
    """FR-05 again: "reject shared accountability". A use case everyone owns is one nobody answers
    for."""
    for owner in ("Dr Khan and Dr Patel", "the referrals team", "Ops / Clinical"):
        bad = gated("3", {"problem": "Referrals wait eleven days before anyone reads them",
                          "for_whom": "clinicians", "expected_change": "shorter wait",
                          "accountable_owner": owner})
        assert any("accountab" in p for p in bad), owner


def test_a_well_framed_use_case_passes():
    assert gated("3", {"problem": "Referrals wait eleven days before a clinician reads them",
                       "for_whom": "referring GPs and the triage team",
                       "expected_change": "median time to first read falls below two days",
                       "accountable_owner": "Dr Aisha Khan"}) == []


# ---------------------------------------------------------------- step 4: decomposition

def test_an_implied_order_in_the_behavioural_list_is_rejected():
    """E0.2: "sequence nothing — an implied order means you have skipped to E0.7". The order
    assumed here would survive unexamined into the workflow graph."""
    bad = gated("4", {"active": [{"name": "triage nurse"}],
                      "behavioural": [{"name": "first receive referral"},
                                      {"name": "then assess urgency"}],
                      "passive": [{"name": "referral"}]})
    assert any("order" in p for p in bad)


@pytest.mark.parametrize("empty", ["active", "behavioural", "passive"])
def test_an_empty_element_list_is_rejected(empty):
    payload = {"active": [{"name": "nurse"}], "behavioural": [{"name": "assess referral"}],
               "passive": [{"name": "referral"}]}
    payload[empty] = []
    assert any(empty in p for p in gated("4", payload))


# ---------------------------------------------------------------- step 5: capabilities

def test_a_match_with_no_capability_id_is_rejected():
    """FR-07: "never create a capability to accommodate an unmatched function". A match with no id
    is an invented capability wearing a label."""
    bad = gated("5", {"matched": [{"function": "assess referral", "capability_id": "",
                                   "confidence": "lookup"}],
                      "functions_without_capability": [], "capabilities_without_function": []})
    assert any("invented" in p or "capability id" in p for p in bad)


def test_coverage_must_be_reported_both_ways_even_when_empty():
    bad = gated("5", {"matched": [{"function": "assess referral", "capability_id": "c1",
                                   "confidence": "lookup"}],
                      "functions_without_capability": []})
    assert bad, "the second direction is required even when it is empty"


def test_an_unmatched_function_is_a_complete_answer():
    """A gap is a finding, not a failure — it is what the Review Board adjudicates."""
    assert gated("5", {"matched": [], "functions_without_capability": ["assess referral"],
                       "capabilities_without_function": [],
                       "gap_flags": [{"what": "no L3 capability for referral assessment",
                                      "owning_body": "Enterprise Architecture"}]}) == []


# ---------------------------------------------------------------- step 6: realisations

def test_a_survey_result_without_a_gap_flag_is_rejected():
    """FR-08 / §4.3: "treat a survey result as a gap flag candidate rather than a silent
    assumption"."""
    bad = gated("6", {"matched": [{"element": "triage system", "realised_by": "maybe PAS",
                                   "confidence": "survey"}],
                      "unrealised": [], "existing": False})
    assert any("survey" in p for p in bad)


# ---------------------------------------------------------------- step 7: the provisional band

def test_the_band_must_declare_itself_provisional():
    """It exists for the feasibility verdict only; step 12 derives the confirmed class
    independently."""
    bad = gated("7", {"band": "business-critical", "provisional": False,
                      "dominant_failure_mode": "a referral is missed and a patient deteriorates"})
    assert bad


# ---------------------------------------------------------------- step 8: quality attributes

@pytest.mark.parametrize("taken_from", ["assumed", "estimated", "n/a"])
def test_an_invented_service_level_is_rejected(taken_from):
    """FR-13: taken from an existing business commitment, or it is a gap flag. A number nobody
    committed to will be designed against, costed, and then missed.

    A plausible-looking source is the dangerous case — an EMPTY one fails the schema before the
    completeness rule is reached, which is the cheaper failure and is asserted separately."""
    bad = gated("8", {"scenarios": [{"function": "assess referral", "response_measure": 2,
                                     "unit": "days", "taken_from": taken_from}]})
    assert any("commitment" in p for p in bad)


def test_a_blank_commitment_fails_the_schema_before_the_rule_is_reached():
    bad = gated("8", {"scenarios": [{"function": "assess referral", "response_measure": 2,
                                     "unit": "days", "taken_from": ""}]})
    assert bad


def test_no_scenarios_and_no_gap_flags_is_rejected():
    assert gated("8", {"scenarios": []})


def test_a_scenario_from_a_real_commitment_passes():
    assert gated("8", {"scenarios": [{"function": "assess referral", "response_measure": 2,
                                      "unit": "days", "percentile": 95,
                                      "taken_from": "DoH referral-to-treatment standard"}]}) == []


# ---------------------------------------------------------------- step 9 and 11

def test_the_ontology_check_must_report_conflicts_even_when_empty():
    """The half a coverage list cannot show, and the half that makes an agent confidently answer
    the wrong question."""
    assert gated("9", {"concepts": [{"object": "referral", "status": "defined"}]})


def test_a_retrieval_contract_without_a_citation_policy_is_rejected():
    """FR-16. Grounding that cannot be cited cannot be audited."""
    bad = gated("11", {"sources": [{"source": "PAS", "sensitivity": "confidential",
                                    "freshness": "dynamic", "citation_policy": ""}]})
    assert any("citation" in p for p in bad)


# ---------------------------------------------------------------- step 10: the graph

def test_an_edge_naming_a_node_that_does_not_exist_is_rejected():
    bad = gated("10", {"nodes": [{"id": "n1", "activity": "assess", "performed_by": "nurse"}],
                       "edges": [{"from": "n1", "to": "n9", "data_class": "referral"}]})
    assert any("n9" in p for p in bad)


def test_an_edge_carrying_no_data_class_is_rejected():
    """The exposure and influence derivations walk these edges — an edge nobody typed is a control
    nobody derived."""
    bad = gated("10", {"nodes": [{"id": "n1", "activity": "assess", "performed_by": "nurse"},
                                 {"id": "n2", "activity": "notify", "performed_by": "system"}],
                       "edges": [{"from": "n1", "to": "n2", "data_class": ""}]})
    assert bad


# ---------------------------------------------------------------- the retry

def test_a_rejected_answer_gets_exactly_one_corrective_attempt():
    good = '{"problem": "Referrals wait eleven days before a clinician reads them", ' \
           '"for_whom": "GPs", "expected_change": "median falls below two days", ' \
           '"accountable_owner": "Dr Aisha Khan"}'
    agent = FakeAgent('{"problem": "we need a chatbot", "for_whom": "x", '
                      '"expected_change": "y", "accountable_owner": "Dr Khan"}', good)
    step = step_for("3")
    out = asyncio.run(run_gated(agent, "ask", step=step.number, validator=step.validator(),
                                complete=step.complete))
    assert out["accountable_owner"] == "Dr Aisha Khan"
    assert len(agent.asked) == 2


def test_the_retry_re_sends_the_whole_question_because_the_client_is_stateless():
    """A follow-up carrying only the complaint would arrive with nothing to correct."""
    agent = FakeAgent("{}", "{}")
    step = step_for("3")
    with pytest.raises(GateFailed):
        asyncio.run(run_gated(agent, "THE ORIGINAL QUESTION", step=step.number,
                              validator=step.validator(), complete=step.complete))
    assert agent.asked[1].startswith("THE ORIGINAL QUESTION")
    assert "rejected" in agent.asked[1]


def test_a_second_failure_stops_the_run_naming_the_problems():
    """Negotiating with a model that has already been told what is wrong produces plausible output
    rather than correct output, which is worse."""
    agent = FakeAgent("{}", "{}")
    step = step_for("4")
    with pytest.raises(GateFailed) as e:
        asyncio.run(run_gated(agent, "ask", step=step.number, validator=step.validator(),
                              complete=step.complete))
    assert e.value.step == "4" and e.value.problems


def test_a_fenced_reply_is_still_read():
    assert json_of('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_of("not json at all") == {}


# ---------------------------------------------------------------- CR-19, the anchoring control

def test_the_confirmation_step_never_sees_the_provisional_band():
    """CR-19. Step 7 produces a band for the feasibility verdict; step 12 derives the confirmed
    class INDEPENDENTLY. If the confirmation could see the guess it would tend to agree with it —
    and the failure is invisible, because the class simply comes back the same."""
    available = {"criticality_band": {"band": "routine"}, "frame": {"problem": "x"},
                 "elements": {"active": []}}
    assert "criticality_band" not in A.context_for("confirm_criticality", available)


def test_the_exclusion_survives_a_widening_of_what_the_step_may_read(monkeypatch):
    """Applied AFTER selection, so adding the band to a context list cannot silently reintroduce
    the anchor."""
    monkeypatch.setitem(A.CONTEXT_FOR, "confirm_criticality",
                        ("frame", "criticality_band", "elements"))
    available = {"criticality_band": {"band": "routine"}, "frame": {"p": 1}, "elements": {"a": 1}}
    got = A.context_for("confirm_criticality", available)
    assert set(got) == {"frame", "elements"}


def test_a_step_reads_only_what_its_exercise_needs():
    """A context carrying everything would make every prompt a search problem and every wrong
    answer unattributable."""
    available = {k: {"x": 1} for k in ("submission", "frame", "elements", "coverage_map",
                                       "ontology_delta", "capabilities", "landscape")}
    assert set(A.context_for("elements", available)) == {"frame"}
    assert set(A.context_for("coverage_map", available)) == {"elements", "capabilities"}


def test_every_step_declares_the_context_it_reads():
    assert {s.key for s in STEPS} <= set(A.CONTEXT_FOR)


# ---------------------------------------------------------------- the rules not yet exercised

def test_a_coverage_check_that_found_neither_a_match_nor_a_gap_was_not_done():
    """Both lists empty is not "nothing to report" — it is the exercise not having happened."""
    bad = gated("5", {"matched": [], "functions_without_capability": [],
                      "capabilities_without_function": []})
    assert any("not done" in p for p in bad)


def test_a_realisation_check_with_neither_a_match_nor_an_unrealised_element_was_not_done():
    assert any("not done" in p for p in gated("6", {"matched": [], "unrealised": [],
                                                    "existing": False}))


def test_a_survey_match_with_a_gap_flag_raised_is_accepted():
    """The rule is not "never survey" — it is "a survey result is a gap flag candidate". Raising
    the flag is the correct answer, not an admission of failure."""
    assert gated("6", {"matched": [{"element": "triage system", "realised_by": "PAS",
                                    "confidence": "survey"}],
                       "unrealised": [], "existing": False,
                       "gap_flags": [{"what": "PAS ownership unconfirmed",
                                      "owning_body": "Application owners"}]}) == []


def test_an_ontology_check_over_no_objects_was_not_run():
    assert any("not run" in p for p in gated("9", {"concepts": [], "conflicts": []}))


def test_an_ontology_check_reporting_coverage_and_conflicts_passes():
    assert gated("9", {"concepts": [{"object": "referral", "status": "unbound",
                                     "note": "defined but no data binding"}],
                       "conflicts": [{"word": "episode", "meanings": ["a care episode",
                                                                     "a billing period"]}]}) == []


def test_no_contracted_source_and_no_gap_flag_is_rejected():
    """A source with no contract FAILS readiness, so it has to be reported either way — a missing
    source is invisible, and an unreadable one is a finding."""
    assert gated("11", {"sources": []})


def test_a_fully_contracted_source_passes():
    assert gated("11", {"sources": [{"source": "PAS", "sensitivity": "confidential",
                                     "permission_scope": "care team", "propagation": "not onward",
                                     "freshness": "dynamic", "provenance": "system of record",
                                     "citation_policy": "cite the record id and retrieval time"}]}) == []


def test_a_graph_with_no_nodes_is_a_board_escalation_not_an_empty_answer():
    """Q1.1: a workflow that cannot be stated as an explicit graph is D3 at orchestration level."""
    assert any("Board" in p for p in gated("10", {"nodes": [], "edges": []}))


def test_a_well_formed_graph_passes():
    assert gated("10", {"nodes": [{"id": "n1", "activity": "assess", "performed_by": "nurse"},
                                  {"id": "n2", "activity": "notify", "performed_by": "system"}],
                        "edges": [{"from": "n1", "to": "n2", "data_class": "referral"}]}) == []


def test_a_provisional_band_passes():
    assert gated("7", {"band": "business-critical", "provisional": True,
                       "dominant_failure_mode": "a referral is missed and a patient deteriorates"}) == []


def test_an_unknown_step_number_refuses_and_names_the_ones_there_are():
    with pytest.raises(KeyError) as e:
        step_for("99")
    assert "3" in str(e.value)


# ---------------------------------------------------------------- the message an agent receives

def test_the_message_carries_the_context_as_json_not_as_prose():
    """Every value here was produced by an earlier step against a schema. Re-narrating it would
    invite the model to reinterpret what a gate already accepted."""
    body = A.message(step_for("5"), {"elements": {"active": [{"name": "nurse"}]},
                                     "capabilities": {"l3": ["c1"]}})
    assert "```json" in body and '"nurse"' in body
    assert body.startswith("# Step 5 — Business Architect")


def test_a_string_context_is_passed_through_unquoted():
    """The submission is prose; wrapping it in JSON would add escaping a reader has to undo."""
    body = A.message(step_for("3"), {"submission": "Referrals wait eleven days."})
    assert "Referrals wait eleven days." in body
    assert "```json" not in body
