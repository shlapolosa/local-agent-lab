"""The translation stage — HyDE, by its usual name: write the query in the CORPUS's language first.

Offline. The point of these is that the parts which decide accuracy can be changed and checked
without spending a model call or reaching the cloud; the eval harness measures whether the change
was an improvement, and these say whether it is correct.
"""
import pytest

from lab.workloads.usecase import coverage
from lab.workloads.usecase.steps import CAPABILITY_QUERY, schema

CORPUS = [
    {"id": "cap-med", "label": "Medication Management", "level": 1, "parent": None,
     "definition": "Ability to prescribe, dispense, reconcile and monitor medication."},
    {"id": "cap-hist", "label": "Medication History Management", "level": 3, "parent": "cap-med",
     "definition": "Ability to capture and maintain a patient's medication history over time."},
    {"id": "cap-prof", "label": "Medication Profile Management", "level": 3, "parent": "cap-med",
     "definition": "Ability to maintain the active medication profile of a patient."},
    {"id": "cap-info", "label": "Information Aggregation", "level": 3, "parent": "cap-gen",
     "definition": "Ability to combine information from several sources."},
    {"id": "cap-gen", "label": "Information Management", "level": 1, "parent": None,
     "definition": "Ability to capture, hold and publish information."},
]
ELEMENTS = {"behavioural": [{"name": "reconcile the medication list", "verb": "reconcile",
                             "object": "medication list"},
                            {"name": "record the outcome", "verb": "record", "object": "outcome"}]}


def gated(out, context=None):
    return CAPABILITY_QUERY.complete(out, context=context)


def test_the_register_sample_teaches_the_language_without_offering_the_map():
    sample = coverage.register_of(CORPUS, n=3)
    assert 0 < len(sample) <= 3
    assert set(sample[0]) == {"label", "definition"}, "no ids — there is nothing here to choose from"
    assert len(sample) < len(CORPUS), "a sample, not the map"


def test_a_translation_is_demanded_for_every_function_and_invents_none():
    out = {"queries": [{"function": "reconcile the medication list",
                        "ability": "Medication History Management",
                        "about": "maintaining a patient's medication record over time"}]}
    problems = " ".join(gated(out, {"elements": ELEMENTS}))
    assert "record the outcome" in problems, "a function nobody translated is never searched for"
    out["queries"].append({"function": "invent a thing", "ability": "X Management", "about": "y"})
    assert any("are not functions from the inventory" in p for p in gated(out, {"elements": ELEMENTS}))


def test_an_ability_that_repeats_the_function_has_translated_nothing():
    out = {"queries": [{"function": "reconcile the medication list",
                        "ability": "reconcile the medication list",
                        "about": "reconciling the list"},
                       {"function": "record the outcome", "ability": "Outcome Recording",
                        "about": "writing the result of a decision"}]}
    assert any("repeats the function verbatim" in p for p in gated(out, {"elements": ELEMENTS}))


def test_a_complete_translation_passes():
    out = {"queries": [{"function": "reconcile the medication list",
                        "ability": "Medication History Management",
                        "about": "maintaining a patient's medication record over time"},
                       {"function": "record the outcome", "ability": "Decision Recording",
                        "about": "writing down what was decided and why"}]}
    assert gated(out, {"elements": ELEMENTS}) == []
    assert gated(out) == [], "without the inventory the rule makes no claim"


def test_the_schema_the_model_reads_is_the_one_the_gate_validates():
    props = schema("capability_query")["properties"]["queries"]["items"]
    assert set(props["required"]) == {"function", "ability", "about"}
    assert props["additionalProperties"] is False


def test_an_answer_is_reachable_at_the_level_it_lives_at():
    """A capability map answers at more than one level: the referral case's own expected set is
    level 2 and level 3, so a matcher offering only leaves cannot return a third of the right
    answers however well it searches."""
    hits = [{"id": "cap-hist", "label": "Medication History Management", "parent": "cap-med"}]
    widened = coverage.with_parents(hits, CORPUS)
    assert {c["id"] for c in widened} == {"cap-hist", "cap-med"}
    assert coverage.with_parents([], CORPUS) == []
    # idempotent: a parent already among the candidates is not added twice
    assert len(coverage.with_parents(widened, CORPUS)) == 2


def test_translate_is_a_registered_strategy_like_any_other():
    assert coverage.MATCHERS["translate"] is coverage.translate
    assert set(coverage.MATCHERS) == {"drill", "leaves", "vector", "translate"}


@pytest.mark.parametrize("missing", ["behavioural", "elements"])
def test_without_functions_it_defers_rather_than_searching_for_nothing(missing):
    import asyncio
    from lab.workloads.usecase.derivation import Derivation
    available = {} if missing == "elements" else {"elements": {"behavioural": []}}
    d = Derivation(available=available)
    asyncio.run(coverage.translate({}, d, CORPUS, search=None))
    assert "needs the behavioural elements" in d.pending["5"]


def test_leaves_takes_the_matching_grain_from_the_caller_not_a_constant():
    """A map's matching grain is a property of THAT map, not of the lab.

    The healthcare map is matched at L3 and deliberately ignores its L4; a map only two levels
    deep has nothing at L3, and the constant silently returns zero candidates — an empty match
    that reads exactly like "nothing is relevant". So the level is a parameter, defaulted to the
    published map's grain.
    """
    two_deep = [{"id": "d1", "label": "Business", "level": 1, "parent": None},
                {"id": "c1", "label": "Capability map", "level": 2, "parent": "d1"}]
    assert coverage.leaves_for(two_deep) == []                       # the constant finds nothing
    assert [c["id"] for c in coverage.leaves_for(two_deep, deepest=2)] == ["c1"]


def test_resolve_and_match_carry_the_grain_through_to_the_matcher():
    """The seam that made the grain parameter worthless in production.

    `leaves` took `deepest`, but `resolve` and `match` — the only way a RUN reaches it — did not
    forward it, so the live path always matched at the constant 3. Against the two-level technology
    map that is zero candidates, and zero candidates reads downstream as "nothing is relevant"
    rather than as a bug. The harness never saw it because it calls the matcher directly.
    """
    two_deep = [{"id": "d1", "label": "Knowledge", "level": 1, "parent": None},
                {"id": "Knowledge · Agentic retrieval", "label": "Agentic retrieval",
                 "level": 2, "parent": "d1"}]
    assert coverage.resolve("leaves", two_deep, budget=200_000, deepest=2) is coverage.leaves

    shown: list = []

    class _D:
        available = {"elements": {"behavioural": [{"name": "retrieve"}]}}
        derived: dict = {}
        pending: dict = {}
        candidates: list = []

        async def run_step(self, cfg, step, label="", **kw):
            shown.append(list(self.candidates))
            return False

        def defer(self, *a, **k):
            pass

    import asyncio
    asyncio.run(coverage.match({}, _D(), two_deep, name="leaves", children=None, search=None,
                               project=lambda r: r, budget=200_000, deepest=2))
    assert [c["id"] for c in shown[0]] == ["Knowledge · Agentic retrieval"]
