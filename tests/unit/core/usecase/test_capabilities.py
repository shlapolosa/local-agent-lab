"""The technology map's join key, in one place.

`families.py` held it privately, and the enforcement binding and the governance check both need the
identical key — a second spelling of "Domain · Capability" would resolve a reference the first
rejects, which is the failure mode the check exists to catch.
"""
import pytest

from lab.core.usecase import capabilities


def test_the_key_is_domain_middle_dot_capability():
    assert capabilities.key({"domain": "Semantic", "capability": "Ontology (entities, rules)"}) == \
        "Semantic · Ontology (entities, rules)"


def test_the_key_tolerates_the_whitespace_a_hand_edited_row_carries():
    assert capabilities.key({"domain": " Knowledge ", "capability": " Agentic retrieval "}) == \
        "Knowledge · Agentic retrieval"


@pytest.mark.parametrize("row", [{"domain": "Knowledge"}, {"capability": "Agentic retrieval"}, {}])
def test_a_half_row_never_produces_a_key_that_looks_whole(row):
    """A missing half must not yield "Knowledge · " — that would resolve against nothing and read
    as a typo in the guardrail rather than an incomplete row in the map."""
    assert "·" not in capabilities.key(row)


def test_refs_splits_a_guardrails_cap_column():
    """`cap` is not in cells.LIST_COLUMNS — G04's rule text carries a semicolon, so the corpus keeps
    the column joined and the split happens here, at the one place that knows it is a list."""
    assert capabilities.refs("Cognitive · Agent identity; Knowledge · Agentic retrieval") == [
        "Cognitive · Agent identity", "Knowledge · Agentic retrieval"]


def test_a_comma_inside_a_label_is_not_a_separator():
    """Regression, 18 Sep 2026. The inherited split also treated `,` as a separator, and the moment
    a capability carrying one became an enforcement point it was cut in half — reported as a
    guardrail pointing at nothing, in a map that carried the row."""
    assert capabilities.refs("Semantic · Ontology (entities, rules); Cross-cutting · Foo") == [
        "Semantic · Ontology (entities, rules)", "Cross-cutting · Foo"]


def test_refs_accepts_an_already_decoded_list():
    assert capabilities.refs(["A · b", " C · d "]) == ["A · b", "C · d"]


@pytest.mark.parametrize("value", ["", None, "   ", ";  ;"])
def test_refs_of_nothing_is_no_references(value):
    assert capabilities.refs(value) == []


def test_a_reference_naming_no_domain_is_returned_and_left_for_the_caller_to_refuse():
    """Two guardrails cite prose ("the capability map itself"). `refs` does not silently drop them:
    a dropped reference is an unenforced guardrail nobody is told about."""
    assert capabilities.refs("the capability map itself") == ["the capability map itself"]


# ------------------------------------------------- the map, as candidates a matcher can be shown

DOMAINS = [{"domain": "Knowledge", "covers": "grounding sources, agentic retrieval, citations"},
           {"domain": "Cognitive", "covers": "agents, orchestration, models, identity, evaluation"}]
ROWS = [{"domain": "Knowledge", "capability": "Agentic retrieval", "primary": "Foundry IQ",
         "rationale": "federated retrieval over declared sources", "alternative": "Azure AI Search",
         "components": ["cmp-foundryiq"]},
        {"domain": "Cognitive", "capability": "Agent identity", "primary": "Entra Agent ID",
         "rationale": "lifecycle and Conditional Access for agent principals", "alternative": ""}]


def test_the_map_becomes_two_levels_of_concepts():
    out = capabilities.concepts(ROWS, DOMAINS)
    assert [c["level"] for c in out if c["label"] == "Knowledge"] == [1]
    assert [c["level"] for c in out if c["label"] == "Agentic retrieval"] == [2]


def test_a_capabilitys_id_IS_its_join_key_so_a_match_reaches_the_guardrails():
    """The whole reason this map can be matched against at all: what a match returns is the string
    the guardrail chain and the component catalogue already join on. A synthetic id would make the
    match a dead end one hop later."""
    hit = next(c for c in capabilities.concepts(ROWS, DOMAINS) if c["label"] == "Agentic retrieval")
    assert hit["id"] == "Knowledge · Agentic retrieval" == capabilities.key(ROWS[0])
    assert hit["parent"] == "Knowledge"


def test_a_capability_carries_a_definition_built_from_what_the_map_actually_says():
    """A label alone is the least informative field the map has. The rationale is why this row
    exists; the products say what it is. Both travel, so a match is a reading rather than a guess."""
    hit = next(c for c in capabilities.concepts(ROWS, DOMAINS) if c["label"] == "Agentic retrieval")
    assert "federated retrieval over declared sources" in hit["definition"]
    assert "Foundry IQ" in hit["definition"]


def test_a_domain_carries_what_it_covers_as_its_definition():
    hit = next(c for c in capabilities.concepts(ROWS, DOMAINS) if c["label"] == "Knowledge")
    assert "grounding sources" in hit["definition"]


def test_a_capability_whose_domain_was_not_published_still_becomes_a_concept():
    """The two artifacts are separate reads and either can be stale. Dropping the capability would
    silently shrink the candidate set; keeping it, parentless, is visible."""
    out = capabilities.concepts([{"domain": "Nowhere", "capability": "Orphan"}], DOMAINS)
    assert [c["label"] for c in out if c["level"] == 2] == ["Orphan"]


def test_a_row_missing_either_half_of_its_key_is_dropped_rather_than_given_a_broken_id():
    assert capabilities.concepts([{"domain": "Knowledge"}, {"capability": "No domain"}], DOMAINS) \
        == capabilities.concepts([], DOMAINS)


def test_no_rows_is_no_concepts_rather_than_a_skeleton_of_domains():
    """An empty map must read as "no candidates" downstream, which is what makes step 5 default
    rather than match every function to a domain."""
    assert capabilities.concepts([], DOMAINS) == []


def test_a_technology_map_id_is_recognisable_as_one():
    """The mapper has to know which map a match came from, and the ID ITSELF says: a technology
    capability is addressed by its natural key, a business one by a synthetic content id. They
    belong at different ArchiMate layers, so putting a solution ability on the Strategy layer
    beside business abilities would make the repository answer the wrong question."""
    assert capabilities.is_key("Knowledge · Agentic retrieval")
    assert not capabilities.is_key("cap-7f3a91")
    assert not capabilities.is_key("")
