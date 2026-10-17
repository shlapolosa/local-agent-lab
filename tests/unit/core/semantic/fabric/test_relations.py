"""Relation candidates from a structured diagram — the only feeder steward B has.

A diagram's boxes are terms and its arrows are relations, which makes it the one artifact that carries the
vocabulary's TOPOLOGY rather than just its membership. Pure: the resolver is handed in, so these assert the
decisions without a scheme, a parser or a store.
"""
from lab.core.semantic.fabric import relations as R

SCHEME = {"ai agent": "AIAgent", "use case": "UseCase", "model card": "ModelCard"}


def resolve(term):
    return SCHEME.get(R.normalise(term), "")


def conn(src, tgt, label="", **kw):
    return {"from": src, "to": tgt, "label": label, **kw}


def test_an_arrow_between_two_known_concepts_is_a_relation_candidate():
    out = R.candidates([conn("AI Agent", "Use case", "realises")], resolve=resolve, states=lambda *a: False)[0]
    assert out == [{"subject": "AIAgent", "predicate": "realises", "object": "UseCase",
                    "subject_term": "AI Agent", "object_term": "Use case", "arrows": 1, "unnamed": False}]


def test_an_arrow_whose_END_is_not_in_the_vocabulary_is_a_GAP_a_steward_can_see():
    """Not silently dropped. A diagram naming a box the vocabulary has no concept for is the same finding the
    classifier's candidates are: the gap is the useful part, and a steward closes it by admitting the term."""
    out, gaps = R.candidates([conn("AI Agent", "Billing engine", "feeds")], resolve=resolve,
                             states=lambda *a: False)
    assert out == [] and gaps == ["Billing engine"]


def test_an_UNLABELLED_arrow_is_a_candidate_a_person_must_NAME():
    """The diagram says these two connect; it does not say how. A typed predicate is what the derived rung
    needs, so the candidate carries none and is marked as needing one — guessing it would put an edge in the
    vocabulary that no author wrote."""
    out = R.candidates([conn("AI Agent", "Use case")], resolve=resolve, states=lambda *a: False)[0]
    assert out[0]["predicate"] == "" and out[0]["unnamed"] is True


def test_the_SAME_relation_drawn_on_several_pages_is_one_candidate_that_counts_them():
    arrows = [conn("AI Agent", "Use case", "realises"), conn("ai agent", "USE CASE", "Realises"),
              conn("AI Agent", "Use case", "documents")]
    out = R.candidates(arrows, resolve=resolve, states=lambda *a: False)[0]
    assert [(c["predicate"], c["arrows"]) for c in out] == [("documents", 1), ("realises", 2)]


def test_a_relation_the_vocabulary_ALREADY_STATES_is_not_proposed_again():
    held = {("AIAgent", "realises", "UseCase")}
    out = R.candidates([conn("AI Agent", "Use case", "realises"), conn("AI Agent", "Model card", "documents")],
                       resolve=resolve, states=lambda s, p, o: (s, p, o) in held)[0]
    assert [c["object"] for c in out] == ["ModelCard"]


def test_an_arrow_onto_the_same_concept_is_not_a_relation():
    """Two boxes the vocabulary resolves to ONE concept — an alt label and its preferred label on the same
    page. The arrow is real and the relation is not: a concept related to itself says nothing."""
    out = R.candidates([conn("AI Agent", "ai agent", "feeds"), conn("AI Agent", "AI Agent")],
                       resolve=resolve, states=lambda *a: False)[0]
    assert out == []


def test_an_arrow_missing_an_end_entirely_is_ignored():
    for bad in (conn("", "Use case", "x"), conn("AI Agent", "", "x"), {"label": "x"}):
        assert R.candidates([bad], resolve=resolve, states=lambda *a: False)[0] == []


def test_candidates_are_ordered_so_the_same_diagram_gives_the_same_list_twice():
    arrows = [conn("Use case", "AI Agent", "needs"), conn("AI Agent", "Use case", "realises"),
              conn("AI Agent", "Model card", "documents")]
    once = R.candidates(arrows, resolve=resolve, states=lambda *a: False)[0]
    assert once == R.candidates(list(reversed(arrows)), resolve=resolve, states=lambda *a: False)[0]
    assert [c["subject"] for c in once] == ["AIAgent", "AIAgent", "UseCase"]


def test_too_many_arrows_in_one_call_is_REFUSED_not_quietly_halved():
    """They arrive inline, and a silently truncated diagram proposes a topology nobody drew. The bound is
    generous against a real diagram — the largest measured in this lab recovered 44 connectors."""
    import pytest
    many = [conn(f"AI Agent", f"Use case", f"r{n}") for n in range(R.MAX_ARROWS + 1)]
    with pytest.raises(ValueError, match="above the"):
        R.candidates(many, resolve=resolve, states=lambda *a: False)
    assert R.candidates(many[:R.MAX_ARROWS], resolve=resolve, states=lambda *a: False)[0]
