"""The guardrail trigger-predicate evaluator.

NFR-15 says gate definitions, derivation rules and guardrail predicates are read as CONFIGURATION
by a service, never compiled into the orchestrator. So the 24 live predicates cannot become 24
Python functions — they are parsed from the published artifact and evaluated against a step's facet
vector. This is what step 19 (evaluate obligations) does for every step in a workflow.

The failure mode that matters is a guardrail that quietly fails to fire, so the tests below care
much more about refusing loudly than about returning False.
"""
import pytest

from lab.core.usecase import seed
from lab.core.usecase import predicates
from lab.core.usecase.predicates import (
    Predicate,
    PredicateError,
    PredicateSyntaxError,
    UnknownCondition,
    UnknownField,
    parse,
)

COMMIT_STEP = {
    "activity": "commit",
    "determinism": "D1",
    "effect": "record write",
    "reversibility": "reversible",
    "blast_radius": "single record",
    "audience": "internal group",
    "authorisation": "policy-bounded",
    "domain": "general",
    "input.sensitivity": "internal",
    "input.freshness": "static",
    "exposure": 1,
    "influence": 1,
    "criticality": "routine",
}


def step(**overrides):
    return COMMIT_STEP | overrides


# ---------------------------------------------------------------- the grammar

def test_always_is_true_whatever_the_step_says():
    assert parse("always — every step executed by an agent").evaluate(step()) is True


@pytest.mark.parametrize("text,facts,expected", [
    ("step.activity ∈ {commit, orchestrate}", {}, True),
    ("step.activity ∈ {commit, orchestrate}", {"activity": "retrieve"}, False),
    ("step.activity = retrieve", {"activity": "retrieve"}, True),
    ("step.authorisation ≠ per-action human", {}, True),
    ("step.authorisation ≠ per-action human", {"authorisation": "per-action human"}, False),
    ("criticality ∈ {business-critical, safety-of-life}", {"criticality": "safety-of-life"}, True),
])
def test_comparisons(text, facts, expected):
    assert parse(text).evaluate(step(**facts)) is expected


@pytest.mark.parametrize("determinism,expected", [("D0", False), ("D1", False),
                                                  ("D2", True), ("D3", True)])
def test_a_tier_comparison_is_ordinal_not_alphabetical(determinism, expected):
    assert parse("step.determinism ≥ D2").evaluate(step(determinism=determinism)) is expected


@pytest.mark.parametrize("influence,expected", [(0, False), (1, False), (2, True), (3, True)])
def test_a_numeric_class_compares_numerically(influence, expected):
    assert parse("influence ≥ 2").evaluate(step(influence=influence)) is expected


def test_conjunction_needs_both_and_disjunction_needs_either():
    both = parse("step.determinism = D1 ∧ step.effect = record write")
    assert both.evaluate(step()) is True
    assert both.evaluate(step(effect="none")) is False

    either = parse("step.determinism = D3 ∨ step.effect = record write")
    assert either.evaluate(step()) is True
    assert either.evaluate(step(effect="none")) is False


def test_conjunction_binds_tighter_than_disjunction():
    # a ∨ (b ∧ c) — with the wrong precedence this reads (a ∨ b) ∧ c and flips.
    text = "step.activity = retrieve ∨ step.activity = commit ∧ step.effect = none"
    assert parse(text).evaluate(step(activity="retrieve", effect="record write")) is True


def test_an_existential_quantifier_reads_the_whole_workflow_not_this_step():
    g19 = parse("∃ step in workflow with influence ≥ 3")
    quiet = [step(influence=0), step(influence=1)]
    loud = [step(influence=0), step(influence=3)]
    assert g19.evaluate(step(influence=0), workflow=quiet) is False
    assert g19.evaluate(step(influence=0), workflow=loud) is True


# ------------------------------------------------- values as the schema spells them

@pytest.mark.parametrize("value", ["cohort", "a cohort"])
def test_an_article_in_a_facet_value_does_not_stop_it_matching(value):
    """The facet schema says "a cohort · the whole population"; the predicates say
    "{cohort, population}". Both spellings are the same value."""
    assert parse("step.blast_radius ∈ {cohort, population}").evaluate(
        step(blast_radius=value)) is True


def test_the_whole_population_matches_population():
    assert parse("step.blast_radius ∈ {cohort, population}").evaluate(
        step(blast_radius="the whole population")) is True


# ---------------------------------------------------------------- named conditions

def test_a_named_condition_is_answered_by_the_caller():
    text = "step.activity ∈ {commit, orchestrate} ∨ step invokes any registered tool"
    p = parse(text)
    assert p.evaluate(step(activity="retrieve"),
                      conditions={"step invokes any registered tool": True}) is True
    assert p.evaluate(step(activity="retrieve"),
                      conditions={"step invokes any registered tool": False}) is False


def test_an_unanswered_named_condition_refuses_rather_than_reading_false():
    """The whole point. A guardrail that silently fails to fire is the failure mode that matters,
    so an unsupplied condition is an error, never a quiet False."""
    p = parse("step.activity = retrieve ∨ step invokes any registered tool")
    with pytest.raises(UnknownCondition) as e:
        p.evaluate(step(activity="commit"))
    assert "invokes any registered tool" in str(e.value)


def test_a_predicate_declares_the_conditions_it_needs_so_a_caller_can_supply_them():
    p = parse("step.activity = orchestrate ∧ the step delegates to another agent")
    assert p.conditions() == frozenset({"the step delegates to another agent"})
    assert parse("step.determinism ≥ D2").conditions() == frozenset()


def test_short_circuit_does_not_excuse_an_unknown_condition_that_could_decide_it():
    """`False ∧ <unknown>` is safely False — the unknown cannot change it. `True ∧ <unknown>`
    cannot be answered and must refuse."""
    p = parse("step.activity = retrieve ∧ some unknown thing")
    assert p.evaluate(step(activity="commit")) is False
    with pytest.raises(UnknownCondition):
        p.evaluate(step(activity="retrieve"))


# ---------------------------------------------------------------- refusing badly-formed input

def test_an_unknown_field_refuses_and_names_what_it_knows():
    with pytest.raises(UnknownField) as e:
        parse("step.wingspan ≥ 2").evaluate(step())
    assert "wingspan" in str(e.value)


@pytest.mark.parametrize("text", ["", "   ", "step.activity ∈ {", "∧ step.activity = commit"])
def test_a_malformed_predicate_refuses_at_parse_time(text):
    with pytest.raises(PredicateSyntaxError):
        parse(text)


# ---------------------------------------------------------------- against the real artifact

def test_every_published_live_predicate_parses():
    """The corpus is data, so the evaluator has to cope with all of it, not a sample."""
    unparsed = []
    for g in seed.live_guardrails():
        try:
            parse(g["pred"])
        except PredicateSyntaxError as exc:
            unparsed.append(f'{g["id"]}: {g["pred"]} -> {exc}')
    assert not unparsed, "\n".join(unparsed)


def test_the_published_set_is_the_twenty_four_the_spec_counts():
    live = seed.live_guardrails()
    assert len(live) == 24, [g["id"] for g in live]
    assert "G09" in {g["id"] for g in live}      # the one the spec's Annexure C omits


def test_every_named_condition_the_corpus_uses_is_declared():
    """A named condition nobody can answer is a guardrail that can never fire. Whatever the
    registry ends up containing, it must cover the whole published corpus."""
    needed = {c for g in seed.live_guardrails() for c in parse(g["pred"]).conditions()}
    assert needed <= predicates.NAMED_CONDITIONS, sorted(needed - predicates.NAMED_CONDITIONS)


def test_ordering_a_value_that_has_no_order_refuses_instead_of_comparing_strings():
    """`step.effect ≥ record write` is meaningless. Falling back to string comparison would answer
    it anyway, and the answer would be arbitrary."""
    with pytest.raises(PredicateError) as e:
        parse("step.effect ≥ record write").evaluate(step())
    assert "no order" in str(e.value)


def test_a_step_missing_the_facet_a_predicate_reads_refuses():
    """An absent facet is not a False. It means the vector was never assigned, which is a step-17
    defect, and reading it as "does not trigger" hides that."""
    facts = {k: v for k, v in COMMIT_STEP.items() if k != "domain"}
    with pytest.raises(UnknownField) as e:
        parse("step.domain ∈ {clinical, financial, HR}").evaluate(facts)
    assert "domain" in str(e.value)


def test_a_missing_seed_artifact_raises_rather_than_reading_as_empty():
    """CR-12: no all-clear inferred from an unavailable artifact. An empty dict would evaluate to
    "no guardrails apply", which is the most dangerous possible wrong answer."""
    with pytest.raises(FileNotFoundError) as e:
        seed.artifact("no-such-artifact")
    assert "no-such-artifact" in str(e.value)


def test_the_retired_guardrails_stay_readable_but_never_enter_a_control_set():
    ids = {g["id"] for g in seed.guardrails()}
    live = {g["id"] for g in seed.live_guardrails()}
    assert {"G11", "G12"} <= ids, "a retired identifier stays citable"
    assert not ({"G11", "G12"} & live), "a retired guardrail must never fire"


def test_a_predicate_is_reusable_across_steps():
    p = parse("step.effect ∈ {external communication} ∧ step.authorisation ≠ per-action human")
    assert isinstance(p, Predicate)
    assert p.evaluate(step(effect="external communication")) is True
    assert p.evaluate(step(effect="external communication",
                           authorisation="per-action human")) is False
