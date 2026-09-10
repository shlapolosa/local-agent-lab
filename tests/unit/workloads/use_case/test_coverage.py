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

def test_every_strategy_is_reachable_by_name():
    assert {"drill", "leaves", "vector"} <= set(coverage.MATCHERS)


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


# ---------------------------------------------------------------- corpus rows carry their path

def test_a_corpus_row_s_own_path_is_used_when_it_has_one():
    """The workbook publisher writes the path onto every row, so a leaf fetched ALONE (no parents
    in the working set) still carries what disambiguates it."""
    rows = [{"id": "c", "label": "Work Queue Prioritization", "level": 3, "parent": "b",
             "path": "Work Management > Work Queue Management > Work Queue Prioritization"}]
    assert coverage.leaves_for(rows)[0]["path"].startswith("Work Management >")


# ---------------------------------------------------------------- the vector strategy

def test_a_query_is_made_per_behavioural_element_and_never_per_actor_or_datum():
    elements = {"active": [{"name": "Referral coordinator"}],
                "behavioural": [{"name": "Triage referral", "verb": "prioritise", "object": "referral"},
                                {"name": "Book slot"}, {"name": "Triage referral"}],
                "passive": [{"name": "Referral record"}]}
    assert coverage.queries_for(elements) == ["Triage referral — prioritise referral", "Book slot"]
    assert coverage.queries_for(None) == []


def test_hits_become_candidates_by_record_id_de_duplicated_with_label_and_path():
    """A hit over the map is record-backed: its key carries the id, its text is `path. definition`."""
    hit = lambda ident, path: {"content": [{"type": "text", "text": f"{path}. A definition. With dots"}],
                               "attributes": {"key": f'{{"id": "{ident}", "parent": "p", "level": "3"}}'}}
    out = coverage.candidates_from_hits([hit("x", "A > B > C"), hit("y", "A > D"), hit("x", "A > B > C"),
                                         {"content": [], "attributes": {}}])
    assert out == [{"id": "x", "label": "C", "path": "A > B > C"},
                   {"id": "y", "label": "D", "path": "A > D"}]


class _Working:
    """A Derivation stand-in: what the matcher records, defers and reads."""
    def __init__(self, elements=None, answer=None):
        self.available = {"elements": elements} if elements else {}
        self.derived, self.pending, self.contexts = {}, {}, []
        self.answer = answer

    async def run_step(self, cfg, step, *, label="", context=None):
        self.contexts.append(dict(context or {}))
        if self.answer is None:
            return False
        self.derived["coverage_map"] = self.answer
        return True

    def defer(self, number, why): self.pending[number] = why
    def record(self, key, out, number=""): self.derived[key] = out


def _search_of(hits_by_query):
    calls = []
    async def search(query, k):
        calls.append((query, k))
        return hits_by_query.get(query, [])
    search.calls = calls
    return search


def test_the_vector_matcher_unions_the_hits_and_runs_one_pass_over_them():
    import asyncio
    hit = lambda ident, path: {"content": [{"type": "text", "text": f"{path}. def"}],
                               "attributes": {"key": f'{{"id": "{ident}"}}'}}
    search = _search_of({"Triage referral": [hit("a", "X > A"), hit("b", "X > B")],
                         "Book slot": [hit("b", "X > B"), hit("c", "Y > C")]})
    d = _Working(elements={"behavioural": [{"name": "Triage referral"}, {"name": "Book slot"}]},
                 answer={"matched": [{"function": "Triage referral", "capability_id": "a"}]})
    out = asyncio.run(coverage.vector({}, d, [], search=search))
    assert [q for q, _ in search.calls] == ["Triage referral", "Book slot"]
    assert all(k == coverage.VECTOR_HITS for _, k in search.calls)
    assert [c["id"] for c in d.contexts[0]["capabilities"]] == ["a", "b", "c"], "the union, once each"
    assert out["capability_depth"] == coverage.DEEPEST_LEVEL
    assert out["coverage_trail"][0]["candidates"] == 3


def test_the_vector_matcher_defers_without_elements_and_when_the_search_refuses():
    import asyncio
    d = _Working()
    assert asyncio.run(coverage.vector({}, d, [], search=_search_of({}))) == {}
    assert "step 4" in d.pending["5"]

    async def refusing(query, k):
        raise RuntimeError("store not granted")
    d = _Working(elements={"behavioural": [{"name": "Triage"}]}, answer={"matched": []})
    assert asyncio.run(coverage.vector({}, d, [], search=refusing)) == {}
    assert "not granted" in d.pending["5"]


def test_the_drill_fetches_children_by_the_ids_it_matched_through_the_caller_s_seam():
    import asyncio
    asked = []

    async def children(ids, level):
        asked.append((list(ids), level))
        return [concept("b", "Work Queue Management", 2, "a")] if level == 2 else []

    class Walking(_Working):
        def __init__(self):
            super().__init__(answer=None)
            self.level = 0

        async def run_step(self, cfg, step, *, label="", context=None):
            self.level += 1
            self.contexts.append(dict(context or {}))
            first = (context or {}).get("capabilities", [{}])[0]
            self.derived["coverage_map"] = {"matched": [
                {"function": "f", "capability_id": first["id"], "capability_label": first["label"]}]}
            return True

    d = Walking()
    out = asyncio.run(coverage.drill({}, d, TREE, children=children, project=lambda r: r))
    assert asked == [(["a"], 2), (["b"], 3)]
    assert out["capability_depth"] == 2, "no L3 children came back, so the drill stopped there"
