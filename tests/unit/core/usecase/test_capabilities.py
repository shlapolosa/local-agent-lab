"""The technology capability map's join key, in one place.

Since the CAFÉ workbook of 28 Sep 2026 the map is its own artifact — `technology-capability-l1/l2/
l3` — and every reference INTO it is an L3 ID: a guardrail's `cap` reads "COG.11 Agent definition
integrity", a component's `l3` reads "TEC.06; COG.05", and the realisation view
(`ai-capability-map`) carries exactly one row per L3 by `l3_id`. The old key, "Domain · Capability",
resolves against nothing in that corpus — 0 of 81 guardrail references did — so a second spelling
anywhere is a silently unenforced guardrail.
"""
import pytest

from lab.core.usecase import capabilities


def test_the_key_of_a_technology_L3_row_is_its_id():
    assert capabilities.key({"id": "KNW.11", "name": "Agentic retrieval"}) == "KNW.11"


def test_the_key_of_a_realisation_view_row_is_the_L3_it_realises():
    """One row per L3 in `ai-capability-map`, joined by `l3_id` — so the second hop of the chain
    (capability -> components) is keyed identically to the first."""
    assert capabilities.key({"l3_id": " COG.02 ", "domain": "Cognitive",
                             "capability": "Custom agent hosting"}) == "COG.02"


@pytest.mark.parametrize("row", [{"domain": "Knowledge", "capability": "Agentic retrieval"},
                                 {"id": "B1.1.2"}, {"id": "BUS-A"}, {}])
def test_a_row_that_is_not_a_technology_L3_has_no_key(row):
    """A business L3 (B1.1.2), an L2 (BUS-A) and an old-style labelled row must not produce a key
    that looks whole — it would resolve against nothing and read as a typo in the guardrail."""
    assert capabilities.key(row) == ""


def test_refs_reads_the_L3_ids_out_of_a_guardrails_cap_column():
    assert capabilities.refs("COG.11 Agent definition integrity; XCT.22 Approval & gate evidence") \
        == ["COG.11", "XCT.22"]


def test_refs_reads_a_components_bare_l3_list():
    assert capabilities.refs("TEC.06; COG.05") == ["TEC.06", "COG.05"]


def test_a_comma_inside_a_label_is_not_a_separator():
    """Regression, 18 Sep 2026: splitting on `,` cut a label in half."""
    assert capabilities.refs("SEM.03 Ontology (entities, rules); XCT.01 Foo") == ["SEM.03", "XCT.01"]


def test_refs_accepts_an_already_decoded_list():
    assert capabilities.refs(["COG.11 Agent", " TEC.06 "]) == ["COG.11", "TEC.06"]


@pytest.mark.parametrize("value", ["", None, "   ", ";  ;"])
def test_refs_of_nothing_is_no_references(value):
    assert capabilities.refs(value) == []


def test_a_reference_that_is_prose_is_returned_for_the_caller_to_refuse():
    """A dropped reference is an unenforced guardrail nobody is told about."""
    assert capabilities.refs("the capability map itself") == ["the capability map itself"]


def test_component_ids_pass_through_refs_untouched():
    """`refs` also splits the realisation view's `components` column — catalogue ids, not L3s."""
    assert capabilities.refs("cmp-34dd73a433; cmp-4c70d67472") == ["cmp-34dd73a433",
                                                                  "cmp-4c70d67472"]


# ------------------------------------------------- the map, as candidates a matcher can be shown

L1 = [{"id": "KNW", "name": "Knowledge", "description": "Finding and supplying grounding content."},
      {"id": "COG", "name": "Cognitive", "description": "Agents, models, identity."}]
L2 = [{"id": "KNW-B", "l1": "KNW", "name": "Retrieval", "description": "Getting the right content."},
      {"id": "COG-A", "l1": "COG", "name": "Agent runtime", "description": "Hosting agents."}]
L3 = [{"id": "KNW.11", "l1": "KNW", "l2": "KNW-B", "name": "Agentic retrieval",
       "description": "Federated retrieval over declared sources.",
       "when_exercised": "Runtime · on every retrieval"},
      {"id": "COG.02", "l1": "COG", "l2": "COG-A", "name": "Custom agent hosting",
       "description": "Runs agents the organisation builds.", "when_exercised": "Run"}]


def _concepts():
    return capabilities.concepts(L3, L1 + L2)


def test_the_map_becomes_three_levels_of_concepts():
    by = {c["label"]: c["level"] for c in _concepts()}
    assert (by["Knowledge"], by["Retrieval"], by["Agentic retrieval"]) == (1, 2, 3)


def test_a_capabilitys_id_IS_its_join_key_so_a_match_reaches_the_guardrails():
    hit = next(c for c in _concepts() if c["label"] == "Agentic retrieval")
    assert hit["id"] == "KNW.11" == capabilities.key(L3[0])
    assert hit["parent"] == "KNW-B"
    assert hit["path"] == "Knowledge · Retrieval · Agentic retrieval"


def test_a_capability_carries_what_the_map_says_about_it_and_WHEN_it_is_exercised():
    hit = next(c for c in _concepts() if c["label"] == "Agentic retrieval")
    assert "Federated retrieval" in hit["definition"] and "every retrieval" in hit["definition"]


def test_a_capability_whose_parents_were_not_published_still_becomes_a_concept():
    """Separate reads, either can be stale: dropping the L3 would silently shrink the candidates."""
    out = capabilities.concepts([dict(L3[0], l2="ZZZ-Q")], L1 + L2)
    assert [c["id"] for c in out if c["level"] == 3] == ["KNW.11"]


def test_a_row_without_an_L3_id_is_dropped_rather_than_given_a_broken_one():
    assert capabilities.concepts([{"name": "no id"}], L1 + L2) == []


def test_no_rows_is_no_concepts_rather_than_a_skeleton_of_parents():
    assert capabilities.concepts([], L1 + L2) == []


def test_only_the_parents_actually_used_are_offered():
    ids = {c["id"] for c in capabilities.concepts(L3[:1], L1 + L2)}
    assert {"KNW", "KNW-B", "KNW.11"} == ids


def test_a_technology_L3_id_is_recognisable_as_one():
    """Which map a match came from decides its ArchiMate layer — and the id alone says: a technology
    L3 is `KNW.11`, a business one `B1.1.2`."""
    assert capabilities.is_key("KNW.11")
    assert not capabilities.is_key("B1.1.2")
    assert not capabilities.is_key("Knowledge · Agentic retrieval")
    assert not capabilities.is_key("")


def test_a_capabilitys_domain_is_its_L1():
    assert capabilities.domain("KNW.11") == "KNW"
    assert capabilities.domain("B1.1.2") == ""


def test_a_label_written_WITH_its_id_is_trimmed_back_to_the_label():
    """A drawing reads "Agentic retrieval". Models put the key into the label field (measured), so
    the label is trimmed of a leading id — and only a leading id."""
    assert capabilities.label("KNW.11 Agentic retrieval") == "Agentic retrieval"
    assert capabilities.label("Agentic retrieval") == "Agentic retrieval"
    assert capabilities.label("KNW.11") == "KNW.11"


@pytest.mark.parametrize("cell", ["COG.11, COG.12 Agent integrity", "XCT.22/XCT.23 gates"])
def test_an_item_naming_TWO_ids_is_returned_whole_so_it_dangles_loudly(cell):
    """Review F6, 28 Sep 2026: "COG.11, COG.12 Agent integrity" was trimmed to COG.11 and the second
    id vanished — a guardrail nobody is told is unenforced, invisible to the governance check that
    resolves through this same function. Trimmed only when exactly one id leads it."""
    assert capabilities.refs(cell) == [cell]
