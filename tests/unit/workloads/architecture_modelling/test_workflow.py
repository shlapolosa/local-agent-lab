"""`architecture_modelling` — documents in, a cited model and an architect's review out.

Offline: the gateway transport and the agent are both faked; the doubles answer in the shapes the
real tools return (`semantic_store_spec` -> `spec_ref`, `approvals_ask` -> `request_id`).
"""
import asyncio
import json

import pytest

from lab.platform.contracts import ApprovalTools, SemanticTools, StorageTools
from lab.workloads.architecture_modelling import workflow as W

TEXT = "The triage nurse assesses each referral.\n\nReferrals are held in the Cerner EHR."

OUTPUT = {
    "systemName": "Referral triage", "summary": "Nurses triage referrals.",
    "elements": [
        {"name": "Triage nurse", "role": "triages",
         "type": "BusinessRole", "provenance": [{"source": "S1", "location": {"paragraph": 1},
                                                 "quote": "The triage nurse"}]},
        {"name": "Cerner EHR", "role": "holds referrals",
         "type": "ApplicationComponent", "provenance": [{"source": "S1", "location": {"paragraph": 2},
                                                         "quote": "the Cerner EHR"}]}],
    "relationships": [], "openQuestions": []}


class FakeAgent:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def run(self, prompt):
        self.prompts.append(prompt)
        r = self.replies.pop(0) if self.replies else OUTPUT
        return type("R", (), {"text": r if isinstance(r, str) else json.dumps(r)})()


class FakeGateway:
    def __init__(self, **overrides):
        self.answers = {StorageTools.read_document: TEXT,
                        SemanticTools.store_spec: {"spec_ref": "art://s/model.envelope.json",
                                                   "name": "model.envelope.json"},
                        ApprovalTools.ask: {"request_id": "apr-1", "review_app": "https://r/apr-1"}
                        } | overrides
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

    async def ok(*a, **kw):
        return None
    monkeypatch.setattr(W.gateway, "preflight", ok)
    return fake


def _run(agent=None, documents=("art://1/brief.docx",)):
    cfg = W.make_cfg(credential="k", agent=agent or FakeAgent())
    return asyncio.run(W.run_workflow(cfg, {"documents": list(documents), "submitter": "a@b"}))


def test_it_models_stores_the_envelope_and_asks_an_architect(gw):
    out = _run()
    assert out["model_ref"] == "art://s/model.envelope.json" and out["approval_id"] == "apr-1"
    assert out["summary"] == {"elements": 2, "relations": 0, "open_questions": 0, "dropped": 0}


def test_the_stored_envelope_is_the_contract_s_shape_with_refs_not_keys(gw):
    _run()
    (stored,) = gw.args_for(SemanticTools.store_spec)
    env = stored["spec"]
    assert env["contract_version"] and {e["id"] for e in env["spec"]["elements"]} == \
        {"business-role-triage-nurse", "ac-cerner-ehr"}
    (p,) = env["provenance"]["elements"]["ac-cerner-ehr"]
    assert p["source_ref"] == "art://1/brief.docx", "the agent's S1 becomes the ref it stands for"


def test_the_agent_sees_every_document_under_its_key_with_numbered_paragraphs(gw):
    agent = FakeAgent()
    _run(agent, documents=("art://1/brief.docx", "art://2/annex.md"))
    prompt = agent.prompts[0]
    assert "## S1 — brief.docx" in prompt and "## S2 — annex.md" in prompt
    assert "[¶2] Referrals are held in the Cerner EHR." in prompt


def test_the_review_is_a_draft_review_for_this_process_with_the_model_attached(gw):
    _run()
    (ask,) = gw.args_for(ApprovalTools.ask)
    assert ask["process"] == "architecture_modelling" and ask["kind"] == "draft-review"
    assert ask["artifacts"]["model_ref"] == "art://s/model.envelope.json"
    assert ask["artifacts"]["source_S1_ref"] == "art://1/brief.docx"
    assert ask["requester"] == "a@b" and "continuation" not in ask


def test_an_invalid_answer_gets_one_corrective_retry(gw):
    agent = FakeAgent({"systemName": "x"}, OUTPUT)
    out = _run(agent)
    assert len(agent.prompts) == 2 and "rejected" in agent.prompts[1]
    assert out["approval_id"] == "apr-1"


def test_a_document_with_no_text_is_refused_by_name(monkeypatch):
    fake = FakeGateway(**{StorageTools.read_document: "   "})
    monkeypatch.setattr(W.gateway, "call_tools", fake)

    async def ok(*a, **kw):
        return None
    monkeypatch.setattr(W.gateway, "preflight", ok)
    with pytest.raises(Exception, match="brief.docx"):
        _run()
