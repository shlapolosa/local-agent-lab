"""`artifact_intake` — one changed artifact becomes a catalogued, classified, linked and reviewed record.

Offline: the gateway transport is the shared Router (every contract tool listed, the fabric's answered by
canned handlers that record what they were asked) and the two agents are scripted. What is pinned hardest
is WHICH RUNG each write lands on and that the run ends on the right question — a wrong rung makes impact
confidently wrong, and a run that decides instead of asking defeats the gate.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/artifact_intake/
"""
import json

import pytest

from fixtures.workflow import Router, run_spine, spine
from lab.platform.contracts import ARTIFACT_PUBLISH, ApprovalKind, ApprovalTools, SemanticTools
from lab.workloads.artifact_intake import agents as A
from lab.workloads.artifact_intake import workflow as W
from lab.workloads.gates import GateFailed

MINUTES = {"source": "lab", "ref": "art://run1/meeting-AAMk1.minutes.json"}
DOC = {"source": "collab", "handle": "collab://item/drive-1/doc7", "version": "2"}
DOC_TYPES = {"urn:fabric:scheme:doc-types#minutes": {"label": "Minutes", "alt": [], "produced_by": "transcript_to_minutes"},
             "urn:fabric:scheme:doc-types#decision-record": {"label": "Decision record", "alt": ["ADR"], "produced_by": ""}}
MINUTES_DOC = {"summary": "We agreed.", "concepts": [{"id": "c1", "label": "Legacy portal"}],
               "decisions": [{"id": "d1", "statement": "Retire the legacy portal", "concerns": ["c1"], "decided_by": ["maria"]}],
               "actions": [{"id": "a1", "commitment": "Plan the migration", "owner": "maria", "concerns": ["c1"], "implements": "d1"}]}
CLASSIFICATION = {"document_type": "urn:fabric:scheme:doc-types#decision-record", "confidence": 0.83,
                  "subjects": ["Care Delivery", "Unknown Term"], "rationale": "named ADR in the EA folder"}
RECORDS = {"records": [{"id": "d1", "title": "Retire the legacy portal", "status": "proposed", "context": "dup",
                        "decision": "Retire the legacy portal", "consequences": "not stated",
                        "decided_by": ["maria"], "concerns": ["Legacy portal"], "actions": ["Plan the migration"]}]}


class FakeAgent:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def run(self, prompt):
        self.prompts.append(prompt)
        r = self.replies.pop(0) if self.replies else {}
        return type("R", (), {"text": r if isinstance(r, str) else json.dumps(r)})()


class Fabric:
    """A canned semantic-mcp: rows by pointer, every write recorded with its rung."""

    def __init__(self, similar=None):
        self.rows, self.asserts, self.edges, self.similar_answer = {}, [], [], similar or []
        self.n = 0

    def upsert(self, a):
        key = f'{a["pointer"]["source"]}:{a["pointer"].get("ref") or a["pointer"].get("handle")}'
        if key not in self.rows:
            self.n += 1
            self.rows[key] = {"iri": f"urn:fabric:artifact:{self.n:026d}", "pointer": a["pointer"], "title": a.get("title", ""),
                              "document_type": "urn:fabric:scheme:doc-types#minutes" if a.get("produced_by") == "transcript_to_minutes" else "",
                              "context": a.get("context", ""), "state": "pending", "links": []}
        self.rows[key].update({k: a[k] for k in ("title", "context") if a.get(k)})
        return dict(self.rows[key])

    def tools(self, **over):
        t = {
            "semantic_catalog_upsert": self.upsert,
            "semantic_catalog_get": lambda a: next(({**r, "links": [{"predicate": "documentType", "rung": x["rung"], "object": x["value"]}
                                                                    for x in self.asserts if x["iri"] == r["iri"]]}
                                                    for r in self.rows.values() if r["iri"] == a["iri"]), None),
            "semantic_catalog_assert": lambda a: self.asserts.append(a) or {"rung": a["rung"], "assertion": "urn:fabric:assertion:x"},
            "semantic_catalog_state": lambda a: {"iri": a["iri"], "state": a["state"], "unassociated": a.get("unassociated")},
            "semantic_edge_assert": lambda a: self.edges.append(a) or {"rung": a["rung"]},
            "semantic_vocab_link": lambda a: {"linked": [{"term": t, "scheme": "syn", "concept": "urn:c", "label": t}
                                                         for t in a["terms"] if t != "Unknown Term"],
                                              "missed": [t for t in a["terms"] if t == "Unknown Term"]},
            "semantic_vocab_propose": lambda a: {"iri": "urn:fabric:candidate:1", "label": a["label"]},
            "semantic_impact": [{"iri": "urn:fabric:artifact:other", "title": "ADR-3", "rung": "X"}],
            "semantic_embed": {"iri": "x", "model": "m", "dim": 8},
            "semantic_similar": lambda a: self.similar_answer,
            "semantic_store_spec": lambda a: {"spec_ref": f"art://store/{a['name']}"},
            "storage_read_artifact": MINUTES_DOC,
            "collab_item": {"name": "ADR-14 Event bus.docx", "path": "/EA/decisions", "modified": "2026-09-11T00:00:00Z"},
            "approvals_ask": lambda a: {"request_id": "apr-1", "status": "pending", "asked": len(a["items"])},
        }
        t.update(over)
        return {k: v for k, v in t.items() if v is not None}


def harness(fab: Fabric, *, classifier=None, synthesis=None, threshold=0.75, default_label="", tools=None):
    # `None` for a tool = the gateway does NOT expose it (a missing grant, a version skew): unlisted, not just unanswered
    hidden = {k for k, v in (tools or {}).items() if v is None}
    router = Router(fab.tools(**(tools or {})), hidden=hidden, full=True)
    ctx = spine(W, router)
    h = ctx.__enter__()
    h.cfg.update({"agents": {k: v for k, v in (("classifier", classifier), ("synthesis", synthesis)) if v},
                  "schemas": {"classifier": A.schema("classifier"), "synthesis": A.schema("synthesis")},
                  "doc_types": DOC_TYPES, "threshold": threshold, "default_label": default_label})
    h.close = lambda: ctx.__exit__(None, None, None)
    return h


def calls(h, suffix):
    return h.router.called(suffix)


def test_a_minutes_run_output_is_a_fact_gets_drafts_and_ends_on_a_draft_review():
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": "urn:fabric:scheme:doc-types#minutes"}),
                synthesis=FakeAgent(RECORDS))
    try:
        out = run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                               "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    # identify: the upsert carried the producer and the context — the type and the delivery edge are C there
    up = calls(h, SemanticTools.catalog_upsert)[0]
    assert (up["produced_by"], up["context"]) == ("transcript_to_minutes", "meeting:AAMk1")
    # classify: the type was a fact, so NO suggestion was asserted for it; subjects linked, the miss proposed
    assert [a for a in fab.asserts if a["field"] == "document_type" and a["iri"] == out["artifact_iri"]] == []
    assert calls(h, SemanticTools.vocab_link)[0]["terms"] == ["Care Delivery", "Unknown Term"]
    assert calls(h, SemanticTools.vocab_propose)[0]["label"] == "Unknown Term"
    # synthesise: one draft per decision, its type a FACT (C), referencing the minutes (C)
    assert out["draft_refs"] == ["art://store/00000000000000000000000001.d1.decision-record.json"]
    draft = [a for a in fab.asserts if a["field"] == "document_type" and a["iri"] != out["artifact_iri"]][0]
    assert (draft["value"], draft["rung"], draft["method"]) == (W.DECISION_RECORD, "C", "drafted-by-fabric")
    assert [(e["predicate"].rsplit("#", 1)[-1], e["rung"]) for e in fab.edges] == [("references", "C")]
    # the question: draft-review, with the drafts attached and the publish continuation
    ask = calls(h, ApprovalTools.ask)[0]
    assert ask["kind"] == ApprovalKind.DRAFT_REVIEW.value and ask["process"] == "artifact_intake"
    assert [i["label"] for i in ask["items"]] == ["document_type"] and ask["fields"] == ["value"]
    assert ask["continuation"]["process"] == ARTIFACT_PUBLISH.name
    assert ask["continuation"]["inputs"] == {"artifact_iri": out["artifact_iri"]}
    assert list(ask["artifacts"].values()) == out["draft_refs"] and ask["requester"] == "a@x.org"
    assert out["approval_id"] == "apr-1" and out["kind"] == "draft-review" and out["association"] == "run-context"
    assert out["summary"]["drafts"] == 1 and out["summary"]["impact"] == 1


def test_a_persons_document_is_suggested_at_s_labelled_at_c_and_asked_where_it_belongs():
    fab = Fabric(similar=[{"iri": "urn:fabric:artifact:n1", "context": "usecase:UC-42", "score": 0.61},
                          {"iri": "urn:fabric:artifact:n2", "context": "meeting:AAMk1", "score": 0.40}])
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), default_label="Confidential")
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    # the title came from the collaboration item; the classifier saw metadata only
    assert calls(h, SemanticTools.catalog_upsert)[0]["title"] == "ADR-14 Event bus.docx"
    brief = json.loads(h.cfg["agents"]["classifier"].prompts[0])
    assert brief["path"] == "/EA/decisions" and "document_types" in brief and "body" not in brief
    # type at S with the confidence; label at C by the site default; no owner guessed
    by_field = {a["field"]: a for a in fab.asserts}
    assert (by_field["document_type"]["rung"], by_field["document_type"]["confidence"]) == ("S", 0.83)
    assert (by_field["sensitivity_label"]["rung"], by_field["sensitivity_label"]["method"]) == ("C", "site-default")
    assert "owner" not in by_field
    # below the threshold: no edge, marked unassociated, and the question is an ASSOCIATION with the candidates
    assert fab.edges == []
    assert calls(h, SemanticTools.catalog_state)[0]["unassociated"] is True
    ask = calls(h, ApprovalTools.ask)[0]
    assert ask["kind"] == ApprovalKind.ASSOCIATION.value
    ctx_item = next(i for i in ask["items"] if i["label"] == "context")
    assert ctx_item["samples"] == ["usecase:UC-42 (0.61)", "meeting:AAMk1 (0.40)"]
    assert out["association"] == "unassociated" and out["draft_refs"] == []


def test_a_confident_neighbour_is_suggested_and_an_id_in_the_title_is_extracted():
    fab = Fabric(similar=[{"iri": "urn:fabric:artifact:n1", "context": "usecase:UC-42", "score": 0.9}])
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    edge = fab.edges[0]
    assert (edge["rung"], edge["confidence"], edge["object"]) == ("S", 0.9, "urn:fabric:context:usecase:UC-42")
    assert out["association"] == "nearest-neighbour" and calls(h, ApprovalTools.ask)[0]["kind"] == "association"

    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), tools={"collab_item": {"name": "UC-7 solution design.docx"}})
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert (fab.edges[0]["rung"], fab.edges[0]["method"]) == ("X", "id-in-title")
    assert out["association"] == "id-in-title" and calls(h, ApprovalTools.ask)[0]["kind"] == "draft-review"


def test_the_classifier_is_gated_and_retried_once_then_refused():
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({"nonsense": True}, CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
        assert "rejected" in h.cfg["agents"]["classifier"].prompts[1]
    finally:
        h.close()
    h = harness(Fabric(), classifier=FakeAgent({"nonsense": True}, "still not json"))
    try:
        with pytest.raises(GateFailed, match="step classification"):
            run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()


def test_a_type_the_fabric_does_not_know_is_dropped_not_suggested():
    """The schema pins the URN's shape; the closed set is the fabric's. A hallucinated type must never become
    a rung-S assertion a reviewer could promote."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": "urn:fabric:scheme:doc-types#business-case"}))
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert [a for a in fab.asserts if a["field"] == "document_type"] == []
    ask = calls(h, ApprovalTools.ask)[0]
    assert "unknown type" in ask["items"][0]["samples"][1] and "suggested: unknown" in ask["items"][0]["samples"][0]
    assert out["summary"]["subjects"] == 1                       # the subjects were still linked


def test_without_agents_the_run_still_catalogues_and_asks():
    fab = Fabric()
    h = harness(fab)
    try:
        out = run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                               "produced_by": "transcript_to_minutes"})
    finally:
        h.close()
    assert out["artifact_iri"] and out["draft_refs"] == [] and calls(h, SemanticTools.vocab_link) == []


def test_overlap_and_a_missing_title_lookup_never_cost_the_run():
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION),
                tools={"collab_item": RuntimeError("no grant"), "semantic_embed": RuntimeError("no embedder")})
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert calls(h, SemanticTools.catalog_upsert)[0]["title"] == "doc7"
    assert out["summary"]["overlap"] == 0


def test_a_missing_required_tool_is_refused_at_preflight_for_zero_tokens():
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), tools={"semantic_catalog_upsert": None})
    try:
        with pytest.raises(RuntimeError):
            run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert h.cfg["agents"]["classifier"].prompts == []


def test_helpers():
    assert W._label_of({"source": "lab", "ref": "art://a/b/minutes.json"}) == "minutes.json"
    # the LINKED labels, never the agent's raw terms: a re-index from the catalog reproduces this text exactly
    assert W._describe({"pointer": DOC, "title": "T", "document_type": "urn:x#minutes", "subjects": ["a", "zz"],
                        "linked": [{"term": "a", "label": "Alpha"}]}) == "T · minutes · Alpha"
    assert W.DECISION_RECORD == "urn:fabric:scheme:doc-types#decision-record"
