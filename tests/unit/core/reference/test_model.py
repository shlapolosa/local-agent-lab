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
