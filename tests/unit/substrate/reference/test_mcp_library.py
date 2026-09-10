"""The reference port over reference-mcp's tools — the adapter a server with no DSN runs.

What matters is that it is the SAME port: a pin is whole (rehydrated from the server, never
claimed), a lookup maps to the same records and citations, and a remote refusal reaches the
caller as the sentence the server rendered, under the base type every caller already catches.
"""
import pytest

from lab.core.reference.errors import ReferenceError
from lab.core.reference.model import RunRef
from lab.core.reference.port import ReferenceLibrary
from lab.platform.contracts import ReferenceTools
from lab.substrate.reference.mcp_library import McpReferenceLibrary

RUN = RunRef(run_id="wfr-1", process="use_case_design", field="obligations")
VERSION = {"artifact_id": "guardrails", "version": "v0.27", "kind": "record", "title": "Guardrails",
           "master_ref": "art://m/g.md", "master_sha256": "a" * 64, "agent_sha256": "b" * 64,
           "derived_from": "a" * 64, "signature_id": "k1", "signed_at": "t", "ring": 0,
           "published_at": "t", "retrieval": "key"}


def library(answers: dict):
    calls = []

    def call(tool, args):
        calls.append((tool, args))
        answer = answers[tool]
        if isinstance(answer, Exception):
            raise answer
        return answer(args) if callable(answer) else answer
    lib = McpReferenceLibrary(url="http://ref/mcp", secret="shh", ring=0, call=call)
    lib.calls = calls
    return lib


def test_the_adapter_satisfies_the_port():
    assert isinstance(library({}), ReferenceLibrary)


def test_a_pin_is_taken_then_rehydrated_whole_from_the_server():
    """The versions are the SERVER's record: the take answers an id, and the id is read back."""
    lib = library({ReferenceTools.pin: {"pin_id": "pin-9", "versions": [{"artifact_id": "guardrails"}]},
                   ReferenceTools.pin_info: {"pin_id": "pin-9", "ring": 0, "pinned_at": "t",
                                             "expires_at": "t", "versions": [VERSION]}})
    pin = lib.pin(["guardrails"])
    assert [t for t, _ in lib.calls] == [ReferenceTools.pin, ReferenceTools.pin_info]
    assert pin.pin_id == "pin-9" and pin.version_of("guardrails").retrieval.value == "key"
    assert pin.version_of("guardrails").title == "Guardrails"


def test_a_lookup_carries_the_pin_and_the_attribution_and_maps_records_with_citations():
    lib = library({ReferenceTools.pin_info: {"pin_id": "pin-9", "ring": 0, "pinned_at": "t",
                                             "expires_at": "t", "versions": [VERSION]},
                   ReferenceTools.lookup: {"records": [{"record_id": "rec-1", "key": {"id": "G01"},
                                                        "body": {"id": "G01", "rule": "r"},
                                                        "artifact_id": "guardrails", "version": "v0.27"}],
                                           "citations": [{"artifact_id": "guardrails", "title": "Guardrails",
                                                          "version": "v0.27", "signature_id": "k1",
                                                          "locator": "rec-1", "master_ref": "art://m/g.md",
                                                          "anchor": ""}],
                                           "matched": 1, "near": []}})
    pin = lib.pin_by_id("pin-9")
    out = lib.lookup(pin, record_type="guardrail", key={"id": "G01"}, run=RUN, artifact_id="guardrails")
    sent = lib.calls[-1][1]
    assert sent["pin_id"] == "pin-9" and sent["field"] == "obligations" and sent["artifact_id"] == "guardrails"
    assert out.matched == 1 and out.records[0].body["rule"] == "r"
    assert out.records[0].citation.master_ref == "art://m/g.md"


def test_a_remote_refusal_reaches_the_caller_as_the_server_s_sentence():
    lib = library({ReferenceTools.pin_info: ReferenceError("pin pin-9 has expired. Remedy: re-pin.")})
    with pytest.raises(ReferenceError) as e:
        lib.pin_by_id("pin-9")
    assert "Remedy" in e.value.sentence


def test_the_registry_offers_the_adapter_by_name_and_it_ignores_an_embedder():
    from lab.substrate import container
    from lab.substrate.reference import mcp_library
    assert container.REFERENCE_PROVIDERS["mcp"].endswith("mcp_library")
    lib = mcp_library.build(url="http://ref/mcp", secret="s", ring=1, embedder=object())
    assert isinstance(lib, McpReferenceLibrary) and lib.ring == 1


PIN_INFO = {"pin_id": "pin-9", "ring": 0, "pinned_at": "t", "expires_at": "t", "versions": [VERSION]}
CATALOGUE = {"ring": 0, "artifacts": [{"artifact_id": "guardrails", "kind": "record",
                                        "record_type": "guardrail", "title": "Guardrails",
                                        "owner": "governance", "version": "v0.27", "retrieval": "key"}]}


def test_a_record_reopened_by_id_carries_the_artifact_s_record_type_from_the_catalogue():
    lib = library({ReferenceTools.pin_info: PIN_INFO, ReferenceTools.catalogue: CATALOGUE,
                   ReferenceTools.record: {"record": {"record_id": "rec-1", "key": {"id": "G01"},
                                                      "body": {"id": "G01"}},
                                           "citation": {"artifact_id": "guardrails", "title": "Guardrails",
                                                        "version": "v0.27", "signature_id": "k1",
                                                        "locator": "rec-1", "master_ref": "art://m/g.md"}}})
    pin = lib.pin_by_id("pin-9")
    found = lib.record(pin, artifact_id="guardrails", record_id="rec-1", run=RUN)
    assert found.record_type == "guardrail" and found.citation.master_ref == "art://m/g.md"


def test_reopening_a_record_of_an_unpinned_artifact_is_a_typed_refusal():
    from lab.core.reference.errors import NotPinned
    lib = library({ReferenceTools.pin_info: PIN_INFO})
    with pytest.raises(NotPinned):
        lib.record(lib.pin_by_id("pin-9"), artifact_id="nope", record_id="r", run=RUN)


def test_a_search_maps_passages_with_their_record_ids_and_keys():
    lib = library({ReferenceTools.pin_info: PIN_INFO,
                   ReferenceTools.search: {"passages": [{"passage_id": "psg-1", "text": "A > B. def",
                                                         "score": 0.9, "heading_path": ["id=x"],
                                                         "artifact_id": "capability-map", "version": "v0.27",
                                                         "record_id": "rec-x", "key": {"id": "x"}}],
                                           "citations": []}})
    out = lib.search(lib.pin_by_id("pin-9"), question="triage", run=RUN, artifact_ids=["capability-map"])
    sent = lib.calls[-1][1]
    assert sent["artifact_ids"] == ["capability-map"] and sent["field"] == "obligations"
    assert out.passages[0].record_id == "rec-x" and out.passages[0].key == {"id": "x"}


def test_an_empty_catalogue_refuses_as_the_port_requires():
    with pytest.raises(ReferenceError):
        library({ReferenceTools.catalogue: {"ring": 0, "artifacts": []}}).catalogue()


def test_the_reverse_index_maps_consumers():
    lib = library({ReferenceTools.consumers: {"consumers": [{"run_id": "r", "process": "p", "field": "f",
                                                            "mode": "lookup", "locator": "", "hit": True,
                                                            "consulted_at": "t"}], "runs": 1}})
    rows = lib.consumers(artifact_id="guardrails", version="v0.27")
    assert rows[0].run_id == "r" and rows[0].artifact_id == "guardrails"


def test_a_transport_failure_is_a_typed_unreachable_naming_the_server(monkeypatch):
    """A socket error must not escape as itself past a caller's `except ReferenceError`."""
    from lab.core.reference.errors import ReferenceUnavailable
    from lab.substrate.reference.mcp_library import _remote_call
    import fastmcp.client.transports as T

    class Broken:
        def __init__(self, *a, **k):
            raise ConnectionError("refused")
    monkeypatch.setattr(T, "StreamableHttpTransport", Broken)
    call = _remote_call("http://ref:9700/mcp", {})
    with pytest.raises(ReferenceUnavailable) as e:
        call(ReferenceTools.catalogue, {})
    assert "http://ref:9700/mcp" in str(e.value) and "ConnectionError" in str(e.value)
