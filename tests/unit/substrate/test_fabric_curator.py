"""The curator: what a person confirmed is PROMOTED, what they corrected is ASSERTED at H, `none` marks the
record unassociated — and nothing happens without an actor or a record."""
import asyncio

import pytest

from lab.platform.contracts import SemanticTools
from lab.substrate import fabric_curator as C

IRI = "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"
ROW = {"iri": IRI, "links": [{"predicate": "documentType", "rung": "S", "object": "urn:fabric:scheme:doc-types#minutes"},
                             {"predicate": "deliveredUnder", "rung": "S", "object": "urn:fabric:context:usecase:UC-42"}]}
PAYLOAD = {"question": {"items": [{"label": "document_type"}, {"label": "context"}], "fields": ["value"]},
           "continuation": {"process": "artifact_publish", "inputs": {"artifact_iri": IRI}}}


def test_applies_to_the_fabrics_kinds_only():
    assert C.applies_to("association") and C.applies_to("draft-review")
    assert not C.applies_to("speaker-mapping") and not C.applies_to("ea-import") and not C.applies_to("")
    assert C.artifact_of(PAYLOAD) == IRI and C.artifact_of({}) == ""


def test_a_confirmed_answer_is_promoted_and_a_corrected_one_asserted_at_h():
    calls = C.plan(ROW, {"document_type": {"value": "urn:fabric:scheme:doc-types#minutes"},
                         "context": {"value": "usecase:UC-42"}}, "maria@x")
    assert [c[0] for c in calls] == [SemanticTools.promote, SemanticTools.promote, SemanticTools.catalog_state]
    assert calls[0][1] == {"subject": IRI, "predicate": "urn:fabric:ont#documentType",
                           "object": "urn:fabric:scheme:doc-types#minutes", "actor": "maria@x", "method": "review"}
    assert calls[1][1]["object"] == "urn:fabric:context:usecase:UC-42" and calls[2][1]["unassociated"] is False
    corrected = C.plan(ROW, {"document_type": {"value": "urn:fabric:scheme:doc-types#decision-record"},
                             "context": {"value": "meeting:AAMk1"}}, "maria@x")
    assert corrected[0][0] == SemanticTools.catalog_assert and corrected[0][1]["rung"] == "H"
    assert corrected[1][0] == SemanticTools.edge_assert and corrected[1][1]["supersede"] is True
    assert corrected[1][1]["object"] == "urn:fabric:context:meeting:AAMk1"


def test_none_marks_the_record_unassociated_and_an_actor_is_required():
    calls = C.plan(ROW, {"context": {"value": "none"}}, "maria@x")
    assert calls == [(SemanticTools.catalog_state, {"iri": IRI, "state": "pending", "unassociated": True})]
    assert C.plan(ROW, {}, "maria@x") == []
    with pytest.raises(ValueError, match="actor"):
        C.plan(ROW, {"context": {"value": "none"}}, "")


def test_apply_reads_the_record_then_writes_the_plan_through_the_injected_transport():
    made = []

    async def call(calls):
        made.append(calls)
        return [ROW] if calls[0][0] == SemanticTools.catalog_get else [{} for _ in calls]
    state = {"payload": PAYLOAD, "answer": {"document_type": {"value": "urn:fabric:scheme:doc-types#minutes"}}}
    applied = asyncio.run(C.apply(state, "maria@x", call=call))
    assert made[0] == [(SemanticTools.catalog_get, {"iri": IRI})] and made[1] == applied and len(applied) == 1


def test_apply_refuses_without_a_record_or_an_artifact():
    async def none(calls):
        return [None]
    with pytest.raises(LookupError):
        asyncio.run(C.apply({"payload": PAYLOAD, "answer": {}}, "m", call=none))
    with pytest.raises(ValueError, match="names no artifact"):
        asyncio.run(C.apply({"payload": {}, "answer": {}}, "m", call=none))


def test_the_fabric_kinds_are_registered_as_appliers_and_nothing_else_is():
    from lab.substrate import answer_appliers
    assert answer_appliers.applier_for("draft-review") is C.apply and answer_appliers.applier_for("association") is C.apply
    assert answer_appliers.applier_for("speaker-mapping") is None
    with pytest.raises(ValueError):
        answer_appliers.register(("draft-review",), lambda s, a: None)


def test_an_owner_answer_is_asserted_at_C_because_owner_is_a_FACT_whoever_supplied_it():
    """This test asserted rung H and the system refused it in production — measured 8 Oct 2026, on the first
    approval anyone ever gave:

        continuation for apr-88662ef369cb failed — ToolError: semantic_catalog_assert:
        refused by the fabric's shapes: owner and sensitivity label must be constructed (rung C)
        from reference data (NFR-3)

    `fab:OwnerProvenanceShape` requires the `fab:ownedBy` triple to live in graph C, full stop. So the
    fabric ASKED a question whose answer it would not accept: intake adds an `owner` item whenever the
    owner-map resolves nothing (`artifact_intake/workflow.py:349-350`, "type the owner's email"), and this
    plan then wrote it at H. Nobody had answered one before, so nothing failed until a person did.

    The rung is a statement about the KIND of knowledge, not about who typed it. FRS FR-1.1 is explicit —
    "identity, owner and sensitivity enter at C only" — because owner is a FACT looked up or supplied, not
    a judgement inferred from evidence. A person typing it is the most reliable source there is, and the
    actor and method still record that a human supplied it; only the rung changes.
    """
    calls = C.plan(ROW, {"owner": {"value": "maria@x"}}, "steward@x")
    assert calls == [(SemanticTools.catalog_assert, {"iri": IRI, "field": "owner", "value": "urn:fabric:person:maria@x",
                                                     "rung": "C", "method": C.OWNER_METHOD, "actor": "steward@x"})]
    assert C.plan(ROW, {"owner": {"value": "urn:fabric:person:maria@x"}}, "steward@x")[0][1]["value"] == "urn:fabric:person:maria@x"
    # the method must still say a HUMAN supplied it — C is not a claim that a reference store was consulted
    assert "review" in C.OWNER_METHOD or "human" in C.OWNER_METHOD or "supplied" in C.OWNER_METHOD


def test_an_overlap_answer_keeps_or_withdraws_as_a_duplicate_of_the_named_record():
    from lab.core.semantic.fabric.ontology import DUPLICATE_OF
    assert C.plan(ROW, {"overlap": {"value": "keep"}}, "steward@x") == []
    calls = C.plan(ROW, {"overlap": {"value": "duplicate-of:urn:fabric:artifact:PUB"}}, "steward@x")
    assert calls == [(SemanticTools.edge_assert, {"subject": IRI, "predicate": DUPLICATE_OF, "object": "urn:fabric:artifact:PUB",
                                                  "rung": "H", "method": C.METHOD, "actor": "steward@x"}),
                     (SemanticTools.catalog_state, {"iri": IRI, "state": "withdrawn"})]
    with pytest.raises(ValueError, match="keep"):
        C.plan(ROW, {"overlap": {"value": "maybe"}}, "steward@x")


def test_a_document_type_may_be_answered_by_its_label_and_an_unknown_one_is_refused_with_the_choices():
    """WP20: a person in chat says "decision record", not an IRI. Labels and alt labels resolve, case-insensitively;
    anything else is refused naming the labels, so the person answers again."""
    def typed(answer):                       # a correction is ASSERTED (value); a confirmation PROMOTED (object)
        args = C.plan(ROW, {"document_type": {"value": answer}}, "maria@x")[0][1]
        return args.get("value") or args.get("object")
    assert typed("Decision record") == "urn:fabric:scheme:doc-types#decision-record"
    assert typed("adr").endswith("#decision-record") and typed("meeting minutes").endswith("#minutes")
    with pytest.raises(ValueError, match="Decision record"):
        C.plan(ROW, {"document_type": {"value": "shopping list"}}, "maria@x")


SUBJECT_P = "http://purl.org/dc/terms/subject"


def test_a_KEPT_subject_is_PROMOTED_so_a_later_re_read_cannot_take_it_away():
    """What confirming a subject is FOR. `vocab_link` replaces the extracted set wholesale on every
    re-read, and spares only what is held above X (`held_elsewhere`) — so a subject the owner confirmed
    survives the next sweep precisely because it was promoted to H, and one left at X does not.

    Promote rather than assert: the X copy stays, which is what keeps the audit chain honest about how the
    fabric first came to believe it."""
    row = {**ROW, "links": [{"predicate": "subject", "rung": "X", "object": "urn:c#Prescription"}]}
    out = C.plan(row, {"subject:urn:c#Prescription": {"value": "keep"}}, "steward@x")
    assert out == [(SemanticTools.promote, {"subject": IRI, "predicate": SUBJECT_P,
                                            "object": "urn:c#Prescription", "actor": "steward@x",
                                            "method": C.METHOD})]


def test_a_DROPPED_subject_is_recorded_as_a_NO_not_merely_retracted():
    """The owner is the one person who knows the document is not about this — and their answer has to LAST.

    A bare `edge_retract` left no trace, so the next classification matched the same label, asserted the
    subject again at X, and asked them the same question: `keep` survived for ever and `drop` survived
    until the next sweep. `not_about` retracts AND records the NO, which is what `vocab_decline` already
    does one level up for a term."""
    row = {**ROW, "links": [{"predicate": "subject", "rung": "X", "object": "urn:c#Pharmacy"}]}
    out = C.plan(row, {"subject:urn:c#Pharmacy": {"value": "drop"}}, "steward@x")
    assert out == [(SemanticTools.not_about, {"iri": IRI, "concept": "urn:c#Pharmacy", "actor": "steward@x",
                                              "reason": "the owner said this document is not about it"})]


def test_an_unreadable_subject_answer_is_REFUSED_by_name():
    """`apply` turns this into AnswerRejected and the runner re-opens the card, so a person who typed
    something unexpected is asked again rather than having it silently discarded."""
    with pytest.raises(ValueError, match="keep"):
        C.plan(ROW, {"subject:urn:c#X": {"value": "maybe"}}, "steward@x")


def test_a_subject_already_CONFIRMED_is_not_promoted_twice():
    """Idempotent, like the type branch: a card answered twice must not append a second assertion."""
    row = {**ROW, "links": [{"predicate": "subject", "rung": "H", "object": "urn:c#Prescription"}]}
    assert C.plan(row, {"subject:urn:c#Prescription": {"value": "keep"}}, "steward@x") == []


def test_the_AUTHOR_confirms_renames_or_removes_each_extracted_term():
    """FR-10: the owner's card carries one `term:<candidate>` item per term read out of the document; each
    answer becomes the author's decision on that candidate, in the author's name."""
    calls = C.plan(ROW, {"term:urn:fabric:candidate:1": {"value": "confirm"},
                         "term:urn:fabric:candidate:2": {"value": "rename: Dispense audit"},
                         "term:urn:fabric:candidate:3": {"value": "remove"}}, "author@x")
    got = [(t, a) for t, a in calls if t == SemanticTools.author_confirm]
    assert [(a["candidate"], a["decision"], a.get("label", "")) for _, a in got] == [
        ("urn:fabric:candidate:1", "confirm", ""), ("urn:fabric:candidate:2", "rename", "Dispense audit"),
        ("urn:fabric:candidate:3", "remove", "")]
    assert all(a["actor"] == "author@x" for _, a in got)


def test_a_term_answer_that_is_none_of_the_three_is_refused_naming_the_term():
    with pytest.raises(ValueError, match="confirm, rename:<word> or remove"):
        C.plan(ROW, {"term:urn:fabric:candidate:1": {"value": "maybe"}}, "author@x")
