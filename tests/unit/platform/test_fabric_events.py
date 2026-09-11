"""The Change Events product: durable, at-least-once, reclaimable; the loop guard's memory."""
import json

from fixtures.fakes import FakeRedis
from lab.core import ids
from lab.platform import fabric_events as fe
from lab.platform.contracts import ArtifactChanged

POINTER = {"source": "collab", "handle": "collab://item/drive-1/01ABC", "version": "4.0"}


def _event(**over):
    base = dict(event_id=ids.ulid(), pointer=POINTER, source_kind="collab", change="updated",
                actor_oid="oid-1", occurred_at="2026-09-11T08:10:31Z")
    base.update(over)
    return ArtifactChanged(**base)


def test_publish_then_read_then_ack():
    r = FakeRedis()
    eid = fe.publish(_event(), client=r)
    assert eid
    got = fe.events(client=r)
    assert len(got) == 1 and ArtifactChanged.from_fields(got[0][1]).pointer_key == "collab:collab://item/drive-1/01ABC"
    fe.ack(got[0][0], client=r)
    assert fe.events(client=r) == []


def test_an_ingress_that_was_down_gets_what_queued():
    r = FakeRedis()
    fe.publish(_event(), client=r); fe.publish(_event(), client=r)
    assert len(fe.events(client=r)) == 2, "start_id 0: a stream of WORK"


def test_dead_letter_parks_and_acks():
    r = FakeRedis()
    fe.publish(_event(), client=r)
    eid, fields = fe.events(client=r)[0]
    fe.dead_letter(eid, fields, "boom", client=r)
    assert r.xlen(fe.DEAD) == 1 and fe.events(client=r) == []
    parked = r.xrange(fe.DEAD)[0][1]
    assert parked["reason"] == "boom" and parked["entry_id"] == eid


def test_loop_guard_memory_matches_the_version_the_fabric_wrote():
    r = FakeRedis()
    key = "collab:collab://item/drive-1/01ABC"
    assert fe.written_by_fabric(key, client=r) is None
    fe.mark_written(key, "5.0", "draft", "run-1", client=r)
    assert fe.written_by_fabric(key, "5.0", client=r) == {"version": "5.0", "kind": "draft", "runId": "run-1"}
    assert fe.written_by_fabric(key, "6.0", client=r) is None, "a person's later edit is a real change"
    assert fe.written_by_fabric(key, client=r)["kind"] == "draft"


def test_emit_cli_publishes(monkeypatch, capsys):
    r = FakeRedis()
    monkeypatch.setattr(fe, "_r", lambda client=None: r)
    payload = {"pointer": POINTER, "change": "created", "actor": {"oid": "o"}, "occurredAt": "2026-09-11T08:00:00Z"}
    assert fe.main(["emit", json.dumps(payload)]) == 0
    assert r.xlen(fe.STREAM) == 1
    assert fe.main(["nope"]) == 2
