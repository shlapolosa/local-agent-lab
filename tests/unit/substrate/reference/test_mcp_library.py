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
