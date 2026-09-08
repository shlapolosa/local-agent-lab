"""reference-mcp — the governed corpus as tools.

Two things are being checked. That the tools map the port faithfully, including the shapes a caller
depends on (`near` separate from `records`, citations carrying the human-readable master). And that
a refusal reaches the caller as a SENTENCE rather than a stack trace, because a tool that fails
opaquely gets retried, and a retried "the index is stale" is a loop.
"""
import pytest
from fastmcp.exceptions import ToolError

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from lab.core.reference.model import ArtifactKind
from lab.platform.contracts import ReferenceTools
from lab.substrate.mcp.reference import server as S


def mapping():
    return SeededArtifact(
        artifact_id="guardrail-mapping", kind=ArtifactKind.RECORD, title="Risk class mapping",
        record_type="risk-class", records=[
            {"record_id": "rec-e2", "risk_class": "E2", "mandatory": "G09, G17"}])


def prose():
    return SeededArtifact(
        artifact_id="tradeoff-catalogue", kind=ArtifactKind.PROSE, title="Tradeoff catalogue",
        passages=[{"passage_id": "psg-1", "heading_path": ["Tradeoffs", "G23"],
                   "text": "idempotency key plus a compensating action"}])


@pytest.fixture
def library():
    fake = FakeReferenceLibrary([mapping(), prose()])
    with S.server.container.reference.override(fake):
        yield fake


ATTRIBUTION = dict(run_id="wfr-1", process="use_case_screening", field="criticality_class")


# ---------------------------------------------------------------- the contract

def test_the_server_registers_exactly_the_catalogue_it_declares():
    import asyncio
    import inspect
    tools = S.server.mcp.list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    registered = {t.name for t in (tools.values() if isinstance(tools, dict) else tools)}
    assert registered == ReferenceTools.names()


def test_the_catalogue_declares_no_write_tool():
    """Publication is an operator CLI. There is no tool a workload could be granted that mutates
    the corpus, so there is nothing to split READ from."""
    assert not hasattr(ReferenceTools, "WRITE")


# ---------------------------------------------------------------- the tools

def test_catalogue_lists_what_this_ring_may_consult(library):
    out = S.reference_catalogue()
    assert {a["artifact_id"] for a in out["artifacts"]} == {"guardrail-mapping",
                                                            "tradeoff-catalogue"}


def test_pin_returns_an_opaque_id_and_the_versions_it_froze(library):
    out = S.reference_pin()
    assert out["pin_id"]
    assert {v["artifact_id"] for v in out["versions"]} == {"guardrail-mapping",
                                                           "tradeoff-catalogue"}


def test_a_read_without_a_pin_refuses_and_says_what_to_do(library):
    with pytest.raises(ToolError) as e:
        S.reference_lookup(pin_id="", record_type="risk-class", key={}, **ATTRIBUTION)
    assert "reference_pin" in str(e.value)


def test_lookup_returns_records_with_citations(library):
    pin = S.reference_pin()["pin_id"]
    out = S.reference_lookup(pin_id=pin, record_type="risk-class",
                             key={"risk_class": "E2"}, **ATTRIBUTION)
    assert out["matched"] == 1
    assert out["records"][0]["body"]["mandatory"] == "G09, G17"
    assert out["citations"][0]["master_ref"].startswith("art://")


def test_a_near_miss_is_returned_apart_from_the_records(library):
    """A caller iterating `records` must never reach something that only nearly matched."""
    pin = S.reference_pin()["pin_id"]
    out = S.reference_lookup(pin_id=pin, record_type="risk-class",
                             key={"risk_class": "E2", "mandatory": "different"}, **ATTRIBUTION)
    assert out["records"] == []
    assert out["near"]


def test_search_returns_passages_and_their_anchors(library):
    pin = S.reference_pin()["pin_id"]
    out = S.reference_search(pin_id=pin, question="compensating action", **ATTRIBUTION)
    assert out["passages"]
    assert out["citations"][0]["anchor"] == "Tradeoffs > G23"


def test_a_stale_index_refuses_as_a_sentence_not_a_traceback(library):
    library.artifacts["tradeoff-catalogue"].indexed = False
    pin = S.reference_pin()["pin_id"]
    with pytest.raises(ToolError) as e:
        S.reference_search(pin_id=pin, question="anything", **ATTRIBUTION)
    assert "Remedy:" in str(e.value)


def test_search_is_capped_so_a_caller_cannot_ask_for_the_whole_corpus(library):
    pin = S.reference_pin()["pin_id"]
    S.reference_search(pin_id=pin, question="action", k=500, **ATTRIBUTION)   # does not raise


def test_a_record_can_be_reopened_by_the_locator_a_citation_carries(library):
    pin = S.reference_pin()["pin_id"]
    locator = S.reference_lookup(pin_id=pin, record_type="risk-class",
                                 key={"risk_class": "E2"}, **ATTRIBUTION)["citations"][0]["locator"]
    out = S.reference_record(pin_id=pin, artifact_id="guardrail-mapping", record_id=locator,
                             **ATTRIBUTION)
    assert out["record"]["body"]["mandatory"] == "G09, G17"


def test_consumers_answers_the_blast_radius_of_a_version(library):
    pin = S.reference_pin()
    S.reference_lookup(pin_id=pin["pin_id"], record_type="risk-class",
                       key={"risk_class": "E2"}, **ATTRIBUTION)
    out = S.reference_consumers(artifact_id="guardrail-mapping",
                                version=pin["versions"][0]["version"])
    assert out["runs"] == 1
    assert out["consumers"][0]["field"] == "criticality_class"


# ---------------------------------------------------------------- attribution is required

@pytest.mark.parametrize("blank", ["run_id", "process", "field"])
def test_a_read_that_names_no_derived_field_refuses(library, blank):
    """FR-44 is enforced by making the attribution an ARGUMENT: there is no 'report your sources
    afterwards' step for a run to forget, because the read does not happen without it."""
    pin = S.reference_pin()["pin_id"]
    with pytest.raises(ToolError):
        S.reference_lookup(pin_id=pin, record_type="risk-class", key={},
                           **{**ATTRIBUTION, blank: "  "})


# ---------------------------------------------------------------- spans carry no content

def test_no_span_attribute_carries_an_artifact_s_text_or_a_caller_s_words(library, monkeypatch):
    """A span reaches a collector this lab does not authenticate, so counts and ids only — never
    what an artifact SAYS and never what a caller asked."""
    recorded: dict = {}

    class Span:
        def set_attribute(self, key, value): recorded[key] = value

    monkeypatch.setattr(S, "span", lambda: Span())
    pin = S.reference_pin()["pin_id"]
    S.reference_lookup(pin_id=pin, record_type="risk-class",
                       key={"risk_class": "E2"}, **ATTRIBUTION)
    S.reference_search(pin_id=pin, question="a secret phrase about compensating action",
                       **ATTRIBUTION)
    S.reference_catalogue()

    assert recorded, "the tools record nothing at all, so this test would pass vacuously"
    for key, value in recorded.items():
        assert isinstance(value, (int, float, bool)), f"{key} is not a count/shape: {value!r}"
        assert "secret" not in str(value), f"{key} leaked the caller's question"
    # The rule is about an art:// REF or a file NAME as a value — not the "reference." prefix every
    # key here legitimately carries, which a substring check would flag forever.
    assert not any(k.endswith(("_ref", "_name", ".ref", ".name")) for k in recorded), recorded
