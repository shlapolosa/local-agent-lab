"""The ingress: finished runs and adapter events become ONE intake run each; filtered, attributed, de-duplicated."""
import json

from fixtures.fakes import FakeRedis
from lab.core import ids
from lab.platform import config, fabric_events, workflows
from lab.platform.contracts import ArtifactChanged
from lab.substrate import fabric_ingress as ing

POINTER = {"source": "collab", "handle": "collab://item/drive-1/01ABC", "version": "4.0"}


def _event(**over):
    base = dict(event_id=ids.ulid(), pointer=POINTER, source_kind="collab", change="updated", actor_oid="o",
                occurred_at="2026-09-11T08:10:31Z")
    base.update(over)
    return ArtifactChanged(**base)


def _minutes_state():
    return {"request_id": "r1", "process": "transcript_to_minutes", "status": "done", "requester": "a@x.org",
            "finished_at": "2026-09-11T09:00:00Z", "inputs": {"recording": "collab://recording/AAMk1/rec-9"},
            "delivered": [{"name": "minutes.docx", "url": "https://t/m", "handle": "collab://item/drive-1/m1"},
                          {"name": "transcript.docx", "url": "https://t/t", "handle": "collab://item/drive-1/t1"}],
            "minutes_ref": "art://abc/minutes.json", "trace_id": "tr"}


def test_a_finished_minutes_run_yields_one_event_per_artifact_with_context_and_producer():
    evs = ing.events_from_run(_minutes_state())
    keys = sorted(e.pointer_key for e in evs)
    assert keys == ["collab:collab://item/drive-1/m1", "collab:collab://item/drive-1/t1", "lab:art://abc/minutes.json"]
    assert all(e.produced_by == "transcript_to_minutes" and e.context == "meeting:AAMk1" for e in evs)


def test_the_speech_lane_rides_on_every_pointer_of_a_lane_run():
    """Three provider lanes over one recording are three lanes of a comparison, not three versions."""
    st = _minutes_state(); st["inputs"]["provider"] = "soniox-en"
    evs = ing.events_from_run(st)
    assert {e.pointer.get("lane") for e in evs} == {"soniox-en"}
    assert sorted(e.pointer_key for e in evs) == sorted(e.pointer_key for e in ing.events_from_run(_minutes_state()))
    assert all("lane" not in e.pointer for e in ing.events_from_run(_minutes_state()))


def test_only_done_runs_of_producing_processes_count():
    assert ing.events_from_run({**_minutes_state(), "status": "failed"}) == []
    assert ing.events_from_run({**_minutes_state(), "process": "artifact_intake"}) == []
    assert "artifact_intake" not in ing.PRODUCERS and "artifact_publish" not in ing.PRODUCERS


def test_allowlist_admits_lab_always_and_external_only_when_listed(monkeypatch):
    lab = _event(pointer={"source": "lab", "ref": "art://a/b"}, source_kind="lab")
    assert ing.admitted(lab, allowlist=())
    ext = _event()
    assert not ing.admitted(ext, allowlist=())
    assert ing.admitted(ext, allowlist=("collab:drive-1",))
    assert ing.admitted(ext, allowlist=("collab:*",))
    assert not ing.admitted(ext, allowlist=("collab:drive-2",))


def test_attribution_uses_the_loop_guards_memory():
    r = FakeRedis()
    plain = _event()
    assert not ing.attributed(plain, client=r).is_fabric_originated
    fabric_events.mark_written(plain.pointer_key, "4.0", "draft", "run-9", client=r)
    assert ing.attributed(plain, client=r).is_fabric_originated
    newer = _event(pointer={**POINTER, "version": "5.0"})
    assert not ing.attributed(newer, client=r).is_fabric_originated, "a person's later edit is real"


def test_submit_once_per_pointer_version(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ("collab:*",))
    workflows.ensure_groups(r)
    first = ing.submit_for(_event(), client=r)
    again = ing.submit_for(_event(), client=r)
    assert first and not first[1]
    assert again and again[1] and again[0] == first[0], "same pointer+version -> the same run"
    state = workflows.status(first[0], client=r)
    assert state["process"] == "artifact_intake" and state["inputs"]["pointer"]["handle"] == POINTER["handle"]
    assert ing.submit_for(_event(fabric_tag={"kind": "draft"}), client=r) is None
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ())
    assert ing.submit_for(_event(), client=r) is None


def test_handle_finished_submits_and_acks(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ("collab:*",))
    workflows.ensure_groups(r)
    r.hset("workflow:req:r1", mapping={k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in _minutes_state().items()})
    workflows.ensure_finished_group(ing.FINISHED_GROUP, r)
    r.xadd(workflows.DONE, {"request_id": "r1", "process": "transcript_to_minutes", "status": "done", "finished_at": "t"})
    started = ing.run_once(client=r)
    assert len(started) == 3
    assert workflows.finished_events(ing.FINISHED_GROUP, client=r) == [], "acked"


def test_handle_event_dead_letters_a_malformed_entry_and_acks_a_good_one(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ("collab:*",))
    workflows.ensure_groups(r); fabric_events.ensure_group(r)
    r.xadd(fabric_events.STREAM, {"event_id": "bad", "pointer": "{}"})
    fabric_events.publish(_event(), client=r)
    started = ing.run_once(client=r)
    assert len(started) == 1
    assert r.xlen(fabric_events.DEAD) == 1
    assert fabric_events.events(client=r) == []



def test_the_serve_loop_dispatches_a_two_stream_read_the_way_serve_calls_it(monkeypatch):
    """`streams.serve` calls `handle(id, fields)` on every read item; the ingress reads TWO streams and tags
    each item with its origin, so the handler takes (kind, (entry id, fields)). Found live, not by a test."""
    seen = []
    monkeypatch.setattr(ing, "handle_finished", lambda eid, f, *, client: seen.append(("finished", eid, f)) or ["r1"])
    monkeypatch.setattr(ing, "handle_event", lambda eid, f, *, client: seen.append(("event", eid, f)) or "r2")
    assert ing.dispatch("finished", ("1-0", {"request_id": "r"}), client=None) == ["r1"]
    assert ing.dispatch("event", ("2-0", {"event_id": "e"}), client=None) == "r2"
    assert [s[0] for s in seen] == ["finished", "event"]
    import inspect
    src = inspect.getsource(ing.main)
    assert "lambda kind, entry: dispatch(kind, entry" in src, "serve's handle takes (id, fields) — two arguments"
