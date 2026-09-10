"""The capability matchers, and the seam that chooses between them.

Which matcher is better is an EMPIRICAL question — `scripts/eval_coverage.py` answers it and the
module docstring records what it answered. What is tested here is the seam: that both are
reachable, that the choice is made by arithmetic rather than preference, and that neither crashes
on a corpus that is not what it expected.
"""
import pytest

from lab.workloads.usecase import coverage


def concept(ident, label, level, parent=None):
    return {"id": ident, "label": label, "level": level,
            **({"parent": parent} if parent else {})}


TREE = [concept("a", "Work Management", 1),
        concept("b", "Work Queue Management", 2, "a"),
        concept("c", "Work Queue Prioritization", 3, "b"),
        concept("d", "Schedule Management", 2, "a")]


# ---------------------------------------------------------------- the registry

def test_both_strategies_are_reachable_by_name():
    assert set(coverage.MATCHERS) == {"drill", "leaves"}


def test_an_unknown_matcher_refuses_rather_than_defaulting():
    """Falling back to a default would run a strategy nobody chose and report it as the one they
    asked for."""
    with pytest.raises(KeyError) as e:
        coverage.resolve("semantic", TREE, budget=10_000)
    assert "not a capability matcher" in str(e.value)


# ---------------------------------------------------------------- the leaf projection

def test_a_leaf_carries_the_path_that_disambiguates_it():
    """A leaf label is frequently meaningless alone — a match made on the label is a match made on
    a coincidence of words."""
    leaves = coverage.leaves_for(TREE)
    assert [l["label"] for l in leaves] == ["Work Queue Prioritization"]
    assert leaves[0]["path"] == "Work Management > Work Queue Management > Work Queue Prioritization"


def test_a_corpus_that_is_not_a_concept_list_yields_no_leaves():
    """A deployment missing the scheme, or a different corpus wired by mistake, must degrade to
    "no candidates" and let the step defer — which is what every other absent corpus does."""
    assert coverage.leaves_for(["healthcare-provider-v2.0", 42, None]) == []
    assert coverage.leaves_for([]) == []


# ---------------------------------------------------------------- the choice

def test_the_fallback_is_arithmetic_not_preference():
    """`leaves` is the better matcher on the evidence, and it is chosen unless its candidate set
    will not fit in a prompt. That is a measurement of THIS corpus, not a judgement about
    strategies."""
    assert coverage.resolve("leaves", TREE, budget=100_000) is coverage.leaves
    assert coverage.resolve("leaves", TREE, budget=10) is coverage.drill


def test_asking_for_the_drill_gets_the_drill_whatever_the_budget():
    """The fallback runs one way. A deployment that chose the drill chose it."""
    assert coverage.resolve("drill", TREE, budget=100_000) is coverage.drill
    assert coverage.resolve("drill", TREE, budget=10) is coverage.drill


def test_the_configured_default_is_the_one_the_evidence_favoured():
    from lab.platform import config
    assert config.COVERAGE_MATCHER in coverage.MATCHERS


# ---------------------------------------------------------------- composing a drill's levels

def test_a_drill_composes_to_one_row_per_function():
    trail = [{"level": 1, "candidates": 42, "matched": [
                  {"function": "triage", "capability_id": "a", "capability_label": "Work Management",
                   "confidence": "assumption"}]},
             {"level": 3, "candidates": 4, "matched": [
                  {"function": "triage", "capability_id": "c",
                   "capability_label": "Work Queue Prioritization", "confidence": "lookup"}]}]
    matched = coverage.composed(trail)["matched"]
    assert len(matched) == 1
    assert matched[0]["capability_label"] == "Work Queue Prioritization"
    assert matched[0]["path"] == ["Work Management", "Work Queue Prioritization"]
