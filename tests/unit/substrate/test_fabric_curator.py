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
