"""`transcript_to_minutes` — an attributed transcript becomes knowledge.

One agent step, gated either side. What is pinned hardest is the gate, because it is the only thing
standing between a plausible-sounding model answer and a graph that quietly asserts something nobody
said.

Offline: the gateway transport and the agent are both faked.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/transcript_to_minutes/
"""
import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from lab.platform.contracts import SemanticTools, StorageTools
from lab.workloads.transcript_to_minutes import workflow as W

SCHEMA = json.loads((Path(W.__file__).resolve().parents[3] / "lab" / "core" / "meetings" /
                     "schemas" / "minutes.schema.json").read_text())
VALIDATOR = Draft7Validator(SCHEMA)

SEGMENTS = {"segments": [
    {"speaker": "SPEAKER_00", "start": 0.0, "end": 6.0, "text": "خلينا نعمل migration بعد الـ review"},
    {"speaker": "SPEAKER_01", "start": 6.0, "end": 8.0, "text": "agreed, we retire the legacy portal"}]}

MAP = {"SPEAKER_00": {"identity": "maria.perez@contoso.com"},
       "SPEAKER_01": {"tag": "the vendor's architect"}}

MINUTES = {"summary": "We agreed to retire the legacy portal.",
           "concepts": [{"id": "c1", "label": "Legacy portal"}],
           "decisions": [{"id": "d1", "statement": "Retire the legacy portal", "concerns": ["c1"],
                          "decided_by": ["SPEAKER_01"]}],
           "actions": [{"id": "a1", "commitment": "Plan the migration", "owner": "SPEAKER_00",
                        "concerns": ["c1"], "implements": "d1"}],
           "keywords": ["migration"]}


class FakeAgent:
    """Answers with a script; records what it was asked."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def run(self, prompt):
        self.prompts.append(prompt)
        r = self.replies.pop(0) if self.replies else MINUTES
        return type("R", (), {"text": r if isinstance(r, str) else json.dumps(r)})()


class FakeGateway:
    def __init__(self, **overrides):
        self.answers = {StorageTools.read_artifact: SEGMENTS,
                        SemanticTools.validate_model: {"illegal": [], "warnings": []},
                        SemanticTools.store_spec: {"ref": "art://s/x.json"},
                        SemanticTools.load_model: {"triples": 42, "derived_relations": 0}} | overrides
        self.calls = []

    async def __call__(self, headers, mcp_url, calls):
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            out.append(self.answers[suffix])
        return out

    def args_for(self, suffix):
        return [a for s, a in self.calls if s == suffix]


@pytest.fixture
def gw(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(W.gateway, "call_tools", fake)
    async def ok(*a, **kw): return None
    monkeypatch.setattr(W.gateway, "preflight", ok)
    return fake


def _run(agent=None, **over):
    cfg = W.make_cfg(credential="k", schema=SCHEMA, agent=agent or FakeAgent())
    inputs = {"transcript": "art://t/x.json", "speaker_map": MAP, "owner": "maria@contoso.com",
              "meeting": {"id": "mtg-1", "subject": "Arch review"}} | over
    return asyncio.run(W.run_workflow(cfg, inputs))


# ------------------------------------------------------------------ the happy path
def test_it_writes_minutes_and_loads_them(gw):
    out = _run()
    assert out["minutes_ref"] == "art://s/x.json" and out["model_id"] == "meeting-mtg-1"
    assert out["summary"]["decisions"] == 1 and out["summary"]["triples"] == 42
    assert "Legacy portal" in out["keywords"] and "migration" in out["keywords"]


def test_the_model_reads_display_names_never_addresses(gw):
    """The gateway pseudonymises addresses, so a transcript full of them reaches the model as
    placeholders and degrades the moment it paraphrases one."""
    agent = FakeAgent()
    _run(agent)
    prompt = agent.prompts[0]
    assert "maria.perez:" in prompt and "@" not in prompt
    assert "the vendor's architect:" in prompt


def test_the_model_is_loaded_under_the_meeting_vocabulary(gw):
    _run()
    load = gw.args_for(SemanticTools.load_model)[0]
    assert load["vocab"] == "meeting-1.0" and load["model_id"] == "meeting-mtg-1"
    assert "spec_ref" in load, "a workload holds no store credentials — it can only pass a reference"


def test_the_minutes_are_stored_before_the_graph_is_loaded(gw):
    """The artifact is the source of truth and the graph is derived — the store is in-memory, so the
    order is what makes the knowledge survive a restart at all."""
    _run()
    order = [s for s, _ in gw.calls]
    assert order.index(SemanticTools.store_spec) < order.index(SemanticTools.load_model)


# ------------------------------------------------------------------ the gate
def _gate(minutes, labels={"SPEAKER_00", "SPEAKER_01"}):
    return W.gate(VALIDATOR, json.loads(json.dumps(minutes)), labels)


def test_good_minutes_pass_the_gate():
    assert _gate(MINUTES) == []


def test_an_invented_speaker_is_caught_and_named():
    """The single likeliest hallucination, and a schema cannot see it."""
    bad = {**MINUTES, "actions": [{"id": "a1", "commitment": "x", "owner": "SPEAKER_09",
                                   "concerns": ["c1"]}]}
    assert any("SPEAKER_09" in p for p in _gate(bad))


def test_minutes_about_nothing_are_refused():
    """A meeting the minutes cannot say was ABOUT anything is not usable — this is what makes the
    model concept-centred rather than a pile of prose."""
    assert any("concept" in p.lower() for p in _gate({**MINUTES, "concepts": []}))


def test_a_decision_concerning_an_unknown_concept_is_caught():
    bad = {**MINUTES, "decisions": [{"id": "d1", "statement": "x", "concerns": ["c9"]}]}
    assert any("c9" in p for p in _gate(bad))


def test_the_bare_speaker_shorthand_is_normalised_before_the_schema_sees_it():
    """So the schema validates ONE shape and an error names the item, rather than saying 'not valid
    under any of the given schemas' — which a corrective retry cannot act on."""
    m = json.loads(json.dumps(MINUTES))
    m["decisions"][0]["evidence"] = "SPEAKER_01"
    assert W.gate(VALIDATOR, m, {"SPEAKER_00", "SPEAKER_01"}) == []
    assert m["decisions"][0]["evidence"] == [{"speaker": "SPEAKER_01"}]


def test_not_json_at_all_is_a_gate_failure_not_a_crash():
    assert _gate(None) == ["not valid JSON"]


# ------------------------------------------------------------------ the retry
def test_a_rejected_answer_gets_one_corrective_retry_carrying_the_transcript_again(gw):
    """The client is stateless, so a bare text correction would run blind."""
    agent = FakeAgent({**MINUTES, "concepts": []}, MINUTES)
    out = _run(agent)
    assert len(agent.prompts) == 2 and out["minutes_ref"]
    assert "maria.perez:" in agent.prompts[1], "the retry re-sends the transcript"
    assert "rejected" in agent.prompts[1]


def test_still_wrong_after_the_retry_fails_the_run(gw):
    agent = FakeAgent({**MINUTES, "concepts": []}, {**MINUTES, "concepts": []})
    with pytest.raises(RuntimeError, match="after retry"):
        _run(agent)


# ------------------------------------------------------------------ the answer must match the audio
def test_a_speaker_nobody_identified_stops_the_run(gw, monkeypatch):
    """An unattributed voice must never reach the minutes as SPEAKER_03."""
    monkeypatch.setitem(gw.answers, StorageTools.read_artifact,
                        {"segments": SEGMENTS["segments"] + [{"speaker": "SPEAKER_03", "text": "hm"}]})
    with pytest.raises(RuntimeError, match="SPEAKER_03"):
        _run()


def test_an_answer_naming_someone_who_never_speaks_is_refused(gw):
    with pytest.raises(RuntimeError, match="SPEAKER_09"):
        _run(speaker_map={**MAP, "SPEAKER_09": {"tag": "ghost"}})


def test_an_empty_transcript_fails_where_it_is_read(gw, monkeypatch):
    monkeypatch.setitem(gw.answers, StorageTools.read_artifact, {"segments": []})
    with pytest.raises(RuntimeError, match="no segments"):
        _run()


def test_an_illegal_mapped_model_fails_before_it_is_stored(gw, monkeypatch):
    """Two independent gates: the schema, then the vocabulary's own matrix."""
    monkeypatch.setitem(gw.answers, SemanticTools.validate_model,
                        {"illegal": [{"src": "p1", "type": "OwnedBy", "tgt": "a1"}], "warnings": []})
    with pytest.raises(RuntimeError, match="illegal"):
        _run()
    assert gw.args_for(SemanticTools.load_model) == []


def test_required_tools_are_spelled_from_the_contract():
    assert set(W.REQUIRED_TOOLS) == {StorageTools.read_artifact, SemanticTools.store_spec,
                                     SemanticTools.load_model, SemanticTools.validate_model}


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


# ---------------------------------------------------------------- naming the meeting
def test_the_meeting_comes_from_the_recording_handle_when_there_is_one():
    """collab://recording/<meeting>/<record> — the SCOPE is the meeting, so no lookup is needed."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    m = _meeting_from("collab://recording/alice~m1/rec9", "art://a/x.segments.json")
    assert m["id"] == "alice~m1" and m["resolved"] is True
    assert m["recording"] == "collab://recording/alice~m1/rec9"


def test_without_a_recording_the_meeting_is_marked_unresolved():
    """The fallback id is a FILENAME. Fine for keying a model, useless for putting anything back
    beside the meeting — so `resolved` is false and every writer must honour it."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    m = _meeting_from("", "art://a/x.segments.json")
    assert m["resolved"] is False and m["id"] == "x.segments.json"


def test_a_malformed_recording_handle_degrades_rather_than_raising():
    """A bad handle must not cost the minutes; it costs only the meeting association."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    for bad in ("not-a-handle", "collab://", "collab://recording/only-two"):
        assert _meeting_from(bad, "art://a/x.segments.json")["resolved"] is False


def test_a_file_handle_names_a_drive_not_a_meeting():
    """The case that actually arrives. A producer watching a FOLDER sends
    collab://item/<drive>/<file>, whose scope is a DRIVE — treating it as a meeting would mint
    `meeting-b!eTA-...` and tell every downstream reader the meeting was known."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    m = _meeting_from("collab://item/b!drive-1/01FILE", "art://a/x.segments.json")
    assert m["resolved"] is False, "a drive id is not a meeting id"
    assert m["id"] == "x.segments.json"
    assert m["recording"] == "collab://item/b!drive-1/01FILE", "but the handle is still worth keeping"


def test_the_handle_is_kept_whatever_its_kind():
    """Even when it names no meeting it says which drive and which file — which is what a writer
    needs to work out where to put the outputs."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    for h in ("collab://item/b!d/01F", "collab://recording/alice~m1/rec9"):
        assert _meeting_from(h, "art://a/x.json")["recording"] == h


def test_where_to_announce_is_carried_in_and_is_independent_of_naming_the_meeting():
    """The half of the seam this side owns, and it is deliberately NOT derived from anything here.

    A run can know exactly which conversation to tell and still have no meeting id of its own: the
    producer that watches a folder sends an ITEM handle, whose scope is a DRIVE. Tying the
    announcement to `resolved` would therefore silence the common case."""
    from lab.workloads.transcript_to_minutes.host import _meeting_from
    m = _meeting_from("collab://item/b!drive-1/01FILE", "art://a/x.json", "19:m@thread.v2")
    assert m["chat_id"] == "19:m@thread.v2" and m["resolved"] is False
    assert _meeting_from("collab://item/b!d/01F", "art://a/x.json")["chat_id"] == "", \
        "and a run told nothing announces nothing rather than guessing a destination"


# ---------------------------------------------------------------- putting the outputs back
ITEM = {"id": "01FILE", "name": "weekly sync.mp4", "drive_id": "b!d", "folder": False,
        "parent": "01FOLDER", "parent_handle": "collab://item/b!d/01FOLDER"}


def _delivering(gw, item=ITEM):
    gw.answers[W.CollabTools.item] = item
    gw.answers[W.CollabTools.put] = {"name": "x", "handle": "collab://item/b!d/01NEW", "bytes": 10,
                                     "url": "https://lab.sharepoint.example/Recordings/x"}
    return gw


def test_the_outputs_are_written_into_the_folder_the_recording_sits_in(gw):
    """"Beside the recording" is what makes them findable without the lab: a person who goes looking
    for the recording finds them next to it, and the provider indexes them for search."""
    _delivering(gw)
    out = _run(meeting={"id": "mtg-1", "subject": "Arch review", "chat_id": "19:t@thread.v2",
                        "recording": "collab://item/b!d/01FILE"})
    folders = {a["folder"] for a in gw.args_for(W.CollabTools.put)}
    assert folders == {"collab://item/b!d/01FOLDER"}, "the folder came from the item, not a guess"
    names = [a["name"] for a in gw.args_for(W.CollabTools.put)]
    assert names == ["weekly sync.transcript.md", "weekly sync.minutes.json"]
    assert len(out["delivered"]) == 2 and out["chat_id"] == "19:t@thread.v2"
    # each with the address a person opens, which is the whole point of announcing them: a chat
    # message can carry a link, and can carry neither a handle nor an id
    assert all(f["url"] for f in out["delivered"])


def test_only_the_prose_transcript_leaves_the_lab(gw):
    """The structured transcript is the audit trail and keeps directory addresses. Publishing it
    would put a list of who-is-who into a folder whose permissions are the recording's — a wider
    audience than the audit needs. The prose form carries display names only."""
    _delivering(gw)
    _run(meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    stored = [a for a in gw.args_for(W.SemanticTools.store_spec) if "transcript" in a.get("name", "")]
    assert stored, "the prose transcript was stored for upload"
    assert "@" not in json.dumps(stored[0]["spec"]), "no directory address leaves the lab"


def test_delivery_never_costs_the_minutes(gw):
    """The minutes are written, stored and loaded before this runs. Failing the run because a tenant
    would not take a copy would throw away the work over its delivery."""
    _delivering(gw)
    original = gw.__call__

    async def refuse(headers, mcp_url, calls):
        if any(s == W.CollabTools.put for s, _ in calls):
            raise RuntimeError("the tenant refused the upload")
        return await original(headers, mcp_url, calls)
    W.gateway.call_tools = refuse

    out = _run(meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    assert out["minutes_ref"] and out["model_id"], "the minutes still exist"
    assert out["delivered"] == [], "nothing was delivered"
    assert "refused the upload" in out["delivery"], "and the run says why, without failing"


def test_no_recording_handle_means_nowhere_to_put_them_and_says_so(gw):
    """The honest end of it, rather than a guess at some default folder."""
    out = _run(meeting={"id": "m", "subject": "s"})
    assert out["delivered"] == [] and "nowhere" in out["delivery"]
    assert out["minutes_ref"], "and the minutes are unaffected"


def test_an_item_with_no_folder_is_reported_not_guessed(gw):
    """A file at the drive root names no parent. Writing it somewhere plausible would be worse."""
    _delivering(gw, item={"id": "01F", "name": "rec.mp4", "drive_id": "b!d", "parent_handle": None})
    out = _run(meeting={"id": "m", "recording": "collab://item/b!d/01F"})
    assert out["delivered"] == [] and "folder" in out["delivery"]
