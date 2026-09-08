"""Replicas — how four lanes stop queueing behind each other.

A Redis Streams consumer group hands each entry to exactly ONE consumer, so N replicas of a workload
process N lanes in parallel with no locking, no threads and no change to the workflow. That is also
the Azure-faithful shape: Container Apps scales replicas, it does not thread inside one container.
The alternative — `asyncio.gather` inside one process — would concentrate four concurrent audio
extractions and four recordings in the one container least able to hold them.

This only works if each replica has its OWN name in the group. Two consumers sharing a name share a
pending list, and XAUTOCLAIM can no longer tell whose in-flight work is whose.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))

import railway                                                          # noqa: E402

FAKE = {"REDIS_URL": "redis://r:6379/0", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel:4318",
        "GATEWAY_URL": "https://gw", "REVIEW_APP_URL": "https://rv", "JAEGER_UI_URL": "https://j",
        "ENTRA_TENANT_ID": "t", "ENTRA_GATEWAY_AUDIENCE": "api://x", "SPEECH_LANES": "a,b"}


def test_a_workload_without_replicas_is_exactly_one_service_named_as_before():
    """Every existing workload keeps its service name. A rename would orphan the deployed service,
    its variables and its logs — and `substrate images` would then report a mismatch against a
    service nobody is running any more."""
    for name, spec in railway.WORKLOADS.items():
        if not spec.get("replicas"):
            assert railway.replica_services(spec) == [(spec["service"], "1")], name


def test_replicas_are_distinct_services_each_with_its_own_consumer_name():
    """The FIRST replica keeps the plain service name, so turning replicas on does not rename,
    orphan or redeploy the service that is already running."""
    got = railway.replica_services({"service": "wf-meeting-transcript", "replicas": 3})
    assert got == [("wf-meeting-transcript", "1"),
                   ("wf-meeting-transcript-2", "2"),
                   ("wf-meeting-transcript-3", "3")]
    assert len({c for _s, c in got}) == 3, "two replicas sharing a name share a pending list"


def test_each_replica_receives_its_own_consumer_name_in_its_env():
    """The name must reach the CONTAINER, not just the service list: `consumer_name()` reads
    WF_CONSUMER, and the spec-level default of "1" would otherwise win for every replica — which is
    precisely the shared-pending-list failure, arrived at by a different route."""
    spec = {**railway.WORKLOADS["meeting"], "replicas": 2}
    envs = [railway.workload_env("meeting", spec, dict(FAKE), "https://gw", consumer=c)
            for _s, c in railway.replica_services(spec)]
    assert [e["WF_CONSUMER"] for e in envs] == ["1", "2"]
    # ...and nothing else differs. Replicas are the same workload run twice, not two configurations.
    assert {k: v for k, v in envs[0].items() if k != "WF_CONSUMER"} == \
           {k: v for k, v in envs[1].items() if k != "WF_CONSUMER"}


def test_replica_count_is_bounded_by_something_a_person_chose():
    """A typo in a config file must not deploy fifty services. The cap is deliberately low: this is
    a lab, the point is to overlap a handful of lanes, and every replica is a metered container."""
    import pytest
    with pytest.raises(ValueError, match="replicas"):
        railway.replica_services({"service": "wf-x", "replicas": 99})
    with pytest.raises(ValueError, match="replicas"):
        railway.replica_services({"service": "wf-x", "replicas": 0})
