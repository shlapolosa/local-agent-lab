"""Growing the vocabulary: a concept admitted into it is findable, and a retired one still resolves.

The seed is rebuilt from its master at every boot, so curation cannot live only in a scheme — but it must be
IN the scheme, because `find` is what the classifier and the linker ask. These are the two halves: this file
holds the scheme's own behaviour, `test_service_curation.py` holds what makes it durable.
"""
import pytest
from rdflib import URIRef

from lab.core.semantic.fabric.vocabulary import build

DCT_REPLACED = URIRef("http://purl.org/dc/terms/isReplacedBy")


def scheme():
    return build(name="cafe", title="CAFÉ",
                 concepts=[{"id": "AIAgent", "name": "AI agent", "module": "Engineering"},
                           {"id": "UseCase", "name": "Use case", "module": "Business"}],
                 relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])


def test_an_admitted_concept_is_findable_from_then_on():
    sc = scheme()
    assert sc.find("Model card") == []
    c = sc.admit(id="ModelCard", label="Model card", definition="What a model is for", parent="AIAgent",
                 module="Assurance", alt=["model sheet"])
    assert c["curated"] is True and c["level"] == 2
    assert sc.find("Model card")[0]["id"] == "ModelCard" and sc.find("model sheet")[0]["id"] == "ModelCard"
    assert sc.resolve("ModelCard") == "ModelCard" and sc.resolve("Model card") == "ModelCard"
    assert sc.concepts["ModelCard"]["module"] == "Assurance"


def test_admission_refuses_what_it_cannot_place_and_names_what_is_wrong():
    sc = scheme()
    with pytest.raises(ValueError, match="already holds"):
        sc.admit(id="AIAgent", label="Something else")
    with pytest.raises(ValueError, match="parent"):
        sc.admit(id="X", label="X", parent="Nope")
    with pytest.raises(ValueError, match="id"):
        sc.admit(id=" ", label="X")
    with pytest.raises(ValueError, match="label"):
        sc.admit(id="X", label="")


def test_a_retired_concept_still_resolves_to_the_one_that_replaced_it():
    """Never deleted: a link made last month points at the old id, and a lookup that fails on it turns a
    correct historical statement into a dangling one."""
    sc = scheme()
    sc.admit(id="Agent", label="Agent")
    sc.retire("Agent", resolves_to="AIAgent", reason="one meaning, two names")
    assert sc.resolve("Agent") == "AIAgent" and sc.resolve("AIAgent") == "AIAgent"
    assert sc.concepts["Agent"]["retired"] is True and sc.concepts["Agent"]["resolves_to"] == "AIAgent"


def test_a_retired_concept_is_never_offered_as_a_choice_again():
    """It resolves, but it is not a live meaning: a classifier shown it would keep making the link a steward
    just retired, and the picture would grow the term back."""
    sc = scheme()
    sc.admit(id="Agent", label="Agent", alt=["bot"])
    sc.retire("Agent", resolves_to="AIAgent", reason="duplicate")
    assert sc.find("Agent") == [] and sc.find("bot") == []
    assert [c["id"] for c in sc.live()] == ["AIAgent", "UseCase"]
    assert "Agent" in sc.concepts                                   # still there, still resolvable


def test_retirement_refuses_a_successor_that_would_strand_the_link():
    sc = scheme()
    sc.admit(id="Agent", label="Agent")
    with pytest.raises(ValueError, match="itself"):
        sc.retire("Agent", resolves_to="Agent", reason="x")
    with pytest.raises(ValueError, match="does not hold"):
        sc.retire("Agent", resolves_to="Ghost", reason="x")
    with pytest.raises(ValueError, match="does not hold"):
        sc.retire("Ghost", resolves_to="AIAgent", reason="x")
    sc.retire("Agent", resolves_to="AIAgent", reason="x")
    sc.admit(id="Bot", label="Bot")
    with pytest.raises(ValueError, match="itself retired"):         # a chain a reader cannot follow
        sc.retire("Bot", resolves_to="Agent", reason="x")


def test_curation_reaches_the_rdf_and_the_master_alike():
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card", definition="d", module="Assurance")
    sc.retire("UseCase", resolves_to="AIAgent", reason="merged")
    g = sc.graph()
    assert (sc.uri("UseCase"), DCT_REPLACED, sc.uri("AIAgent")) in g
    rows = {r["id"]: r for r in sc.rows()}
    assert rows["ModelCard"]["name"] == "Model card" and rows["ModelCard"]["module"] == "Assurance"
    assert rows["UseCase"]["resolves_to"] == "AIAgent"              # publication carries the retirement too


def test_a_steward_PLACES_a_concept_under_a_broader_one_after_admission():
    """`broader` was settable only at proposal time, so the hierarchy was effectively frozen once a concept was
    admitted — and the batch card deliberately collects no parent, which means almost every admitted concept
    arrived unplaced. Placing is its own act for that reason: a concept earns its parent once somebody knows
    where it belongs, which is usually later."""
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    assert sc.concepts["ModelCard"]["parent"] is None and sc.concepts["ModelCard"]["level"] == 1

    c = sc.place("ModelCard", parent="AIAgent")
    assert (c["parent"], c["level"], c["curated"]) == ("AIAgent", 2, True)
    assert sc.place("ModelCard", parent="UseCase")["parent"] == "UseCase", "a placement can be corrected"
    assert sc.place("ModelCard", parent="")["parent"] is None, "...and lifted back to the root"


def test_placing_refuses_what_would_make_the_hierarchy_a_lie():
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card", parent="AIAgent")
    with pytest.raises(ValueError, match="does not hold"):
        sc.place("Nope", parent="AIAgent")
    with pytest.raises(ValueError, match="does not hold"):
        sc.place("ModelCard", parent="Nope")
    with pytest.raises(ValueError, match="its own parent"):
        sc.place("ModelCard", parent="ModelCard")
    with pytest.raises(ValueError, match="cycle"):
        sc.place("AIAgent", parent="ModelCard")      # ModelCard is already under AIAgent
    sc.retire("ModelCard", resolves_to="AIAgent")
    with pytest.raises(ValueError, match="retired"):
        sc.place("ModelCard", parent="UseCase")


def test_a_steward_RELATES_two_concepts_with_a_typed_predicate():
    """`skos:related` cannot carry what the derived rung needs — "A is about X, X relates to Y, B is about Y" is
    answerable only if the edge names its predicate. So a steward's relation is a typed one, in the same shape
    the seed's own relationships arrive in, and it publishes through the relationships master unchanged."""
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    e = sc.relate(subject="ModelCard", predicate="documents", object="AIAgent", note="per the assurance brief")
    assert e == {"subject": "ModelCard", "predicate": "documents", "object": "AIAgent",
                 "cardinality": "", "note": "per the assurance brief", "curated": True}
    assert ("documents", "AIAgent", "out") in sc.relations_of("ModelCard")
    assert ("documents", "ModelCard", "in") in sc.relations_of("AIAgent")
    assert [r for r in sc.relationships if r.get("curated")] == [e], "separable from the seed, like a concept"


def test_relating_refuses_a_dangling_a_retired_or_a_duplicate_edge():
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    for bad in ({"subject": "Nope", "object": "AIAgent"}, {"subject": "ModelCard", "object": "Nope"}):
        with pytest.raises(ValueError, match="does not hold"):
            sc.relate(predicate="documents", **bad)
    with pytest.raises(ValueError, match="itself"):
        sc.relate(subject="ModelCard", predicate="documents", object="ModelCard")
    with pytest.raises(ValueError, match="predicate"):
        sc.relate(subject="ModelCard", predicate="  ", object="AIAgent")
    sc.relate(subject="ModelCard", predicate="documents", object="AIAgent")
    with pytest.raises(ValueError, match="already"):
        sc.relate(subject="ModelCard", predicate="documents", object="AIAgent")
    sc.retire("ModelCard", resolves_to="AIAgent")
    with pytest.raises(ValueError, match="retired"):
        sc.relate(subject="ModelCard", predicate="documents", object="UseCase")


def test_a_placed_and_related_scheme_round_trips_through_its_master_and_its_rdf():
    """The two acts must survive a publication, or a steward's topology is lost at the next boot. The parent is
    a concept COLUMN and the relation is a relationships ROW, which is why they are two acts and not one."""
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    sc.place("ModelCard", parent="AIAgent")
    sc.relate(subject="ModelCard", predicate="documents", object="UseCase")
    row = next(r for r in sc.rows() if r["id"] == "ModelCard")
    assert row["parent"] == "AIAgent"
    g = sc.graph()
    assert (sc.uri("ModelCard"), URIRef("http://www.w3.org/2004/02/skos/core#broader"), sc.uri("AIAgent")) in g
    assert (sc.uri("ModelCard"), sc.predicate("documents"), sc.uri("UseCase")) in g


def test_a_PREDICATE_must_be_a_name_an_IRI_can_hold_not_prose():
    """A predicate becomes an IRI local name in the scheme's own namespace, so prose with spaces produces a
    graph that cannot be serialised — and the arrow captions this is fed from ("sends a prescription to") are
    exactly that. Recorded in the curated graph, it would replay on every boot, so the refusal has to be here
    and not at the first serialisation."""
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    with pytest.raises(ValueError, match="local name"):
        sc.relate(subject="ModelCard", predicate="sends a prescription to", object="AIAgent")
    with pytest.raises(ValueError, match="local name"):
        sc.relate(subject="ModelCard", predicate="documents\nand assures", object="AIAgent")
    sc.relate(subject="ModelCard", predicate="documents", object="AIAgent", note="sends a prescription to")
    assert sc.graph().serialize(format="turtle"), "a curated relation must survive serialisation"
    assert "sends a prescription to" in sc.relationships[-1]["note"], "the author's wording lives in the note"


def test_the_DUPLICATE_check_folds_case_like_every_other_comparison_here():
    """`find` matches case-folded and the diagram lane's dedup key folds too, so a steward calling `relate`
    directly must not be the one path that can state the same relation twice."""
    sc = scheme()
    sc.admit(id="ModelCard", label="Model card")
    sc.relate(subject="ModelCard", predicate="documents", object="AIAgent")
    with pytest.raises(ValueError, match="already"):
        sc.relate(subject="ModelCard", predicate="Documents", object="AIAgent")


def test_a_refused_placement_restores_every_DESCENDANTS_level_not_just_its_own():
    """`place` recomputes the level of every concept, so a rollback that restores one row leaves a whole
    subtree reporting the wrong depth — and `level` is not inert: it reaches an agent's prompt through the
    concept doc string (`L{level}`)."""
    sc = scheme()
    sc.admit(id="Deep", label="Deep", parent="AIAgent")
    sc.admit(id="X", label="X")
    sc.admit(id="D", label="D", parent="X")
    sc.admit(id="E", label="E", parent="D")
    before = {c: sc.concepts[c]["level"] for c in ("X", "D", "E")}
    assert before == {"X": 1, "D": 2, "E": 3}

    sc.place("X", parent="Deep")
    assert [sc.concepts[c]["level"] for c in ("X", "D", "E")] == [3, 4, 5]
    sc.place("X", parent="")                       # the rollback a caller performs: put it back
    assert {c: sc.concepts[c]["level"] for c in ("X", "D", "E")} == before
