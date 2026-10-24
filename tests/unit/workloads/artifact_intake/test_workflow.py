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
from lab.core.semantic.fabric import renderings
from lab.core.semantic.fabric.owners import OwnerMap
from lab.platform.contracts import ARTIFACT_PUBLISH, ApprovalKind, ApprovalTools, SemanticTools, StorageTools
from lab.platform.contracts.fabric import TERM_ITEM
from lab.workloads.artifact_intake import agents as A
from lab.workloads.artifact_intake import workflow as W
from lab.core.validation import GateFailed

MINUTES = {"source": "lab", "ref": "art://run1/meeting-AAMk1.minutes.json"}
DOC = {"source": "collab", "handle": "collab://item/drive-1/doc7", "version": "2"}
DOC_TYPES = {"urn:fabric:scheme:doc-types#minutes": {"label": "Minutes", "alt": [], "produced_by": "transcript_to_minutes"},
             "urn:fabric:scheme:doc-types#decision-record": {"label": "Decision record", "alt": ["ADR"], "produced_by": ""},
             "urn:fabric:scheme:doc-types#requirements-specification": {"label": "Requirements specification",
                                                                        "alt": ["BRS"], "produced_by": ""},
             # the sentinel: the answer "I looked and none of these fits", which is what made a BRS stale
             "urn:fabric:scheme:doc-types#unknown": {"label": "No type fits", "alt": ["none"], "produced_by": ""}}
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

    def __init__(self, similar=None, search=None, concept_hits=None):
        self.rows, self.asserts, self.edges, self.similar_answer = {}, [], [], similar or []
        self.search_answer = search or []
        #: term -> the concept the semantic tier found for it. Anything unlisted is an honest miss.
        self.concept_hits = dict(concept_hits or {})
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

    def concept_answer(self, args: dict) -> dict:
        term = str(args.get("term") or "")
        hit = self.concept_hits.get(term)
        return {"term": term, "concept": hit or "", "label": (hit or "").rsplit("#", 1)[-1],
                "score": 0.6 if hit else 0.2, "margin": 0.09 if hit else 0.004,
                "scheme": "syn", "unavailable": False}

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
            "semantic_search": lambda a: self.search_answer,
            "semantic_concept_match": lambda a: self.concept_answer(a),
            "semantic_store_spec": lambda a: {"spec_ref": f"art://store/{a['name']}"},
            "storage_read_artifact": MINUTES_DOC,
            "collab_item": {"name": "ADR-14 Event bus.docx", "path": "/EA/decisions", "modified": "2026-09-11T00:00:00Z"},
            "approvals_ask": lambda a: {"request_id": "apr-1", "status": "pending", "asked": len(a["items"])},
        }
        t.update(over)
        return {k: v for k, v in t.items() if v is not None}


def _resolve_through(router):
    """`semantic_vocab_resolve` as the real server composes it (`FabricService.vocab_resolve`): link, ask the
    semantic tier about each miss (a failure costs only the suggestion), park the rest. Composed from the
    router's OWN link / match / propose handlers, so each inner call is recorded with the arguments the
    server would pass and every assertion about what reached those tools still means what it did."""
    def data(name, args):
        return router.call(f"srv-{name}", args).data

    def resolve(a):
        link = dict(data("semantic_vocab_link", {"iri": a["iri"], "terms": a["terms"]}) or {})
        proposed = []
        for term in link.get("missed") or []:
            alias_of = ""
            try:
                alias_of = str((data("semantic_concept_match", {"term": term, "scheme": a.get("scheme", "")})
                                or {}).get("concept") or "")
            except Exception:                                    # noqa: BLE001 — a suggestion, never a gate
                alias_of = ""
            parked = data("semantic_vocab_propose", {
                "label": term, "actor": a["actor"], "scheme": a.get("scheme", ""), "proposed_for": a["iri"],
                "alias_of": alias_of, "definition": a.get("definition", "")})
            if isinstance(parked, dict) and parked.get("iri") and a.get("awaiting_author"):
                parked = {**parked, "state": "awaiting-author"}   # as the server marks an extracted term
            proposed.append(parked)
        return {**link, "proposed": proposed}
    return resolve


def harness(fab: Fabric, *, classifier=None, synthesis=None, extractor=None, extract_first=False,
            threshold=0.75, default_label="", tools=None,
            owners=None, vocabulary="", subject_floor=0.0):
    # `None` for a tool = the gateway does NOT expose it (a missing grant, a version skew): unlisted, not just unanswered
    hidden = {k for k, v in (tools or {}).items() if v is None}
    router = Router(fab.tools(**(tools or {})), hidden=hidden, full=True)
    router.tools.setdefault("semantic_vocab_resolve", _resolve_through(router))
    ctx = spine(W, router)
    h = ctx.__enter__()
    h.cfg.update({"agents": {k: v for k, v in (("classifier", classifier), ("synthesis", synthesis),
                                               ("extractor", extractor)) if v},
                  "schemas": {k: A.schema(k) for k in A.SKILL},
                  "extract_first": extract_first,
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
    proposal = calls(h, SemanticTools.vocab_propose)[0]
    assert proposal["label"] == "Unknown Term"
    # ...and WHICH artifact used the word. `vocab_propose` accumulates `proposed_for` so one term is ONE
    # candidate carrying the documents behind it; the caller never passed it, so every candidate in the
    # live register was countless and provenance-less (measured 12 Oct 2026: 45 candidates, 0 with either).
    # Two features silently did nothing as a result — the frequency threshold reads a count that was always
    # null, so every term was asked on first sight (58 open cards), and admission propagates to exactly
    # `proposed_for`, so admitting a concept re-matched no document at all.
    assert proposal["proposed_for"] == out["artifact_iri"], "a candidate must name the artifact that used it"
    # synthesise: one draft per decision, its type a FACT (C), referencing the minutes (C)
    assert out["draft_refs"] == ["art://store/00000000000000000000000001.d1.decision-record.json"]
    # the draft RECORDS WHAT MADE IT. The source record's upsert passes `produced_by` and the draft's did
    # not, so every synthesised draft was catalogued as an orphan — 66 of them live, measured 12 Oct 2026.
    # An orphaned lab record is what `fabric_hygiene.is_working_file` reads as a working file, so the
    # fabric's own products were one catalogue-wide hygiene pass away from being withdrawn.
    drafts = [c for c in calls(h, SemanticTools.catalog_upsert)
              if str((c.get("pointer") or {}).get("ref", "")).endswith(".decision-record.json")]
    assert drafts, "the run drafted nothing, so this assertion proves nothing"
    assert all(d.get("produced_by") == "artifact_intake" for d in drafts), [d.get("produced_by") for d in drafts]
    draft = [a for a in fab.asserts if a["field"] == "document_type" and a["iri"] != out["artifact_iri"]][0]
    assert (draft["value"], draft["rung"], draft["method"]) == (W.DECISION_RECORD, "C", "drafted-by-fabric")
    # the draft references the minutes AND is synthesised from them — the second is what rung D derives the context from
    assert [(e["predicate"].rsplit("#", 1)[-1], e["rung"]) for e in fab.edges] == [("references", "C"), ("synthesisedFrom", "C")]
    # the question: draft-review, with the drafts attached and the publish continuation
    ask = calls(h, ApprovalTools.ask)[0]
    assert ask["kind"] == ApprovalKind.DRAFT_REVIEW.value and ask["process"] == "artifact_intake"
    # The INVARIANT, not the exact list: `document_type` is the one item every owner card carries, and the
    # conditional ones (owner, overlap, context, and one per subject) come and go with the record. Pinning
    # the whole list made every added item look like a regression — it broke on the subject items and
    # caught nothing, which is what an exact-set assertion does on an additive change.
    labels = [i["label"] for i in ask["items"]]
    assert labels[0] == "document_type" and ask["fields"] == ["value"]
    assert not {"owner", "overlap", "context"} & set(labels), "this record needs none of the conditional ones"
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
    # vocab_link IS called with no terms — that is how an empty answer supersedes what came before; what
    # must not happen is a LINK being made or a candidate parked.
    assert h.router.called(SemanticTools.vocab_link)[0]["terms"] == []
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
    assert h.router.called(SemanticTools.vocab_link)[0]["terms"] == [], \
        "no confident subject means no LINK — and the empty call is what retracts any earlier one"


def test_a_structured_ARTIFACT_is_its_own_content():
    """A lab artifact has no `text` key — it IS the text.

    `storage_read_artifact` hands back a `.json` byte-faithfully, so a minutes record parses into
    {"summary": …, "concepts": […]} with neither `text` nor `content`. `_excerpt` looked for exactly those
    two keys, found neither, and returned "" — no exception, so nothing logged, so the classifier saw a
    file name and guessed. Measured 9 Oct 2026: it is why the meeting minutes kept coming back
    `Encounter, Clinical document` even after four other causes were fixed and after an A/B proved every
    candidate model declines this document when actually shown it.

    Fifth distinct cause of one symptom, and the first with no error at all behind it.
    """
    fab, seen = Fabric(), {}

    class Watching(FakeAgent):
        async def run(self, text, **kw):
            seen["brief"] = json.loads(text)
            return await super().run(text, **kw)

    minutes = json.dumps({"summary": "mostly greetings and a check-in", "decisions": [], "actions": []})
    h = harness(fab, classifier=Watching(CLASSIFICATION), tools={"storage_read_artifact": minutes})
    try:
        run_spine(W, h, {"pointer": LAB_DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "mostly greetings" in (seen.get("brief") or {}).get("excerpt", ""), \
        "a structured artifact with no text key must still reach the classifier"


def test_an_EMPTY_excerpt_says_so_even_though_nothing_raised():
    """The instrument this path kept lacking. Four of the five causes announced themselves because they
    RAISED; this one returned "" quietly, and silence is the one thing a degrade-by-design path must never
    do when it degrades."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), tools={"storage_read_artifact": json.dumps({})})
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            run_spine(W, h, {"pointer": LAB_DOC, "event_id": "01K"})
    finally:
        h.close()
    assert "no excerpt" in buf.getvalue() or "empty excerpt" in buf.getvalue(), \
        "an empty excerpt must be reported, or it reads as a classifier fault for ever"


def test_a_classifier_that_now_says_NOTHING_APPLIES_retracts_what_it_said_before():
    """Deciding a record is about nothing must be expressible, and it was not.

    `vocab_link` supersedes the extracted subjects — but it was only called `if subjects`, so an empty
    answer skipped it entirely and the previous links survived. Measured 9 Oct 2026: the classifier
    returned `subjects: []` for a bake-off transcript, with a rationale saying nothing in it matched the
    vocabulary, and the record kept `Person, Party, Location, Location` from the run before.

    The complement of the supersede fix: that one made a NARROWER reading replace a wider one, and this
    one makes the narrowest reading of all — none — reach the graph. Without it a record can only ever
    gain subjects, and the honest empty answer the whole exercise was for is silently discarded.
    """
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": [], "subject_confidence": {}}))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    called = h.router.called(SemanticTools.vocab_link)
    assert called, "an empty answer must still reach vocab_link, or nothing can be taken back"
    assert called[0]["terms"] == [], "with no terms, so every extracted subject is superseded"


def test_a_run_with_NO_classifier_leaves_the_subjects_alone():
    """Absent is not empty, one level up. A deployment with no classifier agent must not read its silence
    as 'nothing applies' and strip a record somebody else's run classified correctly."""
    fab = Fabric()
    h = harness(fab)                                   # no classifier at all
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K"})
    finally:
        h.close()
    assert not h.router.called(SemanticTools.vocab_link), "no classifier means no opinion, not an empty one"


# ------------------------------------------------------- a prior confirmation that a vocabulary change made stale

UNKNOWN_TYPE = "urn:fabric:scheme:doc-types#unknown"
REQS_TYPE = "urn:fabric:scheme:doc-types#requirements-specification"


def _typed(fab: Fabric, iri: str):
    """A record that already CARRIES a type when intake re-reads it — the shape a re-submitted document has."""
    return {"semantic_catalog_upsert": lambda a: {**fab.upsert(a), "document_type": iri}}


def test_a_DIFFERING_classification_is_offered_beside_the_recorded_value():
    """Measured 9-10 Oct 2026, and the reason this exists: `BRS.md` arrived when no document type fitted a
    requirements specification, the classifier honestly returned the sentinel, and a reviewer confirmed it.
    The scheme then GAINED `requirements-specification`; the file was edited, so the record went back to
    pending and intake re-ran, and the classifier read it correctly. The card still built its item from the
    recorded value alone — `suggested: No type fits (fact)` — so the better answer never reached the person,
    who confirmed the stale one again while the card's own justification text said "BRS".

    A human's answer outranking a model's guess is right in general; what it cannot see is that a VOCABULARY
    change made that answer stale. So the recorded value stays the DEFAULT and the differing reading is
    OFFERED beside it, in the labels a person reads rather than IRIs.
    """
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": REQS_TYPE,
                                           "rationale": "names itself a BRS"}),
                tools=_typed(fab, UNKNOWN_TYPE))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K", "context": "meeting:m1"})
    finally:
        h.close()
    samples = calls(h, ApprovalTools.ask)[0]["items"][0]["samples"]
    assert "No type fits" in samples[0] and "(fact)" in samples[0], "the confirmed value is still the default"
    offered = next(s for s in samples if "now reads as" in s)
    assert "Requirements specification" in offered, "and the better reading is offered, by its label"
    assert "doc-types#" not in " ".join(samples), "a person reads labels, never IRIs"
    assert any("names itself a BRS" in s for s in samples), "with the classifier's own rationale"
    # The model's second opinion is OFFERED, never written: a decided type is a person's to change.
    assert [a for a in fab.asserts if a["field"] == "document_type"] == []


def test_an_IDENTICAL_classification_changes_nothing_about_the_card():
    """Only a DIFFERENCE is worth a reviewer's attention. A classifier that agrees with the record must leave
    the item exactly as it was, or every card grows a line that says nothing."""
    fab = Fabric()
    agree = {**CLASSIFICATION, "document_type": REQS_TYPE}
    h = harness(fab, classifier=FakeAgent(agree), tools=_typed(fab, REQS_TYPE))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K", "context": "meeting:m1"})
    finally:
        h.close()
    samples = calls(h, ApprovalTools.ask)[0]["items"][0]["samples"]
    assert samples == [f"suggested: Requirements specification (fact)", CLASSIFICATION["rationale"]]


def test_a_type_the_producing_PROCESS_decided_is_not_put_to_a_vote():
    """A lab product's type is deterministic — the process that made it says what it is (rung C). A classifier
    reading the content differently is not new evidence about that, and offering it would put a second opinion
    on every minutes card for nobody's benefit."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))      # suggests a decision-record...
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:m1",
                         "produced_by": "transcript_to_minutes"})      # ...on a record typed Minutes by its producer
    finally:
        h.close()
    samples = calls(h, ApprovalTools.ask)[0]["items"][0]["samples"]
    assert samples == ["suggested: Minutes (fact)", CLASSIFICATION["rationale"]]


def test_a_RECLASSIFY_sweep_still_asks_nobody_when_only_the_READING_moved():
    """The queue-flooding rule is unchanged: a sweep over the back catalogue raises no card, even where the
    new reading differs. A person sees the difference when the artifact itself changes and intake re-runs —
    which is the republication case this whole item is for."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "document_type": REQS_TYPE}),
                tools=_typed(fab, UNKNOWN_TYPE))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01K", "reason": "reclassify", "context": "meeting:m1"})
    finally:
        h.close()
    assert not calls(h, ApprovalTools.ask)


def test_a_CITED_document_becomes_a_references_edge_at_the_extracted_rung():
    """Impact walks INBOUND over `references`, and until 12 Oct 2026 the only thing that produced that
    edge was a synthesised draft pointing at its source. So a human-authored document that cited another
    in prose produced nothing: measured on three eRx documents that cite each other by name,
    `references=0` on all of them, and `semantic_impact` over any of them returned 0 records — not
    because the graph was empty but because nothing had ever looked.

    The classifier now reports what the excerpt CITES, verbatim; a bounded search proposes candidates and
    `citations.resolve` decides. The edge is EXTRACTED, which is what it is — read out of the text, never
    confirmed by anybody — so impact reads it (trusted rungs) while nobody mistakes it for a fact."""
    fab = Fabric(search=[{"iri": "urn:fabric:artifact:CITED", "title": "ADR-041-prescription-identifier.md"}])
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION,
                                           "references": ["ADR-041 Prescription identifier format"]}))
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    refs = [e for e in fab.edges if str(e.get("predicate", "")).endswith("references")]
    assert refs, "a cited document must become a references edge"
    assert refs[0]["object"] == "urn:fabric:artifact:CITED"
    assert refs[0]["subject"] == out["artifact_iri"]
    assert refs[0]["rung"] == "X", "a citation is EXTRACTED — read from the text, confirmed by nobody"


def test_a_citation_the_rule_CANNOT_PLACE_is_dropped_rather_than_guessed():
    """A wrong edge is worse than a missing one: it puts a document inside the blast radius of a change
    that cannot affect it, and nothing on screen would say so. Search surfacing a plausible candidate is
    not proof — the acronym `eRx-BRS.md` cannot be shown to be what 'eRx Business Requirements
    Specification' names, so no edge is written even though search ranked it first."""
    fab = Fabric(search=[{"iri": "urn:fabric:artifact:BRS", "title": "eRx-BRS.md"}])
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION,
                                           "references": ["eRx Business Requirements Specification"]}))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    assert not [e for e in fab.edges if str(e.get("predicate", "")).endswith("references")]


def test_the_review_card_SAYS_WHICH_SUBJECTS_THE_RUN_TOOK_AWAY():
    """A reviewer confirming a record is shown what it gained and never what it lost.

    `vocab_link` replaces the EXTRACTED subject set wholesale, so a re-read silently retracts whatever it
    no longer stands behind. The reclassify branch reports `retracted` on the run, but the approval
    summary omits it — so the one person asked to confirm the record is the one person not told. Named,
    not counted, for the same reason `dropped_unsure` is: a reviewer can only object to a removal they
    can see."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    assert "retracted" in out["summary"], out["summary"]


#: One span IS in the minutes excerpt (which is the artifact JSON, so its text appears verbatim) and one
#: is not — the pair the grounding rule exists to tell apart.
EXTRACTION = {"terms": [
    {"term": "legacy portal retirement", "evidence_span": "Retire the legacy portal", "salience": 0.9},
    {"term": "a thing the document never says", "evidence_span": "not in the excerpt at all", "salience": 0.8},
]}


def test_EXTRACT_FIRST_grounds_each_term_and_drops_the_ungrounded_one():
    """The inversion's reading step. A term may be INFERRED — naming what a document is about without
    using its words is the point — but the evidence may not. So a span that is not in the excerpt takes
    its term with it, and the run says how many went that way rather than losing them silently."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=FakeAgent(EXTRACTION),
                synthesis=FakeAgent(RECORDS), extract_first=True)
    try:
        out = run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                               "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    linked = calls(h, SemanticTools.vocab_link)
    assert linked, "the grounded term must still reach the vocabulary"
    assert "legacy portal retirement" in linked[0]["terms"]
    assert "a thing the document never says" not in linked[0]["terms"]
    assert out["summary"]["ungrounded"] == 1


def test_EXTRACT_FIRST_with_NOTHING_grounded_does_not_retract_the_record_s_subjects():
    """The hazard that shaped this branch. `vocab_link` replaces the EXTRACTED subject set wholesale, and
    `_excerpt` returns "" on ANY failure — a missing grant, a provider outage, an empty artifact. Composed
    naively, one storage blip means zero grounded terms, an empty `vocab_link`, and EVERY subject on that
    record retracted. Run across the estate under a reclassify sweep, that erases the subject graph.

    So "I could not ground anything" is not "I grounded nothing": the first leaves the prior set standing
    and says so, and only the second is allowed to replace it."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION),
                extractor=FakeAgent({"terms": [{"term": "an unevidenced reading",
                                               "evidence_span": "nowhere in the text", "salience": 0.5}]}),
                extract_first=True)
    try:
        out = run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    assert not calls(h, SemanticTools.vocab_link), "an all-ungrounded run must not touch the subject set"
    assert out["summary"]["ungrounded"] == 1


def test_WITHOUT_the_flag_nothing_changes():
    """Flag-guarded coexistence: the extractor is built and not consulted, so the old path is bit-for-bit
    what it was and reverting is an env change rather than a redeploy."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=FakeAgent(EXTRACTION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    assert calls(h, SemanticTools.vocab_link)[0]["terms"] == ["Care Delivery", "Unknown Term"]


def test_a_term_no_LABEL_matched_but_a_DEFINITION_does_becomes_an_ALIAS_candidate():
    """The third outcome, and the one that did not exist before. A term whose words match no label can
    still be a word for a concept the vocabulary already holds — measured 17 Oct, ZERO of 30 terms on
    real prose matched a label, so without this tier every one of them would become a proposal to invent
    a concept that already exists.

    An alias is a cheap question (`is this another word for X?`) and a new concept is an expensive one
    (`what does it mean, and where does it sit?`). Asking the expensive one by default is what made 58
    cards out of 45 terms."""
    fab = Fabric(concept_hits={"Unknown Term": "urn:lab:semantic:domain:syn#ClinicalReview"})
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    proposed = calls(h, SemanticTools.vocab_propose)
    assert proposed, "the term still has to reach the register"
    assert proposed[0]["alias_of"] == "urn:lab:semantic:domain:syn#ClinicalReview"


def test_a_term_NOTHING_matched_is_proposed_with_no_target_at_all():
    """The honest miss stays honest. A candidate carrying a target nobody can defend would put a
    steward's `existing:<id>` answer one tap away from a relationship the fabric invented."""
    fab = Fabric()                                   # no concept hits at all
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    proposed = calls(h, SemanticTools.vocab_propose)
    assert proposed and not proposed[0].get("alias_of")


def test_a_MINUTES_record_is_read_as_a_TRANSLATED_TRANSCRIPT_not_as_structured_json():
    """The sharp case for the rendering ladder. A minutes artifact is the lab's own JSON — `structured` by how
    this node reads it — but its words are a machine translation of speech, two rungs further from the
    meeting than a document is from itself. Calling it `structured` would be true of the file and false about
    the evidence, so the WRITING process's rendering wins: evidence is only as strong as its weakest hop."""
    assert W._rendering_for("transcript_to_minutes", "structured") == "transcript-translated"
    assert W._rendering_for("meeting_to_transcript", "structured") == "transcript"
    assert W._rendering_for("", "document") == "document", "a document nobody machine-read is its own words"
    assert W._rendering_for("artifact_intake", "structured") == "structured"


def test_every_declared_process_rendering_is_one_the_LADDER_knows():
    """Two homes, one vocabulary: a typo here would be refused by the facet's shape at the gateway, after the
    run had already done its reading."""
    assert set(W.RENDERING_BY_PROCESS.values()) <= set(renderings.RENDERINGS)
    assert all(renderings.weaker(r, than="document") for r in W.RENDERING_BY_PROCESS.values()), \
        "a process is listed here only because it reads the world through a machine"


def test_a_RECLASSIFIED_record_keeps_its_WEAKEST_reading(monkeypatch):
    """The hole in "one run produces one excerpt": subjects ACCUMULATE on a record, and a record can be read
    more than once. Run 1 reads a minutes JSON and links three concepts grounded in a machine translation of
    speech; a later run reads the document body and would SUPERSEDE the rendering with `document` — leaving
    those three concepts on a record that claims the artifact's own words.

    So the facet is monotone downward: the weakest reading ever recorded wins, because a record is only as
    strong as the weakest evidence on it. This is also what gives the ladder's ordering a production reader —
    a rank nobody consults is the defect this phase set out to avoid."""
    assert W._weakest("document", "transcript-translated") == "transcript-translated"
    assert W._weakest("transcript-translated", "document") == "transcript-translated"
    assert W._weakest("", "document") == "document", "nothing recorded yet is not evidence of strength"
    assert W._weakest("transcript", "") == "transcript"
    assert W._weakest("", "") == ""


def _subject_items(ask):
    return [i for i in ask["items"] if i["label"].startswith("subject:")]


#: four grounded terms of descending centrality, each matching a DISTINCT concept — the fake's default
#: `vocab_link` answers one concept IRI for every term, which would collapse four items onto one label.
FOUR = {"terms": [{"term": t, "evidence_span": "We agreed.", "salience": sal}
                  for t, sal in (("Prescription", 0.9), ("Dispense", 0.7),
                                 ("Pharmacy", 0.6), ("Identifier", 0.2))]}
LINK_EACH = {"semantic_vocab_link": lambda a: {
    "linked": [{"term": t, "scheme": "syn", "concept": f"urn:c#{t}", "label": t} for t in a["terms"]],
    "missed": []}}


def _ask_with(extraction, **over):
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=FakeAgent(extraction),
                extract_first=True, tools={**LINK_EACH, **over})
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                         "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
        return calls(h, ApprovalTools.ask)[0]
    finally:
        h.close()


def test_the_OWNER_is_asked_about_the_subjects_MOST_CENTRAL_to_their_document():
    """A subject is asserted at X by a label match on a grounded span — already high confidence — so the
    card's job is not to re-check all of them. It is to let the person who knows the document promote the
    ones that matter to H, where a later re-read cannot quietly take them away.

    Ranked by SALIENCE, how central the extractor found a term to THIS document, and CAPPED: asking about
    every subject of every record is the forty-fields mistake the steward's batch card already paid for.
    The rest stand at X, unasked and unharmed — nothing is tracked and nothing is lost, which is what makes
    a cap safe here and unsafe on the candidate register, where an unasked term is forgotten."""
    ask = _ask_with(FOUR)
    items = _subject_items(ask)
    assert [i["label"] for i in items] == [f"urn:c#{t}" and f"subject:urn:c#{t}"
                                           for t in ("Prescription", "Dispense", "Pharmacy")]
    assert "keep" in items[0]["samples"][0] and "drop" in items[0]["samples"][0]
    assert "Prescription" in items[0]["samples"][0], "the label a person reads, not only the id"
    assert "Identifier" in ask["prompt"], "the ones not asked about are NAMED, never silently dropped"


def _ask_classifier_only(subjects):
    """The flag-OFF path: the CLASSIFIER supplies the subjects, so no salience exists for any of them —
    the extraction schema requires one, so this case cannot arise through the extractor."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent({**CLASSIFICATION, "subjects": subjects,
                                           "subject_confidence": {t: 0.9 for t in subjects}}),
                tools=LINK_EACH)
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                         "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
        return calls(h, ApprovalTools.ask)[0]
    finally:
        h.close()


def test_no_salience_still_caps_and_orders_stably():
    """With the flag off the classifier supplies the subjects and nothing declares salience. The cap still
    holds, and the order falls back to the label — so two runs of one record ask the same question, which a
    ranking keyed on dict order would not."""
    order = ["Pharmacy", "Dispense", "Prescription", "Identifier"]
    first = [i["label"] for i in _subject_items(_ask_classifier_only(order))]
    assert first == [f"subject:urn:c#{t}" for t in ("Dispense", "Identifier", "Pharmacy")]
    assert [i["label"] for i in _subject_items(_ask_classifier_only(list(reversed(order))))] == first


def test_a_record_with_no_subjects_is_asked_about_none():
    ask = _ask_with({"terms": []})
    assert _subject_items(ask) == []


def test_the_EXTRACTOR_IS_SHOWN_NO_VOCABULARY_which_is_its_whole_point():
    """The inversion's defining property, and the one failure its ADR says nothing will catch.

    A closed set ANCHORS the answer — `UseCase` on 37 of the 40 records carrying any subject — so the
    extractor says what a document is about IN ITS OWN WORDS and the vocabulary is matched afterwards,
    deterministically. Hand it the concept list "for context" and the design is taxonomy-first again with
    an extra model call, every test still passing.

    This is that test. It reads the PROMPT, because that is the only place the property is real."""
    fab = Fabric()
    extractor = FakeAgent(EXTRACTION)
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=extractor,
                synthesis=FakeAgent(RECORDS), extract_first=True, vocabulary="cafe")
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                         "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    assert extractor.prompts, "the extractor ran"
    brief = json.loads(extractor.prompts[0])
    assert "concepts" not in brief, "the vocabulary must never reach the extractor"
    assert "document_types" not in brief, "nor the closed type set — that is the classifier's question"
    assert brief.get("excerpt"), "it is shown the TEXT, which is all it needs"
    # ...and the classifier still gets both, because being shown the options is right for a closed set.
    classifier_brief = json.loads(calls_prompt(h, "classifier"))
    assert classifier_brief.get("concepts") is not None and classifier_brief.get("document_types")


def calls_prompt(h, kind):
    return h.cfg["agents"][kind].prompts[0]


def test_the_classifier_s_CONFIDENCE_FLOOR_never_silently_empties_an_EXTRACTED_subject_set():
    """The floor gates a CLASSIFIER's confidence in a subject it chose from a list. An extracted term is
    not in that map at all, so every one scores 0.0 and a shipped floor of 0.6 drops the lot — leaving
    `vocab_link` called with an empty list, which RETRACTS every rung-X subject on the record.

    That is the estate-wide erasure the blind guard was written to stop, arriving through a different
    door: the guard asks whether anything GROUNDED, and these terms grounded fine before the floor ate
    them. Salience is the extract-first dial and it is a different quantity — the ADR refuses to reuse
    this one for it."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=FakeAgent(EXTRACTION),
                synthesis=FakeAgent(RECORDS), extract_first=True, subject_floor=0.6)
    try:
        out = run_spine(W, h, {"pointer": MINUTES, "event_id": "01J", "context": "meeting:AAMk1",
                               "produced_by": "transcript_to_minutes", "requester": "a@x.org"})
    finally:
        h.close()
    linked = calls(h, SemanticTools.vocab_link)
    assert linked, "the link call must still happen"
    assert linked[0]["terms"] == ["legacy portal retirement"], \
        f"the grounded extracted term survives the classifier's floor, got {linked[0]['terms']}"
    assert out["summary"]["subjects"] >= 1


def test_a_run_that_READ_NOTHING_has_no_opinion_about_subjects():
    """The blind guard's own motivating case, through the one route it did not cover. `_excerpt` returns ""
    on ANY failure — a missing grant, a provider outage, an empty artifact — and an extractor shown no text
    may honestly answer `{"terms": []}`, which is schema-valid. Then `ungrounded == 0` and `grounded_any`
    is False, so the old condition (`ungrounded > 0 and not grounded_any`) read it as "it ran and found
    nothing" and called `vocab_link` with an empty list — retracting every rung-X subject on the record.

    A run that read nothing has no opinion, whatever the model answered."""
    fab = Fabric()
    # An EMPTY structure: `_excerpt` reads it, finds "{}", and reports nothing readable — the same ("", "")
    # a missing grant or a provider outage produces, without hiding a tool preflight requires.
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), extractor=FakeAgent({"terms": []}),
                extract_first=True, tools={"storage_read_artifact": {}})
    try:
        run_spine(W, h, {"pointer": MINUTES, "event_id": "01J"})
    finally:
        h.close()
    assert calls(h, SemanticTools.vocab_link) == [], \
        "no excerpt means no opinion — the prior subjects must stand"


def test_a_DIAGRAMS_ARROWS_become_relation_questions_for_a_steward():
    """The ontology queue's other producer, and the sharper of the two. A diagram's boxes are terms and
    its arrows are relations, so it is the one artifact that says how the things a corpus is about are
    CONNECTED rather than just which they are.

    It proposes a QUESTION, never a relation: the arrow says two concepts connect and not how, and a
    predicate the fabric invented would be an edge no author drew — which the derived rung would then
    reason over as if somebody had."""
    fab = Fabric()
    arrows = {"connectors": [{"from": "Prescription", "to": "Prescription item", "label": "contains"},
                             {"from": "Prescription", "to": "Nowhere", "label": "feeds"}]}
    cands = {"candidates": [{"subject": "Prescription", "predicate": "contains",
                             "object": "PrescriptionItem", "arrows": 1, "unnamed": False}],
             "gaps": ["Nowhere"]}
    # A REAL handle: `collab://item/<driveId>/<itemId>`, whose last segment is a Graph id with no
    # extension. The kind comes from the TITLE, which is what `collab_item` actually reports — keying it
    # off the handle made every collab-sourced artifact look like "not a diagram".
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION),
                tools={"storage_read_vsdx": arrows,
                       "collab_item": {"name": "eRx context map.vsdx", "path": "/EA",
                                       "modified": "2026-10-19T00:00:00Z"},
                       "collab_fetch": {"ref": "art://up/eRx context map.vsdx"},
                       "semantic_vocab_relation_candidates": cands,
                       "semantic_vocab_relation_propose": {"iri": "urn:fabric:relation-q:1"}},
                vocabulary="cafe")
    try:
        run_spine(W, h, {"pointer": {"source": "collab", "handle": "collab://item/b!drive/01ITEMID"},
                         "event_id": "01J"})
    finally:
        h.close()
    proposed = calls(h, SemanticTools.relation_propose)
    assert proposed, "the arrow reached the ontology queue"
    assert (proposed[0]["subject"], proposed[0]["predicate"], proposed[0]["object"]) == (
        "Prescription", "contains", "PrescriptionItem")
    assert "eRx context map.vsdx" in proposed[0]["evidence"], "a steward is told which diagram drew it"
    # FR-7: the question names WHO proposed it and the ARTIFACT that drew it, as structured evidence
    assert proposed[0]["actor"] == "artifact-intake"
    assert proposed[0]["proposed_for"].startswith("urn:fabric:artifact:")
    # ...and storage was handed the RESOLVED ref, never the handle, which it cannot read
    assert calls(h, StorageTools.read_vsdx)[0]["ref"].startswith("art://")


def test_a_document_that_is_NOT_a_diagram_proposes_no_relations():
    """The read costs a grant and a round trip, so it is attempted only for a diagram."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION), vocabulary="cafe")
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    assert calls(h, SemanticTools.relation_propose) == []
    assert calls(h, StorageTools.read_vsdx) == []


def test_a_term_EXTRACTED_from_the_document_is_put_to_its_AUTHOR_on_the_owner_card():
    """FR-10: a term read out of the document waits for the author — it is parked `awaiting_author` and
    the owner's own review card asks confirm / rename:<word> / remove, before any steward is asked."""
    fab = Fabric()
    h = harness(fab, classifier=FakeAgent(CLASSIFICATION))
    try:
        run_spine(W, h, {"pointer": DOC, "event_id": "01J"})
    finally:
        h.close()
    (resolve,) = calls(h, SemanticTools.vocab_resolve)
    assert resolve["awaiting_author"] is True
    ask = calls(h, ApprovalTools.ask)[0]
    terms = [i for i in ask["items"] if i["label"].startswith(TERM_ITEM)]
    assert terms and terms[0]["choices"] == ["confirm", "remove"]
    assert "rename:" in terms[0]["samples"][0]
