"""The two fabric hosts are composition roots: what each alone decides — its service name, the identity it
authenticates as, what it injects into the graph, what reaches a span and the board."""
import asyncio
import os

import pytest

from fixtures.fakes import FakeRedis
from fixtures.host import make_root
from lab.platform import config
from lab.platform.contracts import PROCESSES
from lab.workloads.artifact_intake import host as intake
from lab.workloads.artifact_publish import host as publish

POINTER = {"source": "lab", "ref": "art://r/minutes.json"}


@pytest.fixture(autouse=True)
def _static_credentials():
    for prefix in ("CLASSIFIER_AGENT", "SYNTHESIS_AGENT", "PUBLISH_AGENT"):
        os.environ.pop(f"{prefix}_CLIENT_ID", None); os.environ.pop(f"{prefix}_CLIENT_SECRET", None)
        os.environ[f"{prefix}_KEY"] = f"sk-{prefix.lower()}"


def test_each_host_has_its_own_service_name_process_and_identity():
    assert intake.SERVICE != publish.SERVICE and intake.SERVICE.startswith("process-")
    assert intake.PROCESS in PROCESSES and publish.PROCESS in PROCESSES
    assert publish.AGENT_PREFIX == "PUBLISH_AGENT" and publish._cred() == "sk-publish_agent"
    assert intake._cred(intake.CLASSIFIER_PREFIX) == "sk-classifier_agent"


def test_the_intake_host_injects_two_agents_the_schemas_and_the_settings(monkeypatch):
    seen = []

    async def run_workflow(cfg, inputs):
        seen.append((cfg, inputs)); return {"artifact_iri": "urn:fabric:artifact:x", "approval_id": "apr-1", "kind": "draft-review"}
    monkeypatch.setattr(intake, "run_workflow", run_workflow)
    monkeypatch.setattr(config, "FABRIC_ASSOCIATION_THRESHOLD", 0.6)
    monkeypatch.setattr(config, "FABRIC_DEFAULT_LABEL", "Internal")
    out = asyncio.run(intake.run_once(make_root(intake.SERVICE, redis=FakeRedis()), POINTER, "01J",
                                      context="meeting:AAMk1", produced_by="transcript_to_minutes", requester="a@x"))
    cfg, inputs = seen[0]
    assert set(cfg["agents"]) == {"classifier", "synthesis"} and set(cfg["schemas"]) == {"classifier", "synthesis"}
    assert cfg["agents"]["classifier"].name == "fabric-classifier" and cfg["agents"]["synthesis"].name == "fabric-synthesis"
    assert cfg["credential"] == "sk-classifier_agent" and cfg["threshold"] == 0.6 and cfg["default_label"] == "Internal"
    assert "urn:fabric:scheme:doc-types#minutes" in cfg["doc_types"]
    assert inputs == {"pointer": POINTER, "event_id": "01J", "context": "meeting:AAMk1",
                      "produced_by": "transcript_to_minutes", "requester": "a@x"}
    assert out["trace_id"] and intake.run_fields(out) == {"artifact_iri": "urn:fabric:artifact:x", "approval_id": "apr-1"}


def test_the_publish_host_runs_with_its_own_credential_and_no_agent(monkeypatch):
    seen = []

    async def run_workflow(cfg, inputs):
        seen.append((cfg, inputs)); return {"artifact_iri": "urn:fabric:artifact:x", "baseline": {"version": "1"}}
    monkeypatch.setattr(publish, "run_workflow", run_workflow)
    out = asyncio.run(publish.run_once(make_root(publish.SERVICE, redis=FakeRedis()), "urn:fabric:artifact:x", "apr-0123456789ab"))
    cfg, inputs = seen[0]
    assert cfg["credential"] == "sk-publish_agent" and "agents" not in cfg
    assert inputs == {"artifact_iri": "urn:fabric:artifact:x", "approval_id": "apr-0123456789ab"}
    assert out["trace_id"] and publish.run_fields(out)["baseline"] == {"version": "1"}


def test_the_board_label_names_the_item_never_a_person():
    assert intake._label({"source": "collab", "handle": "collab://item/d/doc7"}) == "intake doc7"
    assert intake._label({}) == "intake ?"
