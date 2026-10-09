"""The intake's consumer forwards every input the contract declares; its agents compose the registered skill
with the schema the gate holds them to."""
import asyncio
from types import SimpleNamespace

import pytest

from lab.platform.contracts import ARTIFACT_INTAKE, PROCESSES
from lab.workloads.artifact_intake import agents as A
from lab.workloads.artifact_intake import consumer, host

INPUTS = {"pointer": {"source": "lab", "ref": "art://r/minutes.json"}, "event_id": "01J",
          "context": "meeting:AAMk1", "produced_by": "transcript_to_minutes", "reason": "reclassify"}


def test_it_is_registered_continuation_only_and_gets_its_own_group():
    assert consumer.PROCESS in PROCESSES and PROCESSES[consumer.PROCESS].group == "wf-fabric"
    assert ARTIFACT_INTAKE.external is False


def test_every_input_the_contract_declares_reaches_the_run():
    seen = {}

    async def fake_run_once(root, pointer, event_id, *, context="", produced_by="", requester="", reason="", on_trace=None):
        seen.update(pointer=pointer, event_id=event_id, context=context, produced_by=produced_by,
                    reason=reason)
        seen["requester"] = requester
        return {"artifact_iri": "urn:fabric:artifact:x"}

    saved, consumer.run_once = consumer.run_once, fake_run_once
    try:
        out = asyncio.run(consumer._run(object(), SimpleNamespace(inputs=INPUTS, requester="a@x.org"), on_trace=None))
    finally:
        consumer.run_once = saved
    assert {k: seen[k] for k in INPUTS} == INPUTS and seen["requester"] == "a@x.org"
    assert set(INPUTS) == {f.name for f in ARTIFACT_INTAKE.inputs}, "a new input the consumer never forwards is dead"
    assert out == {"artifact_iri": "urn:fabric:artifact:x"}


def test_the_log_line_names_ids_never_a_person():
    line = consumer._describe(SimpleNamespace(inputs=INPUTS, requester="a@x.org"))
    assert "01J" in line and "art://r/minutes.json" in line and "a@x.org" not in line
    assert host._label(INPUTS["pointer"]) == "intake minutes.json" and host.run_fields({"artifact_iri": "u", "approval_id": "a"}) == {
        "artifact_iri": "u", "approval_id": "a"}


def test_agents_compose_the_skill_and_the_schema():
    for kind in ("classifier", "synthesis"):
        text = A.instructions(kind, A.schema(kind))
        assert "## The schema" in text and '"$schema"' in text and not text.lstrip().startswith("---")
    assert "document_type" in A.schema("classifier")["properties"]
    assert A.schema("synthesis")["properties"]["records"]["items"]["required"][0] == "id"
    with pytest.raises(ValueError):
        A.make_agent("oracle", credential="k", gateway_url="http://gw", model="m")
    agent = A.make_agent("classifier", credential="k", gateway_url="http://gw", model="m", headers={"traceparent": "00-x"})
    assert agent.name == "fabric-classifier"


def test_classification_is_SAMPLED_AT_ZERO_because_it_is_a_judgement_not_a_draft():
    """No temperature was set, so the provider default (~1) applied and the pipeline SAMPLED.

    Measured 9 Oct 2026 on one unchanged record: the same minutes came back `Person, Location` on one run
    and `Party, Person, Location, Location` on the next, while the identical brief at temperature 0
    returned no subjects at all, consistently. Reading a definition and deciding whether it applies has no
    creative latitude worth sampling for — the variance was pure noise, and it was about to be averaged
    away with a three-run ensemble that would have cost three sweeps to hide a one-line cause.
    """
    for kind in ("classifier", "synthesis"):
        agent = A.make_agent(kind, credential="k", gateway_url="http://gw", model="m")
        assert agent.default_options["temperature"] == 0, f"{kind} must not sample"
