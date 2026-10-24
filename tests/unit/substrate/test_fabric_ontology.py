"""Steward B's gate: a PERSON's answer about how concepts RELATE, applied as curation.

The sibling of `fabric_vocabulary`, which applies a person's answer about what the vocabulary CONTAINS
— same stream, same runner, same registry, so a second domain is an applier and one `register` line
rather than a branch in the runner.

What it is for. Two concepts co-occur on five documents and the vocabulary says nothing about how they
relate; or a diagram draws an arrow between them. Neither is a question a model may settle: a relation
is what the derived rung reasons over, so "A is about X, X relates to Y, B is about Y" is only
answerable if a person stood behind the middle step.
"""
import pytest

from lab.platform.contracts import ApprovalKind, SemanticTools
from lab.substrate import answer_appliers
from lab.substrate import fabric_ontology as O

Q1 = "urn:fabric:relation-q:one"
Q2 = "urn:fabric:relation-q:two"
PAYLOAD = {"kind": ApprovalKind.CONCEPT_RELATION.value,
           "context": {"questions": [
               {"iri": Q1, "scheme": "cafe", "subject": "Prescription", "predicate": "contains",
                "object": "PrescriptionItem", "evidence": "drawn on the eRx context diagram"},
               {"iri": Q2, "scheme": "cafe", "subject": "Pharmacy", "predicate": "",
                "object": "Dispense", "evidence": "4 documents are about both"}]}}


def test_it_applies_only_the_ONTOLOGY_kind():
    assert O.applies_to(ApprovalKind.CONCEPT_RELATION.value)
    assert not O.applies_to(ApprovalKind.CONCEPT_ADMISSION.value)
    assert answer_appliers.applier_for(ApprovalKind.CONCEPT_RELATION.value) is O.apply


def test_RELATE_states_the_relation_the_question_proposed():
    out = O.plan(PAYLOAD, {Q1: {"value": "relate"}}, "steward@x")
    assert out == [(SemanticTools.vocab_relate,
                    {"scheme": "cafe", "subject": "Prescription", "predicate": "contains",
                     "object": "PrescriptionItem", "actor": "steward@x",
                     "note": "drawn on the eRx context diagram"})]


def test_an_UNNAMED_arrow_must_be_NAMED_by_the_person_answering_it():
    """A diagram says two concepts connect; it does not say how. A typed predicate is exactly what the
    derived rung needs, so the person supplies it — `relate:realisedBy` — and an answer that does not is
    refused rather than inventing one."""
    out = O.plan(PAYLOAD, {Q2: {"value": "relate:fulfils"}}, "steward@x")
    assert out[0][1]["predicate"] == "fulfils" and out[0][1]["subject"] == "Pharmacy"
    # Unreadable: PLANNED as nothing, and REPORTED — `plan` skips so the readable answers on the same
    # card still apply, and `batch_problems` is what re-opens it for this one.
    assert O.plan(PAYLOAD, {Q2: {"value": "relate"}}, "steward@x") == []
    assert any("name the relation" in m
               for m in O.batch_problems(PAYLOAD["context"]["questions"], {Q2: {"value": "relate"}}))


def test_BROADER_places_one_concept_under_the_other_instead():
    """The other half of steward B's job, answerable on the same card: an arrow between two concepts is
    sometimes a hierarchy rather than a relation, and a person reading the diagram is who can tell."""
    out = O.plan(PAYLOAD, {Q1: {"value": "broader"}}, "steward@x")
    assert out == [(SemanticTools.vocab_place,
                    {"concept_id": "PrescriptionItem", "scheme": "cafe", "parent": "Prescription",
                     "actor": "steward@x", "reason": "drawn on the eRx context diagram"})]


def test_DECLINE_records_the_NO_so_both_producers_stop_proposing_it():
    out = O.plan(PAYLOAD, {Q1: {"value": "decline"}}, "steward@x")
    assert out == [(SemanticTools.relation_decline,
                    {"question": Q1, "actor": "steward@x", "reason": ""})]


def test_an_unreadable_verdict_NAMES_the_relation_it_could_not_read():
    """A steward answered ten of these. An error that does not say which one is an error they cannot act
    on — the lesson `_verdict` already records for the term card."""
    assert any("Prescription" in m
               for m in O.batch_problems(PAYLOAD["context"]["questions"], {Q1: {"value": "maybe"}}))


def test_a_blank_actor_is_REFUSED():
    with pytest.raises(ValueError, match="actor is required"):
        O.plan(PAYLOAD, {Q1: {"value": "relate"}}, "")


def test_what_is_READABLE_is_applied_and_the_rest_is_RE_ASKED():
    """One unreadable verdict must not discard nine good ones — the measured lesson from the term card,
    where one empty id box threw away all four of a steward's answers."""
    assert O.batch_problems(PAYLOAD["context"]["questions"],
                            {Q1: {"value": "relate"}, Q2: {"value": "nonsense"}})
    assert not O.batch_problems(PAYLOAD["context"]["questions"], {Q1: {"value": "relate"}})


def test_the_sweep_PROPOSES_from_the_corpus_and_asks_ONE_card_for_all_of_it():
    """Both producers feed one queue. The sweep proposes what the corpus connects, reads whatever is open
    — from either producer — and raises ONE card, because a card per relation is how 101 approvals buried
    ~37 others. The register remembers it asked, so the next tick does not ask again."""
    import asyncio
    asked, marked = [], []
    pairs = [{"scheme": "cafe", "subject": "Prescription", "object": "PrescriptionItem", "records": 4,
              "evidence": "4 records are about both"}]
    open_q = [{"iri": Q1, "scheme": "cafe", "subject": "Prescription", "predicate": "",
               "object": "PrescriptionItem", "evidence": "4 records are about both", "asked": ""}]

    async def call(calls):
        out = []
        for tool, args in calls:
            if tool == SemanticTools.concept_pairs:
                out.append(pairs)
            elif tool == SemanticTools.relation_propose:
                out.append({"iri": Q1})
            elif tool == SemanticTools.relation_open:
                out.append(open_q)
            elif tool == SemanticTools.vocab_asked:
                marked.append(args)
                for row in open_q:
                    if row["iri"] == args.get("candidate"):
                        row["asked"] = args.get("request_id") or "asked"
                out.append({"asked": True})
            elif tool == "approvals_ask":
                asked.append(args)
                out.append({"request_id": f"apr-{len(asked)}"})
            else:
                out.append({})
        return out

    raised = asyncio.run(O.ask_open(call=call))
    assert len(asked) == 1 and asked[0]["kind"] == ApprovalKind.CONCEPT_RELATION.value
    assert [i["label"] for i in asked[0]["items"]] == [Q1]
    assert asked[0]["context"]["questions"][0]["subject"] == "Prescription"
    assert "relate:<predicate>" in asked[0]["items"][0]["choices"], "an unnamed arrow must be NAMED"
    assert marked and raised

    # the REGISTER remembers: a second tick asks nobody
    assert asyncio.run(O.ask_open(call=call)) == []
    assert len(asked) == 1


def test_BROADER_calls_the_tool_by_the_PARAMETER_NAME_IT_HAS():
    """The port is the tool's signature, and fastmcp refuses an unexpected keyword outright — so a wrong
    argument name is not a typo, it is a write path that cannot work. `broader` is offered on every item,
    so this broke on the first steward who used it, and the failure is a ToolError rather than an
    AnswerRejected: the decision is recorded, nothing is applied, and the card closes."""
    import inspect
    from lab.substrate.mcp.semantic import server
    fn = getattr(server.semantic_vocab_place, "fn", server.semantic_vocab_place)
    accepted = set(inspect.signature(fn).parameters)
    args = O.plan(PAYLOAD, {Q1: {"value": "broader"}}, "steward@x")[0][1]
    assert set(args) <= accepted, f"{set(args) - accepted} is not a parameter of semantic_vocab_place"


def test_one_unreadable_verdict_does_not_DISCARD_the_readable_ones():
    """What the module says it does, now true. `plan` let `_verdict`'s ValueError out, so `apply`
    converted it to AnswerRejected BEFORE making any call — the opposite of the claim, and of the sibling
    that gets it right. A steward who answers ten relations and fumbles one must not lose the other nine."""
    import asyncio
    made = []

    async def call(calls):
        made.extend(calls)
        return [{} for _ in calls]

    state = {"payload": PAYLOAD, "answer": {Q1: {"value": "relate"}, Q2: {"value": "yes please"}}}
    with pytest.raises(answer_appliers.AnswerRejected, match="yes please"):
        asyncio.run(O.apply(state, "steward@x", call=call))
    assert [t for t, _ in made] == [SemanticTools.vocab_relate], "the readable half was applied"
    assert made[0][1]["subject"] == "Prescription"


def test_a_RE_ANSWERED_card_does_not_fail_on_what_it_already_did():
    """`apply` must be re-entrant: the runner redrives a failed continuation, and `plan` re-opening the
    card (above) asks the steward again for the part it could not read. `vocab_relate` REFUSES a duplicate,
    so without this a partial write is permanent — the redrive fails identically for ever and the
    steward's other answers never land."""
    import asyncio
    seen = []

    async def call(calls):
        for tool, args in calls:
            seen.append(tool)
            if tool == SemanticTools.vocab_relate and seen.count(tool) > 1:
                raise ValueError("cafe already states 'Prescription' 'contains' 'PrescriptionItem'")
        return [{} for _ in calls]

    state = {"payload": PAYLOAD, "answer": {Q1: {"value": "relate"}}}
    asyncio.run(O.apply(state, "steward@x", call=call))
    asyncio.run(O.apply(state, "steward@x", call=call))      # the redrive must not raise


def test_the_card_tells_the_steward_WHO_proposed_a_relation_and_HOW_MANY_artifacts_did():
    """FR-7: the evidence a steward triages on includes the proposers and the artifact count, so a
    relation two channels and three documents want reads differently from one a diagram drew once."""
    (item,) = O.batch_question([{"iri": "urn:fabric:relation-q:1", "subject": "Prescription",
                                 "predicate": "contains", "object": "PrescriptionItem",
                                 "evidence": "drawn on eRx.vsdx",
                                 "proposed_by": ["maria@contoso.com", "saf-assistant"],
                                 "proposed_for": ["urn:fabric:artifact:a", "urn:fabric:artifact:b"],
                                 "proposals": 2}])
    said = item["samples"][0]
    assert "maria@contoso.com" in said and "saf-assistant" in said and "2 artifacts" in said
    assert item["choices"] == ["relate", "broader", "decline"], "evidence never becomes an answer"


def test_a_relation_with_no_recorded_proposer_reads_as_before():
    (item,) = O.batch_question([{"iri": "q", "subject": "A", "predicate": "", "object": "B",
                                 "evidence": "3 records are about both"}])
    assert "proposed by" not in item["samples"][0]
