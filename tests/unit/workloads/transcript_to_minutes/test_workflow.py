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
        self.answers = {StorageTools.read_document: SEGMENTS,
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
    monkeypatch.setitem(gw.answers, StorageTools.read_document,
                        {"segments": SEGMENTS["segments"] + [{"speaker": "SPEAKER_03", "text": "hm"}]})
    with pytest.raises(RuntimeError, match="SPEAKER_03"):
        _run()


def test_an_answer_naming_someone_who_never_speaks_is_refused(gw):
    with pytest.raises(RuntimeError, match="SPEAKER_09"):
        _run(speaker_map={**MAP, "SPEAKER_09": {"tag": "ghost"}})


def test_an_empty_transcript_fails_where_it_is_read(gw, monkeypatch):
    monkeypatch.setitem(gw.answers, StorageTools.read_document, {"segments": []})
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
    assert set(W.REQUIRED_TOOLS) == {StorageTools.read_document, SemanticTools.store_spec,
                                     SemanticTools.load_model, SemanticTools.validate_model}


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
