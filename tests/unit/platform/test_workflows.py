"""src/lab/platform/workflows.py — the run-request contract comes from lab.platform.contracts (statuses, the
event's field names via WorkflowRequest) and every entry point takes `client=` so a host's composition
root can hand in ITS Redis client (the container's Singleton) instead of the module reaching for the
pool. Offline: FakeRedis passed explicitly while the shared pool is a DeadRedis — any call that bypassed
the injected client would raise. (The full stream/hash behaviour is covered by tests/integration/test_workflows.py.)
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_workflows.py"""
import json

import pytest

from fixtures.fakes import DeadRedis, FakeRedis, patched_client
from lab.platform import workflows
from lab.platform.contracts import WorkflowRequest, WorkflowStatus

INPUTS = {"diagram": "art://d1/lab.vsdx", "requirements": ["art://r1/req.docx"]}


def test_statuses_are_the_contracts_values():
    assert workflows.STATUSES == tuple(s.value for s in WorkflowStatus) == ("pending", "running", "done", "failed")


def test_request_publishes_the_contracts_event_shape():
    with patched_client(FakeRedis()) as r:
        rid = workflows.request("visio_to_archimate", INPUTS, "socrates")
        (_, fields), = r.x[workflows.REQ]
        req = WorkflowRequest.from_fields(fields)                       # parses cleanly = shape is the contract's
        assert req.request_id == rid and req.process == "visio_to_archimate" and req.inputs == INPUTS
        assert req.requester == "socrates" and req.status is WorkflowStatus.PENDING
        assert set(fields) == {"request_id", "process", "inputs", "requester", "status", "created_at", "created_ts"}
        assert r.h[f"workflow:req:{rid}"] == fields


def test_every_entry_point_uses_the_injected_client_not_the_pool():
    fake = FakeRedis()
    with patched_client(DeadRedis()):                                    # the pool must never be touched
        rid = workflows.request("visio_to_archimate", INPUTS, "u", client=fake)
        assert workflows.status(rid, client=fake)["inputs"] == INPUTS
        assert [s["request_id"] for s in workflows.pending(client=fake)] == [rid]
        assert [s["request_id"] for s in workflows.recent(client=fake)] == [rid]
        upd = workflows.mark(rid, WorkflowStatus.RUNNING, consumer="1", client=fake)
        assert upd["status"] == "running" and fake.h[f"workflow:req:{rid}"]["status"] == "running"
        events = workflows.channel_events(workflows.GROUPS[0], "1", count=5, client=fake)
        assert [f["request_id"] for _, f in events] == [rid]
        workflows.ack(workflows.GROUPS[0], events[0][0], client=fake)
        assert fake.calls["xack"] == 1
        workflows.mark(rid, "done", summary={"views": 1}, client=fake)
        assert json.loads(fake.h[f"workflow:req:{rid}"]["summary"]) == {"views": 1}
        assert rid not in fake.s.get("workflow:pending", set())
        with pytest.raises(ValueError, match="one of"):
            workflows.mark(rid, "exploded", client=fake)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
