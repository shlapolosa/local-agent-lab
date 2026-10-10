"""Curation that SURVIVES: the seed is rebuilt from its master at every boot, so what a steward decided must
live in a persisted graph and be replayed onto the seed — and an ambiguous term must reach the steward rather
than being guessed at."""
import pytest
from rdflib import Dataset, URIRef

from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.rungs import CONFIRMED, CURATED_GRAPH
from lab.core.semantic.fabric.service import PERSISTED_GRAPHS, FabricService
from lab.core.semantic.fabric.vocabulary import build


def scheme():
    return build(name="cafe", title="CAFÉ",
                 concepts=[{"id": "AIAgent", "name": "AI agent", "module": "Engineering",
                            "alt": ["Agent"]},                      # the ambiguity a steward must settle
                           {"id": "UseCase", "name": "Use case", "module": "Business"},
                           {"id": "LegacyAgent", "name": "Legacy agent"}],
                 relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])


@pytest.fixture
def fab():
    sc = scheme()
    ds = Dataset(default_union=True)
    ds.graph(URIRef("urn:lab:semantic:vocab:cafe")).__iadd__(sc.graph())
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {"cafe": sc})
    f.scheme = sc                     # type: ignore[attr-defined]
    return f


def _doc(f, title="ADR-14"):
    return f.catalog_upsert({"source": "collab", "handle": f"collab://item/{title}"}, title=title)["iri"]


def test_the_curated_delta_is_a_persisted_graph_so_a_rebuild_does_not_lose_it():
    assert PERSISTED_GRAPHS["curated"] == CURATED_GRAPH


def test_accepting_a_candidate_puts_it_in_the_vocabulary(fab):
    """Admission used to write one lifecycle triple and leave the concept where no lookup could reach it — so
    the same term was proposed again the next time a document used it."""
    c = fab.vocab_propose("Model card", actor="steward@x", definition="What a model is for", scheme="cafe")
    assert fab.scheme.find("Model card") == []                      # parked, not admitted
    r = fab.promote(c["iri"], actor="steward@x", method="review")
    assert r["from"] == "candidates" and r["scheme"] == "cafe" and r["concept_id"] == "ModelCard"
    assert fab.scheme.find("Model card")[0]["id"] == "ModelCard"
    assert fab.scheme.concepts["ModelCard"]["definition"] == "What a model is for"


def test_an_admitted_concept_can_be_linked_like_any_other(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    iri = _doc(fab)
    assert fab.vocab_link(iri, ["Model card"])["linked"][0]["concept"].endswith("#ModelCard")


def test_a_candidate_with_no_home_is_refused_naming_what_is_missing(fab):
    c = fab.vocab_propose("Model card", actor="s@x")                # no scheme named
    with pytest.raises(ValueError, match="scheme"):
        fab.promote(c["iri"], actor="s@x", method="review")
    with pytest.raises(LookupError, match="not a candidate"):
        fab.promote("urn:fabric:candidate:nope", actor="s@x", method="review")


def test_curation_is_replayed_onto_a_freshly_seeded_scheme(fab):
    """The boot path: the master is read again, so the scheme object is NEW and knows nothing a steward did."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    fab.vocab_retire("LegacyAgent", scheme="cafe", resolves_to="AIAgent", actor="s@x", reason="one meaning, two names")

    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    assert fresh.find("Model card") == [] and fresh.find("Legacy agent") != []   # the seed, before replay
    assert fab.recurate().items() >= {"admitted": 1, "retired": 1, "failed": 0}.items()
    assert fresh.find("Model card")[0]["id"] == "ModelCard"
    assert fresh.find("Legacy agent") == [] and fresh.resolve("LegacyAgent") == "AIAgent"
    twice = fab.recurate()                                                   # replaying changes nothing more
    assert twice["admitted"] == twice["retired"] == twice["failed"] == 0 and twice["skipped"] == 2


def test_a_term_with_two_meanings_goes_to_a_steward_instead_of_linking_to_both(fab):
    """`vocab_link` used to link a document to EVERY match. A document about one of two meanings then carried
    both, and no reader could tell which was meant — the picture, the impact and the search all inherit it."""
    fab.scheme.admit(id="SoftwareAgent", label="Agent", definition="a process acting for a user")
    assert len(fab.scheme.find("Agent")) == 2                       # by LABEL: an exact id still wins alone
    iri = _doc(fab)
    r = fab.vocab_link(iri, ["Agent", "AI agent"])
    assert [l["term"] for l in r["linked"]] == ["AI agent"]
    assert r["conflicts"][0]["term"] == "Agent"
    assert sorted(r["conflicts"][0]["concepts"]) == ["AIAgent", "SoftwareAgent"]
    assert [l.get("label") for l in fab.catalog_get(iri)["links"]] == ["AI agent"]


def test_a_conflict_is_recorded_for_the_steward_not_only_returned(fab):
    fab.scheme.admit(id="SoftwareAgent", label="Agent")
    fab.vocab_link(_doc(fab), ["Agent"])
    open_ = fab.vocab_conflicts()
    assert len(open_) == 1 and open_[0]["term"] == "Agent"
    assert open_[0]["concepts"] == ["AIAgent", "SoftwareAgent"] and open_[0]["scheme"] == "cafe"
    fab.vocab_link(_doc(fab, "ADR-15"), ["Agent"])                  # the same ambiguity, twice
    assert len(fab.vocab_conflicts()) == 1                          # one thing for a steward to settle, not two


def test_retirement_is_a_persons_decision_recorded_at_their_rung(fab):
    r = fab.vocab_retire("LegacyAgent", scheme="cafe", resolves_to="AIAgent", actor="steward@x", reason="duplicate")
    assert r["rung"] == CONFIRMED and r["actor"] == "steward@x"
    with pytest.raises(ValueError, match="actor"):
        fab.vocab_retire("UseCase", scheme="cafe", resolves_to="AIAgent", actor="", reason="x")
    with pytest.raises(LookupError, match="risk"):
        fab.vocab_retire("UseCase", scheme="risk", resolves_to="AIAgent", actor="s@x", reason="x")


def test_a_term_that_means_a_concept_already_held_becomes_another_name_for_it(fab):
    """Not a second concept: admitting one would be exactly the duplicate the vocabulary exists to prevent."""
    iri = _doc(fab)
    assert fab.vocab_link(iri, ["Digital worker"])["missed"] == ["Digital worker"]
    fab.vocab_amend("AIAgent", scheme="cafe", alt="Digital worker", actor="steward@x", reason="same thing")
    assert fab.vocab_link(iri, ["Digital worker"])["linked"][0]["concept"].endswith("#AIAgent")
    assert len(fab.scheme.live()) == 3                              # nothing was added
    with pytest.raises(ValueError, match="actor"):
        fab.vocab_amend("AIAgent", scheme="cafe", alt="x", actor="")


def test_an_amendment_survives_the_rebuild_like_every_other_decision(fab):
    fab.vocab_amend("AIAgent", scheme="cafe", alt="Digital worker", actor="s@x")
    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    assert fresh.find("Digital worker") == []
    assert fab.recurate()["amended"] == 1
    assert fresh.find("Digital worker")[0]["id"] == "AIAgent"


def test_a_settled_ambiguity_stops_being_asked_about(fab):
    """Openness is derived from the vocabulary, so every way of settling one closes it. A marker would have to
    be written by each path, and the path that forgot would re-ask the steward on every restart forever."""
    fab.scheme.admit(id="SoftwareAgent", label="Agent")
    fab.vocab_link(_doc(fab), ["Agent"])
    assert len(fab.vocab_conflicts()) == 1
    fab.vocab_retire("SoftwareAgent", scheme="cafe", resolves_to="AIAgent", actor="steward@x", reason="settled")
    assert fab.vocab_conflicts() == []
    assert fab.vocab_link(_doc(fab, "ADR-16"), ["Agent"])["linked"][0]["concept"].endswith("#AIAgent")


def test_a_child_admitted_in_the_same_second_as_its_parent_replays_either_way(fab):
    """`graph.now()` is second-resolution, so two decisions in one second TIE and the tie would be broken by
    rdflib's iteration order. Passes make the order stop mattering."""
    parent = fab.vocab_propose("Model artefact", actor="s@x", scheme="cafe", concept_id="ModelArtefact")
    fab.promote(parent["iri"], actor="s@x", method="review")
    child = fab.vocab_propose("Model card", actor="s@x", scheme="cafe", concept_id="ModelCard",
                              broader="ModelArtefact")
    fab.promote(child["iri"], actor="s@x", method="review")
    assert fab.scheme.concepts["ModelCard"]["parent"] == "ModelArtefact"
    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    assert fab.recurate()["admitted"] == 2 and fresh.concepts["ModelCard"]["parent"] == "ModelArtefact"


def test_one_unplaceable_row_is_named_and_the_rest_still_apply(fab, capsys):
    """This runs inside boot(). A row that cannot be placed must not stop a service starting — it would
    refuse identically on every restart, with the bad row still in the store."""
    fab.vocab_amend("AIAgent", scheme="cafe", alt="Digital worker", actor="s@x")
    fab._record_curation("cafe", "admitted", {"id": "Broken", "label": "B", "parent": "Nowhere"},
                         actor="s@x", method="review", to="H")
    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    counts = fab.recurate()
    printed = capsys.readouterr().out
    assert counts["failed"] == 1 and counts["amended"] == 1        # the good row landed
    assert "could not be replayed" in printed and "Nowhere" in printed     # and the bad one says why
    assert fresh.find("Digital worker")[0]["id"] == "AIAgent" and "Broken" not in fresh.concepts


def test_a_replay_with_nothing_to_do_is_distinguishable_from_one_that_lost_something(fab):
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    again = fab.recurate()                                          # same scheme: everything already applied
    assert again["admitted"] == 0 and again["skipped"] == 1 and again["failed"] == 0


def test_the_same_word_in_two_vocabularies_is_not_an_ambiguity(fab):
    """That is what having two vocabularies means. Flattening them also lost which scheme each id came from,
    so settling one would have retired a foreign id — after the steward had answered."""
    other = build(name="risk", title="Risk", concepts=[{"id": "Agent", "name": "Agent"}])
    fab._schemes = lambda: {"cafe": fab.scheme, "risk": other}
    iri = _doc(fab)
    r = fab.vocab_link(iri, ["Agent"])
    assert sorted(l["scheme"] for l in r["linked"]) == ["cafe", "risk"] and r["conflicts"] == []
    fab.scheme.admit(id="SoftwareAgent", label="Agent")              # NOW cafe alone is ambiguous
    r = fab.vocab_link(_doc(fab, "ADR-17"), ["Agent"])
    assert [c["scheme"] for c in r["conflicts"]] == ["cafe"]
    assert [l["scheme"] for l in r["linked"]] == ["risk"]             # the unambiguous one is still linked


def test_one_ambiguity_is_one_decision_however_it_is_spelled(fab):
    fab.scheme.admit(id="SoftwareAgent", label="Agent")
    fab.vocab_link(_doc(fab), ["Agent"])
    fab.vocab_link(_doc(fab, "ADR-18"), ["agent"])                    # `find` matches case-insensitively
    assert len(fab.vocab_conflicts()) == 1


def test_admitting_the_same_concept_twice_admits_it_once(fab):
    """A redrive of a decision whose first attempt landed, or a steward answering twice. Raising would leave
    the approval permanently stuck behind a confusing error.

    The SAME candidate is promoted twice, which is what a redrive actually replays. It used to be set up by
    proposing the term a second time; that no longer mints anything, because once the scheme holds the word
    `vocab_propose` reports who holds it instead of parking a duplicate — asserted below, since it is the
    other half of the same guarantee."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    first = fab.promote(c["iri"], actor="s@x", method="review")
    second = fab.promote(c["iri"], actor="s@x", method="review")
    assert first["concept_id"] == second["concept_id"] == "ModelCard" and second.get("already") is True
    assert len([c for c in fab.scheme.live() if c["label"] == "Model card"]) == 1
    # ...and the word now MEANS something, so proposing it again is answered, not parked
    again = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    assert again["held_by"] == "cafe" and "iri" not in again
