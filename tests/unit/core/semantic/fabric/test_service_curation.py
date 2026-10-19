"""Curation that SURVIVES: the seed is rebuilt from its master at every boot, so what a steward decided must
live in a persisted graph and be replayed onto the seed — and an ambiguous term must reach the steward rather
than being guessed at."""
import pytest
from rdflib import Dataset, URIRef

from lab.core.semantic.fabric import graph as G
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


def test_placing_and_relating_are_a_persons_decisions_recorded_at_their_rung(fab):
    """The two acts steward B has, and both are a person's: `actor` is refused blank for the same reason a
    retirement's is — "who organised this vocabulary" is what the record is for."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    assert fab.scheme.concepts["ModelCard"]["parent"] is None

    placed = fab.vocab_place("ModelCard", scheme="cafe", parent="AIAgent", actor="s@x", reason="assurance")
    assert (placed["parent"], placed["rung"], placed["actor"]) == ("AIAgent", CONFIRMED, "s@x")
    assert placed["assertion"] and placed["concept"].endswith("ModelCard")
    assert fab.scheme.concepts["ModelCard"]["parent"] == "AIAgent"

    related = fab.vocab_relate(scheme="cafe", subject="ModelCard", predicate="documents", object="UseCase",
                               actor="s@x", note="per the brief")
    assert (related["predicate"], related["object"], related["actor"]) == ("documents", "UseCase", "s@x")
    assert ("documents", "UseCase", "out") in fab.scheme.relations_of("ModelCard")

    for blank in (lambda: fab.vocab_place("ModelCard", scheme="cafe", parent="UseCase", actor=""),
                  lambda: fab.vocab_relate(scheme="cafe", subject="ModelCard", predicate="x",
                                           object="AIAgent", actor="")):
        with pytest.raises(ValueError, match="actor is required"):
            blank()


def test_a_placement_and_a_relation_survive_the_rebuild_like_every_other_decision(fab):
    """The trap this phase had to avoid: a new curation act that `_replay` does not know is DURABLE AND
    INVISIBLE — recorded faithfully, replayed never, and so lost at the first boot. `recurate` raises on an
    act it cannot apply, which is why the act and its replay land together."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    fab.vocab_place("ModelCard", scheme="cafe", parent="AIAgent", actor="s@x")
    fab.vocab_relate(scheme="cafe", subject="ModelCard", predicate="documents", object="UseCase", actor="s@x")

    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    counts = fab.recurate()
    assert counts["failed"] == 0, "an act the replay cannot apply is the whole failure mode here"
    assert counts["placed"] == 1 and counts["related"] == 1
    assert fresh.concepts["ModelCard"]["parent"] == "AIAgent" and fresh.concepts["ModelCard"]["level"] == 2
    assert ("documents", "UseCase", "out") in fresh.relations_of("ModelCard")
    twice = fab.recurate()
    assert twice["placed"] == twice["related"] == twice["failed"] == 0 and twice["skipped"] == 3


def test_a_placement_replays_AFTER_the_admission_it_depends_on(fab):
    """A placement names a parent, and the concept it places may itself have been admitted in the same second.
    Admissions replay first and in passes for exactly that reason; a placement must not be what breaks it."""
    for label, cid in (("Model card", "ModelCard"), ("Eval report", "EvalReport")):
        c = fab.vocab_propose(label, actor="s@x", scheme="cafe")
        fab.promote(c["iri"], actor="s@x", method="review")
    fab.vocab_place("EvalReport", scheme="cafe", parent="ModelCard", actor="s@x")

    fresh = scheme()
    fab._schemes = lambda: {"cafe": fresh}
    counts = fab.recurate()
    assert counts["failed"] == 0 and counts["admitted"] == 2 and counts["placed"] == 1
    assert fresh.concepts["EvalReport"]["parent"] == "ModelCard" and fresh.concepts["EvalReport"]["level"] == 2


def test_a_placement_that_cannot_be_applied_leaves_the_scheme_as_it_was(fab):
    """`place` recomputes the level, which is what catches a cycle — and the whole row is restored, because
    `place` also sets `curated` and a seed concept left marked that way would be published as part of the
    delta by a write the store never took."""
    c = fab.vocab_propose("Model card", actor="s@x", scheme="cafe")
    fab.promote(c["iri"], actor="s@x", method="review")
    fab.vocab_place("ModelCard", scheme="cafe", parent="AIAgent", actor="s@x")
    with pytest.raises(ValueError, match="cycle"):
        fab.vocab_place("AIAgent", scheme="cafe", parent="ModelCard", actor="s@x")
    assert fab.scheme.concepts["AIAgent"].get("parent") is None
    assert not fab.scheme.concepts["AIAgent"].get("curated"), "a refused placement marks nothing as curated"


def test_a_diagram_yields_relation_candidates_resolved_against_the_vocabulary(fab):
    """Steward B's feeder, through the real scheme. The two seams the pure rule needs come from here: a term
    resolves through `find` (so an ALT label works), and "already stated" is read off the vocabulary's own
    relationships — the seed's and the curated ones alike."""
    arrows = [{"from": "AI agent", "to": "Use case", "label": "realises"},      # the seed already states this
              {"from": "Agent", "to": "Legacy agent", "label": "supersedes"},   # 'Agent' is an ALT of AIAgent
              {"from": "AI agent", "to": "Billing engine", "label": "feeds"},   # a box with no concept
              {"from": "AI agent", "to": "Legacy agent"}]                       # drawn, unnamed
    out = fab.vocab_relation_candidates(arrows, scheme="cafe")
    assert out["gaps"] == ["Billing engine"], "a box the vocabulary cannot name is the finding, not an error"
    assert [(c["subject"], c["predicate"], c["object"]) for c in out["candidates"]] == [
        ("AIAgent", "", "LegacyAgent"), ("AIAgent", "supersedes", "LegacyAgent")]
    assert out["candidates"][0]["unnamed"] is True
    assert out["scheme"] == "cafe"


def test_an_AMBIGUOUS_box_resolves_to_nothing_rather_than_to_a_guess(fab):
    """'Agent' is an alt of AIAgent here; make it ambiguous and the box must stop resolving. Choosing between
    two meanings narrows the vocabulary, and that is not a question a diagram may settle."""
    fab.scheme.amend("UseCase", alt="Agent")                      # now 'Agent' means two things
    out = fab.vocab_relation_candidates([{"from": "Agent", "to": "Legacy agent", "label": "x"}], scheme="cafe")
    assert out["candidates"] == [] and out["gaps"] == ["Agent"]


def test_a_relation_a_steward_has_already_stated_stops_being_proposed(fab):
    arrows = [{"from": "AI agent", "to": "Legacy agent", "label": "supersedes"}]
    assert fab.vocab_relation_candidates(arrows, scheme="cafe")["candidates"]
    fab.vocab_relate(scheme="cafe", subject="AIAgent", predicate="supersedes", object="LegacyAgent", actor="s@x")
    assert fab.vocab_relation_candidates(arrows, scheme="cafe")["candidates"] == []


def test_a_placement_the_STORE_REFUSES_restores_every_descendants_level_too(fab):
    """A placement moves a whole SUBTREE, so restoring the one row it names is not a rollback. The older acts
    (`retire`, `amend`) touch a single concept, which is why copying their idiom was the defect: measured, a
    refused persist left a three-deep subtree reporting depths 4 and 5 while its root was back at 1.

    `level` is not inert — `SkosScheme` puts `L{level}` into the concept doc string an agent is shown, so a
    stale depth reaches a classifier's prompt."""
    sc = fab.scheme
    sc.admit(id="Deep", label="Deep", parent="AIAgent")
    sc.admit(id="X", label="X")
    sc.admit(id="D", label="D", parent="X")
    sc.admit(id="E", label="E", parent="D")
    before = {c: sc.concepts[c]["level"] for c in ("X", "D", "E")}
    row = dict(sc.concepts["X"])

    fab._on_write = lambda touched: (_ for _ in ()).throw(RuntimeError("the store did not take it"))
    with pytest.raises(RuntimeError, match="did not take"):
        fab.vocab_place("X", scheme="cafe", parent="Deep", actor="s@x")

    assert sc.concepts["X"]["parent"] is None, "the placed concept is back where it was"
    assert {c: sc.concepts[c]["level"] for c in ("X", "D", "E")} == before, "and so is its whole subtree"
    assert sc.concepts["X"] == row, "the row comes back exactly as it was, `curated` included — a seed " \
                                    "concept left marked would be published by a write never taken"


def test_a_diagram_BOX_resolves_through_the_same_normaliser_the_classifier_uses(fab):
    """`find` folds case and strips, nothing more. A diagram's boxes are authored by hand, so they arrive
    plural, with an article, and wrapped across two lines — and each of those became a GAP asking a steward to
    admit a concept the vocabulary already held, while the relation it was drawn on was dropped.

    This is the one place the diagram lane and the classifier lane could disagree about what a term IS, which
    is what `concepts.normalise` exists to prevent."""
    arrows = [{"from": "AI agents", "to": "Legacy agent", "label": "supersedes"},      # plural
              {"from": "The AI agent", "to": "Legacy agent", "label": "replaces"},     # leading article
              {"from": "AI   agent", "to": "Legacy agent", "label": "informs"}]        # a wrapped caption
    out = fab.vocab_relation_candidates(arrows, scheme="cafe")
    assert out["gaps"] == [], f"every box names a concept the vocabulary holds: {out['gaps']}"
    assert {c["subject"] for c in out["candidates"]} == {"AIAgent"}
    assert len(out["candidates"]) == 3


def test_a_CONFLICT_remembers_that_a_steward_was_asked_exactly_as_a_candidate_does(fab):
    """The other half of the gate, and the half that had no memory. A candidate records `fab:InReview` so
    nobody asks twice (71 cards became 101 in one afternoon without it); a conflict recorded nothing, so
    the reconciler re-raised the same ambiguity on EVERY sweep tick — about 96 cards a day, each one a
    question somebody had already been asked.

    Openness stays DERIVED (a settled ambiguity disappears because the term stops matching twice).
    ASKEDNESS is the thing that must be durable, which is the same split the candidate register makes."""
    doc = _doc(fab)
    fab.scheme.amend("UseCase", alt="Agent")             # now "Agent" has two live meanings
    fab.vocab_link(doc, ["Agent"])                       # ...which is a steward's decision, not a guess
    opened = fab.vocab_conflicts()
    assert len(opened) == 1 and opened[0]["asked"] == ""

    marked = fab.vocab_asked(opened[0]["iri"], request_id="apr-7")
    assert marked["asked"] is True
    assert fab.vocab_conflicts()[0]["asked"] == "apr-7"
    assert fab.vocab_asked(opened[0]["iri"], request_id="apr-8")["already"] is True, "asked once"

    # ...and it is still OPEN: being asked is not being answered.
    assert len(fab.vocab_conflicts()) == 1


# ---------------------------------------------------------------- the ontology register (steward B)

def test_a_RELATION_QUESTION_is_parked_once_however_many_producers_propose_it(fab):
    """Two producers feed this queue — a diagram's arrows and the corpus's co-occurrences — and both
    recompute their candidates every time they run. So the CANDIDATE is not what must be durable; what
    must be durable is that somebody was ASKED, and that somebody said no.

    That is `_conflict`'s shape, not `_candidate_for`'s: a keyed idempotent node whose openness is
    DERIVED. A relation the vocabulary now states disappears from the queue without anybody marking it,
    which is the only way a queue cannot drift from the thing it is a queue for."""
    one = fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="realisedBy",
                                     object="UseCase", evidence="3 documents are about both")
    again = fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="RealisedBy",
                                       object="UseCase", evidence="a diagram says so")
    assert again["iri"] == one["iri"], "the predicate's case is not a second question"
    assert len(fab.vocab_relation_open()) == 1

    row = fab.vocab_relation_open()[0]
    assert (row["subject"], row["predicate"], row["object"]) == ("AIAgent", "realisedBy", "UseCase")
    assert row["asked"] == "" and row["evidence"]


def test_a_relation_the_VOCABULARY_NOW_STATES_drops_out_of_the_queue_by_itself(fab):
    """Derived openness. A steward who answers through some other surface — or a seed that is
    republished with the relation already in it — must not leave a question behind, and no marker
    written by one path can be relied on by all of them."""
    fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="documents", object="UseCase")
    assert len(fab.vocab_relation_open()) == 1
    fab.vocab_relate(scheme="cafe", subject="AIAgent", predicate="documents", object="UseCase", actor="s@x")
    assert fab.vocab_relation_open() == []


def test_a_DECLINED_relation_is_never_asked_about_again(fab):
    """Without a durable NO a restart re-asks everything — 71 cards became 101 in one afternoon. A
    person's answer about a relation deserves what a person's answer about a term already has."""
    parked = fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="owns", object="UseCase")
    fab.vocab_relation_decline(parked["iri"], actor="s@x", reason="they are not connected that way")
    assert fab.vocab_relation_open() == []
    # ...and re-proposing it does not reopen the question a person has already settled
    fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="owns", object="UseCase")
    assert fab.vocab_relation_open() == []


def test_a_relation_question_remembers_it_was_ASKED(fab):
    parked = fab.vocab_relation_propose(scheme="cafe", subject="AIAgent", predicate="serves", object="UseCase")
    assert fab.vocab_asked(parked["iri"], request_id="apr-9")["asked"] is True
    assert fab.vocab_relation_open()[0]["asked"] == "apr-9", "still open — being asked is not being answered"


def test_CONCEPT_PAIRS_finds_what_the_corpus_connects_and_the_vocabulary_does_not(fab):
    """The second producer. A diagram is the sharpest evidence about how concepts relate, but it only
    helps where diagrams are ingested — and the corpus itself is saying something all the time: two
    concepts that keep turning up on the same documents are probably related, and the vocabulary that
    says nothing about them has a gap a steward can close.

    It is computed HERE, in process, over the graph: a caller doing this per record over the gateway
    pays a round trip each and trips its own rate limit at about sixty, which is the measurement
    `corpus_view` already records."""
    # AIAgent + LegacyAgent: the corpus puts them together and the vocabulary says nothing about them.
    # (AIAgent + UseCase is already stated by the seed — see the second half.)
    a, b, c = (fab.scheme.uri(x) for x in ("AIAgent", "LegacyAgent", "UseCase"))
    for n in range(3):
        doc = _doc(fab, f"both-{n}")
        for concept in (a, b):
            fab.graph_assert(doc, str(G.DCT.subject), str(concept), rung="X", method="label-match")
    once = _doc(fab, "once")
    for concept in (b, c):
        fab.graph_assert(once, str(G.DCT.subject), str(concept), rung="X", method="label-match")

    pairs = fab.concept_pairs(min_records=2)
    assert [(p["subject"], p["object"], p["records"]) for p in pairs] == [("AIAgent", "LegacyAgent", 3)]
    assert pairs[0]["evidence"] == "3 records are about both" and pairs[0]["scheme"] == "cafe"

    # ...and a pair the vocabulary ALREADY connects is not a gap, however often it co-occurs: the seed
    # states AIAgent realises UseCase, so no number of documents about both makes it a question.
    for n in range(3):
        doc = _doc(fab, f"stated-{n}")
        for concept in (a, c):
            fab.graph_assert(doc, str(G.DCT.subject), str(concept), rung="X", method="label-match")
    assert all((p["subject"], p["object"]) != ("AIAgent", "UseCase") for p in fab.concept_pairs(min_records=2))

    fab.vocab_relate(scheme="cafe", subject="AIAgent", predicate="supersedes", object="LegacyAgent",
                     actor="s@x")
    assert fab.concept_pairs(min_records=2) == [], "answering it removes it from the queue's source too"


def test_a_PROSE_arrow_label_becomes_a_question_a_person_CAN_answer(fab):
    """A diagram's arrow says "is realised by", and `relations.candidates` carries the caption verbatim.
    Parked as the predicate, the card then offers plain `relate` — and `vocab_relate` REFUSES it, because
    a predicate is an IRI local name. A steward handed a card they cannot answer correctly is worse than
    no card, so the wording becomes EVIDENCE and the question asks them to name it."""
    # LegacyAgent/UseCase: a pair the seed does NOT relate, so the question stays open to be inspected.
    out = fab.vocab_relation_propose(scheme="cafe", subject="LegacyAgent", predicate="is realised by",
                                     object="UseCase", evidence="drawn on the context diagram")
    row = next(r for r in fab.vocab_relation_open() if r["iri"] == out["iri"])
    assert row["predicate"] == "", "prose is not a predicate"
    assert "is realised by" in row["evidence"], "...but the author's wording is not lost"


def test_propose_REFUSES_a_question_nobody_could_answer(fab):
    """The queue that feeds `vocab_relate` must validate what `vocab_relate` validates. A blank scheme
    reaches here from a misconfigured workload (`cfg.get("vocabulary", "")`), and a concept the scheme
    does not hold parks a question whose only possible answer raises."""
    with pytest.raises(LookupError, match="vocabulary"):
        fab.vocab_relation_propose(scheme="", subject="AIAgent", predicate="x", object="UseCase")
    with pytest.raises(ValueError, match="Nope"):
        fab.vocab_relation_propose(scheme="cafe", subject="Nope", predicate="x", object="UseCase")


def test_an_UNNAMED_question_is_settled_by_a_relation_in_EITHER_direction(fab):
    """The two readers must agree. `concept_pairs` treats a pair as unordered — it cannot know which way
    round a relation runs — so a question it proposed must leave the queue when the vocabulary states one
    either way. A NAMED question stays directional, because `A contains B` and `B contains A` are
    different claims and only one of them was asked."""
    fab.vocab_relation_propose(scheme="cafe", subject="LegacyAgent", predicate="", object="AIAgent")
    fab.vocab_relate(scheme="cafe", subject="AIAgent", predicate="supersedes", object="LegacyAgent",
                     actor="s@x")
    assert fab.vocab_relation_open() == [], "the vocabulary has answered it, whichever way round"


def test_CONCEPT_PAIRS_works_on_a_vocabulary_that_states_NOTHING_yet(fab):
    """The bootstrap case, and the one this producer exists for: a vocabulary whose relation half is
    empty is exactly where a steward needs the corpus's help. Filtering the schemes by whether they
    ALREADY state a relation excluded the only vocabulary that needed asking about."""
    bare = build(name="bare", title="Bare", concepts=[{"id": "X", "name": "Ex"}, {"id": "Y", "name": "Why"}])
    fab._schemes = lambda: {"bare": bare}
    for n in range(3):
        doc = _doc(fab, f"pair-{n}")
        for cid in ("X", "Y"):
            fab.graph_assert(doc, str(G.DCT.subject), str(bare.uri(cid)), rung="X", method="m")
    assert [(p["subject"], p["object"]) for p in fab.concept_pairs(min_records=2)] == [("X", "Y")]
