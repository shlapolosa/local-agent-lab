"""The reference vocabulary's own invariants — the ones the types enforce so nothing else has to."""
import pytest

from lab.core.reference.errors import (
    ArtifactUnverified,
    IndexUnavailable,
    ReferenceError,
    ReferenceUnavailable,
)
from lab.core.reference.model import (
    ArtifactHead,
    ArtifactKind,
    ArtifactVersion,
    Consumption,
    Pin,
    RunRef,
)


def version(**kw):
    base = dict(artifact_id="guardrails", version="2026.09.1", kind=ArtifactKind.RECORD,
                title="Guardrail set", master_ref="art://abc/guardrails.md",
                master_sha256="a" * 64, agent_sha256="b" * 64, derived_from="a" * 64,
                signature_id="k1", signed_at="2026-09-08T00:00:00Z", ring=0,
                published_at="2026-09-08T00:00:00Z")
    return ArtifactVersion(**(base | kw))


# ---------------------------------------------------------------- DR-02 as a type invariant

def test_a_version_cannot_claim_a_master_it_was_not_derived_from():
    with pytest.raises(ValueError) as e:
        version(derived_from="z" * 64)
    assert "derived" in str(e.value).lower()


def test_a_record_artifact_declares_a_record_type_and_a_prose_one_does_not():
    ArtifactHead("guardrails", ArtifactKind.RECORD, "Guardrails", "Agent Council", "v1",
                 record_type="guardrail")
    ArtifactHead("tradeoffs", ArtifactKind.PROSE, "Tradeoffs", "Architecture Board", "v1")
    with pytest.raises(ValueError):
        ArtifactHead("guardrails", ArtifactKind.RECORD, "G", "owner", "v1")
    with pytest.raises(ValueError):
        ArtifactHead("tradeoffs", ArtifactKind.PROSE, "T", "owner", "v1", record_type="oops")


# ---------------------------------------------------------------- the pin

def test_a_pin_resolves_an_artifact_to_exactly_one_version():
    pin = Pin("pin-1", 0, "t", "t+1", versions=(version(),))
    assert pin.version_of("guardrails").version == "2026.09.1"


def test_asking_a_pin_for_something_it_does_not_hold_refuses_and_says_what_it_has():
    pin = Pin("pin-1", 0, "t", "t+1", versions=(version(),))
    with pytest.raises(KeyError) as e:
        pin.version_of("price-sheet")
    assert "guardrails" in str(e.value)


# ---------------------------------------------------------------- attribution

@pytest.mark.parametrize("blank", ["run_id", "process", "field"])
def test_a_read_that_names_no_derived_field_is_refused(blank):
    """FR-44: every derived field records the versions it consulted. An unattributed read cannot,
    so it is not allowed to happen."""
    kwargs = dict(run_id="r", process="p", field="f") | {blank: "  "}
    with pytest.raises(ValueError):
        RunRef(**kwargs)


def test_a_consumption_row_defaults_to_a_hit_with_no_extra():
    row = Consumption(run_id="r", process="p", field="criticality", artifact_id="a",
                      version="v1", mode="lookup", consulted_at="t")
    assert row.hit is True
    assert row.extra == {}


# ---------------------------------------------------------------- the refusals

def test_every_refusal_renders_one_sentence_saying_what_and_why():
    for error in (ReferenceUnavailable("price-sheet", 2),
                  IndexUnavailable("tradeoffs", "v1", "the index is incomplete"),
                  ArtifactUnverified("guardrails", "v1", "signature does not verify")):
        assert isinstance(error, ReferenceError)
        assert error.sentence.endswith(".")
        assert error.to_dict()["sentence"]


def test_an_unavailable_artifact_says_which_ring_has_no_release():
    assert "ring 2" in ReferenceUnavailable("price-sheet", 2).sentence


def test_an_unavailable_index_refuses_rather_than_ranking_what_it_has():
    error = IndexUnavailable("tradeoffs", "v1", "embedded with a different model")
    assert "worse than none" in error.sentence


# ---------------------------------------------------------------- retrieval mode is data

def test_retrieval_mode_is_declared_per_artifact_and_defaults_to_exact():
    """`whole` / `key` / `vector` is a property of the ARTIFACT, not something a caller infers from
    its size. A caller that guessed would vector-search a nine-row register and silently drop the
    rule it needed."""
    from lab.core.reference.model import ArtifactHead, ArtifactKind, Retrieval
    head = ArtifactHead(artifact_id="facet-schema", kind=ArtifactKind.RECORD, title="Facets",
                        owner="x", version="v1", record_type="facet")
    assert head.retrieval is Retrieval.KEY
    assert {str(m) for m in Retrieval} == {"whole", "key", "vector"}
    prose = ArtifactHead(artifact_id="tradeoffs", kind=ArtifactKind.PROSE, title="T", owner="x",
                         version="v1")
    assert prose.retrieval is Retrieval.VECTOR, "an undeclared mode follows the kind"


def test_a_prose_artifact_can_only_be_retrieved_semantically():
    """Prose has no natural key to look up by, so declaring it `key` or `whole` would promise a
    read the corpus cannot answer."""
    from lab.core.reference.model import ArtifactHead, ArtifactKind, Retrieval
    with pytest.raises(ValueError) as e:
        ArtifactHead(artifact_id="tradeoffs", kind=ArtifactKind.PROSE, title="T", owner="x",
                     version="v1", retrieval=Retrieval.KEY)
    assert "prose" in str(e.value)
    assert ArtifactHead(artifact_id="tradeoffs", kind=ArtifactKind.PROSE, title="T", owner="x",
                        version="v1", retrieval=Retrieval.VECTOR).retrieval is Retrieval.VECTOR


def test_a_record_artifact_may_also_be_searched_when_it_says_so():
    """A 1,600-row capability map is a record artifact (exact reads by parent and level) AND a
    vector one (relevance over the leaves). Both, declared — not one inferred from the other."""
    from lab.core.reference.model import ArtifactHead, ArtifactKind, Retrieval
    head = ArtifactHead(artifact_id="capability-map", kind=ArtifactKind.RECORD, title="Map",
                        owner="x", version="v1", record_type="capability",
                        retrieval=Retrieval.VECTOR)
    assert head.retrieval is Retrieval.VECTOR


def test_a_passage_can_name_the_record_it_was_derived_from():
    """A semantic hit over a record artifact resolves to its exact row, so a caller can follow a
    relevance result with an exact read rather than trusting the passage text."""
    from lab.core.reference.model import Citation, Passage
    citation = Citation(artifact_id="m", title="M", version="v1", signature_id="k1",
                        locator="psg-1", master_ref="art://m/master.md")
    passage = Passage(passage_id="psg-1", text="t", score=0.9, heading_path=(),
                      citation=citation, record_id="rec-1", key={"id": "L3.1"})
    assert passage.record_id == "rec-1" and passage.key == {"id": "L3.1"}
    assert Passage(passage_id="p", text="t", score=0.1, heading_path=(),
                   citation=citation).record_id == ""


# ---------------------------------------------------------------- the pin decides what is searched

def _pin_with(*modes):
    from lab.core.reference.model import Pin, Retrieval
    versions = tuple(version(artifact_id=f"a{i}", retrieval=Retrieval(m))
                     for i, m in enumerate(modes))
    return Pin(pin_id="pin-1", ring=0, pinned_at="t", expires_at="t", versions=versions)


def test_a_whole_pin_search_covers_the_vector_artifacts_and_skips_the_exact_ones():
    assert _pin_with("key", "vector", "whole", "vector").searchable() == ["a1", "a3"]


def test_naming_an_exact_artifact_is_refused_and_points_at_lookup():
    from lab.core.reference.errors import NotSearchable
    with pytest.raises(NotSearchable) as e:
        _pin_with("key", "vector").searchable(["a0"])
    assert "reference_lookup" in str(e.value) and "key" in str(e.value)


def test_naming_an_unpinned_artifact_is_refused_rather_than_read_around_the_pin():
    from lab.core.reference.errors import NotPinned
    with pytest.raises(NotPinned) as e:
        _pin_with("vector").searchable(["nope"])
    assert "pin-1" in str(e.value) and "['a0']" in str(e.value)


def test_a_pin_with_nothing_searchable_refuses_rather_than_answering_nothing():
    from lab.core.reference.errors import IndexUnavailable
    with pytest.raises(IndexUnavailable):
        _pin_with("key", "whole").searchable()
