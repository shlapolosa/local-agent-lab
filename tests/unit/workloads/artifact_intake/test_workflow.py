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
from lab.core.semantic.fabric.owners import OwnerMap
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
                  "subjects": ["Care Delivery", "Unknown Term"], "rationale": "named ADR in the EA folder",
                  "subject_confidence": {"Care Delivery": 0.88, "Unknown Term": 0.77}}
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


def harness(fab: Fabric, *, classifier=None, synthesis=None, threshold=0.75, default_label="", tools=None,
            owners=None, vocabulary="", subject_floor=0.0):
    # `None` for a tool = the gateway does NOT expose it (a missing grant, a version skew): unlisted, not just unanswered
    hidden = {k for k, v in (tools or {}).items() if v is None}
    router = Router(fab.tools(**(tools or {})), hidden=hidden, full=True)
    ctx = spine(W, router)
    h = ctx.__enter__()
    h.cfg.update({"agents": {k: v for k, v in (("classifier", classifier), ("synthesis", synthesis)) if v},
                  "schemas": {"classifier": A.schema("classifier"), "synthesis": A.schema("synthesis")},
                  "doc_types": DOC_TYPES, "threshold": threshold, "default_label": default_label,
                  # the shipped map's lab rule: a lab product's owner is the person who asked for the run
                  "owners": owners or OwnerMap.from_dict({"lab": {"transcript_to_minutes": "requester"}}),
                  "overlap_threshold": 0.85, "vocabulary": vocabulary, "subject_floor": subject_floor})
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
    # the draft references the minutes AND is synthesised from them — the second is what rung D derives the context from
    assert [(e["predicate"].rsplit("#", 1)[-1], e["rung"]) for e in fab.edges] == [("references", "C"), ("synthesisedFrom", "C")]
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


def test_a_revised_record_tells_the_reviewer_it_is_a_new_version():
    fab = Fabric()
    real = fab.upsert
    def revised_upsert(a):
        row = real(a); row.update(revised=True, previous_version="wfr-1"); return row
    fab.upsert = revised_upsert
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": "urn:fabric:scheme:doc-types#minutes"}),
                synthesis=FakeAgent(RECORDS))
    try:
        run_spine(W, h, {"pointer": {"source": "lab", "product": "transcript_to_minutes/minutes_ref/collab:recording/AAMk1/rec-9",
                                     "ref": "art://r2/minutes.json", "version": "wfr-2"}, "event_id": "01J",
                         "context": "meeting:AAMk1", "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    ask = h.router.called(ApprovalTools.ask)[0]
    assert "NEW VERSION wfr-2" in ask["prompt"] and "wfr-1" in ask["prompt"]


def test_owner_and_label_are_looked_up_at_c_and_an_unresolved_owner_is_asked():
    from lab.core.semantic.fabric.owners import OwnerMap
    owners = OwnerMap.from_dict({"lab": {"transcript_to_minutes": "requester"}, "collab": {"drive-1/EA": "ea@x"}})
    # a lab product: the run's requester, method `requester`
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": "urn:fabric:scheme:doc-types#minutes"}),
                synthesis=FakeAgent(RECORDS), owners=owners)
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                         "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    owner = [a for a in fab.asserts if a["field"] == "owner"]
    assert owner and (owner[0]["value"], owner[0]["rung"], owner[0]["method"]) == ("urn:fabric:person:a@x.org", "C", "requester")
    # a library document: the folder rule wins, the item's label is the label (method item-label)
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), owners=owners, default_label="Internal",
                tools={"collab_item": {"name": "ADR-14.docx", "path": "EA/decisions", "modified": "2026-09-11T00:00:00Z",
                                       "label": "Confidential", "author": "ann@x"}})
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    by = {a["field"]: a for a in fab.asserts if a["field"] in ("owner", "sensitivity_label")}
    assert (by["owner"]["value"], by["owner"]["method"]) == ("urn:fabric:person:ea@x", "owner-map")
    assert (by["sensitivity_label"]["value"], by["sensitivity_label"]["method"]) == ("Confidential", "item-label")
    # nobody: no rule, no author → no owner asserted, the review asks the steward
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), owners=OwnerMap.empty())
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert not [a for a in fab.asserts if a["field"] == "owner"]
    assert "owner" in [i["label"] for i in h.router.called(ApprovalTools.ask)[0]["items"]]


def test_a_near_duplicate_of_a_published_record_becomes_a_review_item():
    near = [{"iri": "urn:fabric:artifact:PUB", "title": "ADR-14 Event bus", "score": 0.91, "state": "published"},
            {"iri": "urn:fabric:artifact:PEN", "title": "draft twin", "score": 0.97, "state": "pending"},
            {"iri": "urn:fabric:artifact:FAR", "title": "unrelated", "score": 0.40, "state": "published"}]
    fab = Fabric(similar=near)
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    ask = h.router.called(ApprovalTools.ask)[0]
    item = next(i for i in ask["items"] if i["label"] == "overlap")
    assert any("ADR-14 Event bus" in s and "0.91" in s for s in item["samples"]) and not any("draft twin" in s for s in item["samples"])
    assert any("duplicate-of:" in s for s in item["samples"]) and out["summary"]["overlap"] == 1
    fab = Fabric(similar=[{"iri": "urn:fabric:artifact:PUB", "title": "ADR-14", "score": 0.5, "state": "published"}])
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "overlap" not in [i["label"] for i in h.router.called(ApprovalTools.ask)[0]["items"]]


def test_a_new_version_that_published_records_reference_tells_their_owners():
    hits = [{"iri": "urn:fabric:artifact:R1", "title": "Runbook 7", "rung": "X", "state": "published", "owner": "urn:fabric:person:ann@x"},
            {"iri": "urn:fabric:artifact:D1", "title": "a draft", "rung": "X", "state": "pending", "owner": ""}]
    fab = Fabric()
    real = fab.upsert
    def revised_upsert(a):
        row = real(a); row.update(revised=True, previous_version="wfr-1"); return row
    fab.upsert = revised_upsert
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), tools={"semantic_impact": hits})
    try:
        out = run_spine(W, h, {"pointer": {**DOC, "version": "5.0"}, "event_id": "01K"})
    finally:
        h.close()
    asks = h.router.called(ApprovalTools.ask)
    notice = next(a for a in asks if a["kind"] == "impact-notice")
    assert notice["answer_required"] is False and "1 published record" in notice["subject"]
    assert [i["label"] for i in notice["items"]] == ["urn:fabric:artifact:R1"] and "ann@x" in notice["items"][0]["samples"][0]
    assert "continuation" not in notice and out["notice_id"]
    # a first version tells nobody
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), tools={"semantic_impact": hits})
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "impact-notice" not in [a["kind"] for a in h.router.called(ApprovalTools.ask)] and not out.get("notice_id")


def test_the_classifier_is_shown_the_vocabulary_and_its_chosen_ids_become_links():
    """The payoff of owning a vocabulary: subjects are CHOSEN from it and link by id, instead of being invented
    and then having to match a label exactly. A vocabulary that cannot be read degrades to the old behaviour,
    because an unclassified record is worse than an unlinked one."""
    concepts = [{"id": "Referral", "label": "Referral", "definition": "A request to transfer care.",
                 "module": "CARE"},
                {"id": "DigitalPlatform", "label": "Digital platform", "module": "ENG"}]
    fab = Fabric()
    seen = {}

    class Choosing(FakeAgent):
        def __init__(self):
            super().__init__({**CLASSIFICATION, "subjects": ["Referral", "Widget"]})

        async def run(self, text, **kw):                      # the brief the agent is handed
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    h = harness(fab, classifier=Choosing(), tools={"semantic_concepts": concepts}, vocabulary="cafe")
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert [c["id"] for c in seen["brief"]["concepts"]] == ["Referral", "DigitalPlatform"]
    assert h.router.called(SemanticTools.concepts)[0] == {"scheme": "cafe", "kind": ""}
    linked = h.router.called(SemanticTools.vocab_link)[0]["terms"]
    assert linked == ["Referral", "Widget"]                   # ids go straight to the link, misses to a proposal

    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), vocabulary="cafe",
                tools={"semantic_concepts": RuntimeError("no grant")})
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert h.router.called(SemanticTools.vocab_link)          # the run still classifies and still links


# ---------------------------------------------------------------- classifying on EVIDENCE, not on a filename
LAB_DOC = {"source": "lab", "ref": "art://store/minutes.json", "product": "p/q/r"}


def test_the_classifier_is_shown_an_excerpt_of_what_it_is_classifying():
    """The defect this closes, measured 6 Oct 2026 on the live catalogue: the classifier was shown a TITLE, a
    file name, a path and 123 concepts — never a byte of the document — and asked what it is about. For
    `UC-1043-business-case.docx` in `/BusinessCases/` that nearly works; for
    `Test 8-20261006_104714-Meeting Recording.comparison.txt` it cannot, and the model did what a model does
    with no evidence: it reached for the nearest concepts in a healthcare-shaped vocabulary. `Clinical document`
    landed on 39 of 93 records, and a meeting about a note-taking app was filed under `Teleconsultation`.

    Content was never the problem — the workload already HOLDS `storage_read_artifact` and the synthesis node
    reads whole minutes with it. Only the node that assigns subjects went without.
    """
    seen = {}

    class Watching(FakeAgent):
        async def run(self, text, **kw):
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    fab = Fabric()
    h = harness(fab, classifier=Watching(CLASSIFICATION),
                tools={"storage_read_artifact": {"text": "Agenda: compare speech providers. "
                                                         "Munsit transliterated English into Arabic script."}})
    try:
        run_spine(W, h, {"pointer": LAB_DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "excerpt" in seen["brief"], "the classifier must see the document, not only its name"
    assert "speech providers" in seen["brief"]["excerpt"]


def test_an_excerpt_is_bounded_so_one_document_cannot_become_the_whole_prompt():
    """A transcript is tens of thousands of words and the classifier needs a paragraph. An unbounded excerpt
    would blow the context, cost per record, and the span that carries it."""
    fab = Fabric()
    seen = {}

    class Watching(FakeAgent):
        async def run(self, text, **kw):
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    h = harness(fab, classifier=Watching(CLASSIFICATION),
                tools={"storage_read_artifact": {"text": "x" * 50_000}})
    try:
        run_spine(W, h, {"pointer": LAB_DOC, "event_id": "01K"})
    finally:
        h.close()
    assert len(seen["brief"]["excerpt"]) <= W.EXCERPT_CHARS


def test_a_document_whose_content_cannot_be_read_is_still_classified():
    """Degrading, never failing: no grant, an unreadable body, a provider outage — the record is still
    catalogued from its metadata, exactly as before. An unclassified artifact is worse than an unlinked one."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION),
                tools={"storage_read_artifact": RuntimeError("no grant")})
    try:
        run_spine(W, h, {"pointer": LAB_DOC, "event_id": "01K"})
    finally:
        h.close()
    assert h.router.called(SemanticTools.vocab_link)        # still linked, still catalogued


def test_a_collab_item_is_fetched_by_handle_before_it_is_read():
    """A `lab` pointer carries an `art://` ref that `storage_read_artifact` takes directly. A `collab` pointer
    carries a HANDLE, which must be streamed into the upload store first — `collab_fetch` mints the ref. Two
    sources, one excerpt, and the fetch is attempted only for the source that needs it."""
    fab, seen = Fabric(), {}

    class Watching(FakeAgent):
        async def run(self, text, **kw):
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    h = harness(fab, classifier=Watching(CLASSIFICATION),
                tools={"collab_fetch": {"ref": "art://store/doc7.txt"},
                       "storage_read_document": "the body of doc7"})
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert h.router.called("collab_fetch"), "a handle must be fetched before it can be read"
    assert h.router.called("collab_fetch")[0]["handle"] == DOC["handle"]
    # ...and the EXCERPT must actually arrive. Asserting only that the fetch happened let a real defect
    # through: `ref_from` defaults to the key `spec_ref` while collab_fetch answers with `ref`, so it
    # raised, `_excerpt`'s degrade-rather-than-fail `except` swallowed it, and every collab document was
    # classified from its file name while the run reported success. A path that is DESIGNED to fail
    # quietly needs a test that asserts the success case produces something, not that it was attempted.
    assert "the body of doc7" in (seen.get("brief") or {}).get("excerpt", "")


def test_a_DOCUMENT_is_read_with_the_document_reader_not_the_artifact_one():
    """Storage has two readers and they refuse each other's files.

    `storage_read_artifact` serves .json/.xml/.svg/.xlsx/.html and REFUSES a document: measured live on
    9 Oct 2026, every `.md` in the pilot library came back "ADR-022-….md is not an artifact; use
    storage_read_document for an upload" — so the whole collab half of the catalogue was still being
    classified from its file name after two sweeps that each reported 93 submitted, 0 failed.

    Documents are most of what a documentation fabric catalogues, so the reader is chosen by KIND
    (`filetypes.kind_for`), and `read_document` takes the cap directly rather than the caller slicing
    a whole file it already paid to decode.
    """
    fab, seen = Fabric(), {}

    class Watching(FakeAgent):
        async def run(self, text, **kw):
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    h = harness(fab, classifier=Watching(CLASSIFICATION),
                tools={"collab_fetch": {"ref": "art://store/ADR-022.md"},
                       "storage_read_document": "# ADR-022\nWe will retry claims intake on failure.",
                       "storage_read_artifact": RuntimeError("the artifact reader must not be asked for a .md")})
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "retry claims intake" in (seen.get("brief") or {}).get("excerpt", "")
    asked = h.router.called("storage_read_document")
    assert asked and asked[0]["max_chars"] == W.EXCERPT_CHARS, "the reader caps it, not the caller"


def test_no_subject_is_a_legal_answer():
    """Nothing rewarded declining, so the model always picked something — and a confident wrong edge is worse
    than no edge, because a person reviewing 57 of them cannot tell which were guesses. An empty `subjects`
    must validate, link nothing, and propose nothing."""
    import json as _json
    from pathlib import Path
    schema = _json.loads((Path(W.__file__).parent / "schemas" / "classification.schema.json").read_text())
    import jsonschema
    jsonschema.validate({"document_type": None, "confidence": 0.1, "subjects": [], "subject_confidence": {},
                         "rationale": "the file name says nothing and the body is not about any concept listed"},
                        schema)

    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": []}))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert not h.router.called(SemanticTools.vocab_link), "no subjects means no link, not an empty link"
    assert not h.router.called(SemanticTools.vocab_propose), "and no candidate parked for a steward"


def test_a_RECLASSIFY_of_a_TYPED_record_raises_no_card_at_all():
    """Re-reading the back catalogue must not bury the queue it exists to make worth working.

    The catalogue measured 7 Oct 2026 held ~90 records classified from their FILE NAMES, with ~40 approvals
    already open. A re-classification ending in `ask_review` like any other run would have raised a card per
    record — a SECOND card for records whose first is still waiting — and the queue would have become
    unusable at the moment its contents finally became worth reading.

    Nothing is lost by staying quiet: subjects live at rung X whichever pass produced them, so whoever opens
    the existing card simply sees the better ones.
    """
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K", "reason": "reclassify",
                         "produced_by": "transcript_to_minutes", "context": "meeting:m1"})
    finally:
        h.close()
    assert not calls(h, ApprovalTools.ask), "a reclassify asks nobody when only the subjects moved"
    assert h.router.called(SemanticTools.vocab_link), "but it still re-links, which is the point"


def test_a_RECLASSIFY_still_asks_when_the_record_gains_a_TYPE_it_did_not_have():
    """The type is a facet a person confirms, so a record acquiring one still goes to somebody.

    Note what this CANNOT do: a type is only ever asserted onto a record that has none, so re-reading a
    typed record never changes it. A model's second opinion can therefore never displace a decided type —
    the quiet path is safe precisely because the loud one is unreachable for anything already settled.
    """
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))      # suggests a decision-record type
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K", "reason": "reclassify", "context": "meeting:m1"})
    finally:
        h.close()
    assert calls(h, ApprovalTools.ask), "a record that gains a type goes back to a person"


def test_an_ORDINARY_run_is_unchanged_and_still_asks():
    """The flag must not leak into the normal path: every artifact that genuinely changed still ends in a
    person's card."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert calls(h, ApprovalTools.ask)


def test_a_subject_the_model_is_GUESSING_at_is_dropped_before_it_becomes_a_link():
    """The judgement half of the same defect the excerpt fixed the plumbing half of.

    Measured 9 Oct 2026, after the classifier could finally read documents: the vocabulary in use went
    from 8 concepts to 47 and the ADRs, screenings and requirements came out right — but a speech-provider
    bake-off's minutes were STILL filed under `Clinical document` and `Encounter`. The excerpt was reaching
    the model; it had read the content and still reached for the nearest concept, because CAFÉ is
    healthcare-shaped and something always looks vaguely close.

    So the model declares a confidence PER SUBJECT — one can be certain while another is a guess, which a
    single number for the whole classification cannot say — and anything below the floor never becomes a
    link. A dropped subject is REPORTED, not silently discarded: a floor nobody can see is a floor nobody
    can tune.
    """
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": ["Triage", "Care Delivery"],
                                           "subject_confidence": {"Triage": 0.91, "Care Delivery": 0.22}}),
                subject_floor=0.6)
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    linked = h.router.called(SemanticTools.vocab_link)
    assert linked and linked[0]["terms"] == ["Triage"], "only the confident subject reaches the link"
    assert "Care Delivery" in json.dumps(out), "the dropped subject is reported, not silently discarded"


def test_the_schema_REQUIRES_a_confidence_for_every_subject_returned():
    """An optional field mentioned once in a prompt is a field a small model ignores.

    Measured 9 Oct 2026: with `subject_confidence` optional, the deployed classifier never emitted it, the
    floor never fired, and the minutes stayed filed under `Clinical document` — the change was inert while
    every test passed. If the pipeline needs the number, the CONTRACT has to ask for it; a prompt alone is
    a request, and the gate is what makes it a requirement.
    """
    import json as _json
    from pathlib import Path as _Path
    import jsonschema
    schema = _json.loads((_Path(W.__file__).parent / "schemas" / "classification.schema.json").read_text())
    assert "subject_confidence" in schema["required"]
    ok = {"document_type": None, "confidence": 0.4, "subjects": ["Triage"], "rationale": "r",
          "subject_confidence": {"Triage": 0.8}}
    jsonschema.validate(ok, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({k: v for k, v in ok.items() if k != "subject_confidence"}, schema)
    jsonschema.validate({**ok, "subjects": [], "subject_confidence": {}}, schema)   # nothing to rate


def test_a_subject_with_no_declared_confidence_is_treated_as_a_GUESS():
    """Once the contract requires the number, a subject missing from it is not an older client being
    generous to — it is a subject the model declined to stand behind, and the floor applies."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": ["Triage", "Care Delivery"],
                                           "subject_confidence": {"Triage": 0.9}}),
                subject_floor=0.6)
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert h.router.called(SemanticTools.vocab_link)[0]["terms"] == ["Triage"]


def test_dropping_every_subject_is_a_legal_outcome_and_links_nothing():
    """The case the whole change exists for: a document about nothing in the vocabulary ends with no
    subjects at all, rather than the nearest healthcare concept."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": ["Triage"],
                                           "subject_confidence": {"Triage": 0.3}}),
                subject_floor=0.6)
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert not h.router.called(SemanticTools.vocab_link), "no confident subject means no link at all"
