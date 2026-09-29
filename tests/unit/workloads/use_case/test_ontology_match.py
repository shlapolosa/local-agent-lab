"""Step 9 in the CAFÉ bundle's vocabulary: every business object MATCHED to an ontology concept by
id — matched, partial, enhancement or gap — with the relationships the use case needs.

Changed 29 Sep 2026 so the step can be drawn (`semantic_view_ontology`): the old answer named each
object with `defined | absent | unbound | conflicting` and no concept id, so nothing could place it
on the ontology. A gap is a PROPOSAL the Ontology Council admits, so it has to be reviewable: it
carries a name, a module, a kind and a definition.
"""
import functools

from lab.workloads.usecase.gates import gate
from lab.workloads.usecase.steps import step_for

ONTOLOGY = {"ontology": {"ontology-concepts": [{"id": "Payer", "name": "Payer"},
                                               {"id": "Coverage", "name": "Coverage"}]}}


def gated(out, context=ONTOLOGY):
    step = step_for("9")
    return gate(out, validator=step.validator(), normalise=step.normalise,
                complete=functools.partial(step.complete, context=context))


GAP = {"object": "Criteria version", "status": "gap", "name": "Criteria version", "module": "CLN",
       "kind": "document", "definition": "Which criteria text was in force for a decision."}


def ok(**over):
    return {"concepts": [{"object": "Payer", "id": "Payer", "status": "matched"}, GAP],
            "relationships": [{"subject": "Criteria version", "predicate": "governs",
                               "object": "Coverage", "status": "gap"}],
            "conflicts": [], **over}


def test_a_complete_match_passes():
    assert gated(ok()) == []


def test_the_old_vocabulary_is_refused():
    bad = ok(concepts=[{"object": "Payer", "id": "Payer", "status": "defined"}])
    assert gated(bad)


def test_a_matched_object_names_a_concept_the_ontology_carries():
    """An id the ontology does not have is not a match — it is an invented concept wearing one."""
    problems = gated(ok(concepts=[{"object": "Payer", "id": "Insurer", "status": "matched"}]))
    assert any("Insurer" in p for p in problems)


def test_a_non_gap_without_an_id_is_refused():
    problems = gated(ok(concepts=[{"object": "Payer", "status": "partial"}]))
    assert any("Payer" in p for p in problems)


def test_a_gap_must_be_reviewable_by_the_council():
    thin = {"object": "Criteria version", "status": "gap"}
    problems = gated(ok(concepts=[thin]))
    assert any("module" in p and "definition" in p for p in problems)


def test_a_relationship_joins_concepts_that_exist_or_are_proposed_here():
    problems = gated(ok(relationships=[{"subject": "Nowhere", "predicate": "x", "object": "Payer",
                                            "status": "gap"}]))
    assert any("Nowhere" in p for p in problems)


def test_relationships_and_conflicts_are_reported_even_when_empty():
    body = ok()
    del body["relationships"]
    assert gated(body)
    body = ok()
    del body["conflicts"]
    assert gated(body)


def test_without_the_ontology_in_context_ids_are_not_second_guessed():
    """The context only CHECKS ids; an absent corpus must not turn every match into a failure."""
    assert gated(ok(concepts=[{"object": "Payer", "id": "Insurer", "status": "matched"}]),
                 context={}) == []
