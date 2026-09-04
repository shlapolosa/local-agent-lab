"""The process registry (lab.platform.contracts.PROCESSES) is the ONE source of a process's identity.

Before this, "wf-visio" was written out in five places (workflows.GROUPS, the consumer, the registry,
deploy, docs) and `workflows.request()` accepted any dict, so the review app, the CLI and workflow-mcp
each validated inputs differently — or not at all. Offline: FakeRedis only.
"""
import pytest

from fixtures.fakes import FakeRedis
from lab.platform import contracts, workflows
from lab.platform.contracts import PROCESSES


def test_consumer_groups_are_derived_from_the_registry():
    """Adding a ProcessSpec must not require a second edit in workflows.py."""
    assert workflows.GROUPS == tuple(s.group for s in PROCESSES.values())
    assert "wf-visio" in workflows.GROUPS


def test_the_consumer_takes_its_identity_from_the_registry():
    from lab.workloads.visio_to_archimate import consumer
    spec = PROCESSES[consumer.PROCESS]
    assert consumer.GROUP == spec.group and consumer.SPEC is spec


def test_request_validates_through_the_process_spec():
    """One validator for every producer: workflow-mcp, the review app's Submit and the CLI."""
    r = FakeRedis()
    rid = workflows.request("visio_to_archimate", {"diagram": "art://a/b.vsdx"}, "tester", client=r)
    assert rid.startswith("wfr-")
    stored = workflows.status(rid, client=r)
    assert stored["inputs"] == {"diagram": "art://a/b.vsdx", "requirements": []}   # normalised by the spec

    with pytest.raises(ValueError, match="not an art:// reference"):
        workflows.request("visio_to_archimate", {"diagram": "http://evil/x.vsdx"}, "tester", client=r)
    with pytest.raises(ValueError, match="unknown input"):
        workflows.request("visio_to_archimate", {"diagram": "art://a/b", "nope": 1}, "tester", client=r)
    with pytest.raises(ValueError, match="unknown process"):
        workflows.request("no_such_process", {"diagram": "art://a/b"}, "tester", client=r)


def test_a_new_process_needs_only_a_registry_entry(monkeypatch):
    spec = contracts.ProcessSpec(
        name="probe_process", group="wf-probe", title="Probe", description="test only",
        inputs=(contracts.InputField("thing", contracts.InputKind.REF, "a thing"),), outputs=("out",))
    monkeypatch.setitem(PROCESSES, "probe_process", spec)
    monkeypatch.setattr(workflows, "GROUPS", tuple(s.group for s in PROCESSES.values()))
    r = FakeRedis()
    rid = workflows.request("probe_process", {"thing": "art://x/y"}, "tester", client=r)
    assert workflows.status(rid, client=r)["process"] == "probe_process"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
