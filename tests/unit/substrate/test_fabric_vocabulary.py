"""The steward's gate: a person's answer about the VOCABULARY, applied as curation.

The sibling of `fabric_curator`, which applies a person's answer about one ARTIFACT. Same stream, same runner,
same registry — a second domain is an applier and a `register` line, not a branch in the runner.
"""
import asyncio

import pytest

from lab.platform.contracts import ApprovalKind, SemanticTools
from lab.substrate import answer_appliers, fabric_vocabulary as V

CANDIDATE = "urn:fabric:candidate:01J9X5K7QZ3M8N2P4R6T8V0W1Y"
PAYLOAD = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "candidate": CANDIDATE, "label": "Model card",
           "scheme": "cafe", "proposed_by": "classifier-agent", "used_by": ["urn:fabric:artifact:A"]}


def one(label, value, field="value"):
    return {label: {field: value}}


def test_the_registry_routes_this_kind_here_and_only_this_kind():
    assert answer_appliers.applier_for(ApprovalKind.CONCEPT_ADMISSION.value) is V.apply
    assert V.applies_to(ApprovalKind.CONCEPT_ADMISSION.value)
    assert not V.applies_to(ApprovalKind.DRAFT_REVIEW.value)


def test_admitting_names_the_person_the_scheme_and_the_id():
    calls = V.plan(PAYLOAD, {**one("decision", "admit"), **one("definition", "What a model is for"),
                             **one("module", "Assurance"), **one("concept_id", "ModelCard")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_propose, SemanticTools.promote]
    parked = dict(calls[0][1])
    assert parked["scheme"] == "cafe" and parked["concept_id"] == "ModelCard"
    assert parked["definition"] == "What a model is for" and parked["actor"] == "steward@doh"
    assert parked["module"] == "Assurance"      # asked for, so it must reach the concept — not be discarded
    assert calls[1][1]["actor"] == "steward@doh" and "predicate" not in calls[1][1]


def test_a_decision_to_decline_admits_nothing_and_says_so():
    assert V.plan(PAYLOAD, one("decision", "decline"), "steward@doh") == []


def test_a_steward_may_answer_that_it_already_exists_which_is_a_link_not_a_concept():
    """The commonest answer to "this term has no concept": it does, under another name. Admitting a second
    would be the duplicate the vocabulary exists to prevent."""
    calls = V.plan(PAYLOAD, {**one("decision", "existing"), **one("concept_id", "AIAgent")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_amend]
    assert calls[0][1] == {"concept_id": "AIAgent", "scheme": "cafe", "alt": "Model card",
                           "actor": "steward@doh", "reason": "a steward said this term means AIAgent"}


def test_settling_a_conflict_retires_the_meaning_the_steward_did_not_keep():
    payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": "cafe", "term": "Agent",
               "concepts": ["AIAgent", "SoftwareAgent"], "conflict": "urn:fabric:conflict:Agent"}
    calls = V.plan(payload, {**one("decision", "settle"), **one("keep", "AIAgent")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_retire]
    assert calls[0][1]["concept_id"] == "SoftwareAgent" and calls[0][1]["resolves_to"] == "AIAgent"
    assert calls[0][1]["actor"] == "steward@doh"


def test_a_kept_meaning_that_is_not_one_of_the_two_is_refused():
    payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": "cafe", "term": "Agent",
               "concepts": ["AIAgent", "SoftwareAgent"]}
    with pytest.raises(ValueError, match="one of"):
        V.plan(payload, {**one("decision", "settle"), **one("keep", "Elsewhere")}, "steward@doh")


def test_the_gate_refuses_an_anonymous_decision_and_an_unanswerable_one():
    with pytest.raises(ValueError, match="actor"):
        V.plan(PAYLOAD, one("decision", "admit"), "")
    with pytest.raises(ValueError, match="decision"):
        V.plan(PAYLOAD, one("definition", "d"), "steward@doh")
    with pytest.raises(ValueError, match="admit|decline|existing|settle"):
        V.plan(PAYLOAD, one("decision", "maybe"), "steward@doh")
    with pytest.raises(ValueError, match="scheme"):
        V.plan({"kind": "concept-admission", "label": "x"}, one("decision", "admit"), "steward@doh")


def test_apply_makes_the_calls_and_answers_with_what_it_did():
    made = []

    async def call(calls):
        made.extend(calls)
        return [{"iri": CANDIDATE} for _ in calls]

    out = asyncio.run(V.apply({"payload": PAYLOAD, "answer": one("decision", "admit")}, "steward@doh", call=call))
    assert [t for t, _ in out] == [SemanticTools.vocab_propose, SemanticTools.promote]
    # the SECOND call promotes the candidate the FIRST one just parked, never the one in the payload: a gate
    # that admitted the original would admit whatever the asker had left lying there
    assert made[1][1]["subject"] == CANDIDATE


def test_the_question_asks_one_thing_per_label_as_every_other_surface_does():
    """`contracts.answer_value` refuses two fields under one label, so a question that bundled definition and
    module would be unanswerable on every surface at once."""
    q = V.question(PAYLOAD)
    assert [i["label"] for i in q] == ["decision", "concept_id", "definition", "module", "broader"]
    assert "admit" in q[0]["samples"][0] and "existing" in q[0]["samples"][0]
    assert all(isinstance(i["samples"], list) and i["samples"] for i in q)     # every label says what to type


def test_the_steward_is_asked_about_open_conflicts_and_parked_candidates_once_each():
    """Nothing else raises this question, so the sweep is what makes the gate reachable — and asking the same
    thing every fifteen minutes would bury the approvals that need somebody, exactly as a channel backlog does."""
    asked, open_ = [], [{"iri": "urn:fabric:conflict:1", "term": "Agent", "scheme": "cafe",
                         "concepts": ["AIAgent", "SoftwareAgent"]}]
    parked = [{"iri": CANDIDATE, "label": "Model card", "scheme": "cafe", "proposed_by": "classifier-agent"}]

    async def call(calls):
        out = []
        for tool, args in calls:
            if tool == SemanticTools.vocab_conflicts:
                out.append(open_)
            elif tool == SemanticTools.vocab_candidates:
                out.append(parked)
            elif tool == "approvals_ask":
                asked.append(args)
                out.append({"request_id": f"apr-{len(asked)}"})
            else:
                out.append({})
        return out

    made = asyncio.run(V.ask_open(call=call, seen=set()))
    assert len(made) == 2 and {a["kind"] for a in asked} == {ApprovalKind.CONCEPT_ADMISSION.value}
    candidate, conflict = asked                                      # what has NO meaning, then what has two
    assert [i["label"] for i in candidate["items"]][:2] == ["decision", "concept_id"]
    assert candidate["payload"]["label"] == "Model card" and "no concept" in candidate["subject"]
    assert [i["label"] for i in conflict["items"]] == ["decision", "keep"]
    assert conflict["payload"]["concepts"] == ["AIAgent", "SoftwareAgent"] and "Agent" in conflict["subject"]
    seen = {"urn:fabric:conflict:1", CANDIDATE}
    assert asyncio.run(V.ask_open(call=call, seen=seen)) == []       # asked once, not every tick


def test_the_eleventh_thing_to_settle_is_not_lost_behind_the_first_ten():
    """Slicing before filtering means that once `limit` rows have been asked about, the next is never reached
    again for the life of the process — and the queue only grows."""
    rows = [{"iri": f"urn:fabric:conflict:{i}", "term": f"t{i}", "scheme": "cafe", "concepts": ["A", "B"]}
            for i in range(12)]

    async def call(calls):
        return [rows if t == SemanticTools.vocab_conflicts else [] if t == SemanticTools.vocab_candidates
                else {"request_id": "apr-1"} for t, _ in calls]

    seen = {r["iri"] for r in rows[:10]}
    assert [r["term"] for r in asyncio.run(V.ask_open(call=call, seen=seen))] == ["t10", "t11"]


def test_every_label_the_steward_is_asked_about_is_read_by_the_plan():
    """A question with an item nothing reads asks a person for something that is thrown away — and one that
    reads a label it never offered can never receive it."""
    answered = {"decision": {"value": "admit"}, "concept_id": {"value": "ModelCard"},
                "definition": {"value": "d"}, "module": {"value": "m"}, "broader": {"value": "AIAgent"}}
    asked = {i["label"] for i in V.question(PAYLOAD)}
    assert asked == set(answered)
    parked = dict(V.plan(PAYLOAD, answered, "steward@doh")[0][1])
    assert {parked[k] for k in ("concept_id", "definition", "module", "broader")} == {"ModelCard", "d", "m", "AIAgent"}
