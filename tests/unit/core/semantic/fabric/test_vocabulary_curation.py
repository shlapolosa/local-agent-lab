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
