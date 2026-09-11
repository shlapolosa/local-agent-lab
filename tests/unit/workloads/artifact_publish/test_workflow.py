"""`artifact_publish` — a reviewed record is baselined and re-indexed. Deterministic; the promotion happened at
the gate. What matters: an unapproved approval releases nothing, the baseline names a version, the index is
best effort, and the consumer forwards both inputs."""
import asyncio
from types import SimpleNamespace

import pytest

from fixtures.workflow import Router, run_spine, spine
from lab.platform.contracts import ARTIFACT_PUBLISH, PROCESSES, SemanticTools
from lab.workloads.artifact_publish import consumer, host
from lab.workloads.artifact_publish import workflow as W

IRI = "urn:fabric:artifact:01J"
ROW = {"iri": IRI, "title": "ADR-14", "document_type": "urn:fabric:scheme:doc-types#decision-record",
       "pointer": {"source": "collab", "handle": "collab://item/d/1"}, "state": "pending",
       "links": [{"predicate": "documentType", "rung": "H", "object": "x"}, {"predicate": "subject", "rung": "H", "object": "urn:c#Care"}]}


def tools(**over):
    t = {"approvals_get": {"request_id": "apr-1", "status": "approved", "decision": "approve", "decided_by": "maria@x", "decided_at": "2026-09-11T10:00:00Z"},
         "semantic_catalog_get": ROW,
         "semantic_catalog_state": lambda a: {**ROW, "state": a["state"], "baseline_version": a["baseline_version"]},
         "semantic_embed": {"iri": IRI, "model": "m", "dim": 8},
         "collab_item": {"name": "ADR-14.docx", "modified": "2026-09-10T09:00:00Z"}}
    t.update(over)
    return {k: v for k, v in t.items() if v is not None}


def run(**over):
    router = Router(tools(**over), full=True)
    with spine(W, router) as h:
        out = run_spine(W, h, {"artifact_iri": IRI, "approval_id": "apr-1"})
    return out, router


def test_an_approved_review_baselines_the_record_and_reindexes_it():
    out, router = run()
    state = router.called(SemanticTools.catalog_state)[0]
    assert (state["state"], state["baseline_version"]) == ("published", "2026-09-10T09:00:00Z")   # the item's stamp
    assert out["baseline"] == {"version": "2026-09-10T09:00:00Z", "approved_by": "maria@x", "at": "2026-09-11T10:00:00Z"}
    assert router.called(SemanticTools.embed)[0]["text"] == "ADR-14 · decision-record · Care"
    assert out["promoted"] == 2 and "projection_ref" not in out          # the projector annotates it later


def test_a_pointer_version_wins_and_the_decision_time_is_the_last_resort():
    out, _ = run(semantic_catalog_get={**ROW, "pointer": {"source": "collab", "handle": "collab://item/d/1", "version": "7"}})
    assert out["baseline"]["version"] == "7"
    out, _ = run(collab_item=RuntimeError("no grant"))
    assert out["baseline"]["version"] == "2026-09-11T10:00:00Z"


def test_an_unapproved_approval_releases_nothing():
    with pytest.raises(RuntimeError, match="not approved"):
        run(approvals_get={"request_id": "apr-1", "status": "pending", "decision": None})
    with pytest.raises(RuntimeError, match="no catalog record"):
        run(semantic_catalog_get=None if False else lambda a: None)


def test_the_index_is_best_effort():
    out, _ = run(semantic_embed=RuntimeError("no embedder"))
    assert "no embedder" in out["index_note"] and out["baseline"]["version"]


def test_consumer_forwards_both_inputs_and_the_process_is_registered():
    assert consumer.PROCESS in PROCESSES and PROCESSES[consumer.PROCESS].group == "wf-artifact-publish"
    assert ARTIFACT_PUBLISH.external is False
    seen = {}

    async def fake(root, artifact_iri, approval_id, *, on_trace=None):
        seen.update(artifact_iri=artifact_iri, approval_id=approval_id); return {"baseline": {}}
    saved, consumer.run_once = consumer.run_once, fake
    try:
        asyncio.run(consumer._run(object(), SimpleNamespace(inputs={"artifact_iri": IRI, "approval_id": "apr-1"}), None))
    finally:
        consumer.run_once = saved
    assert seen == {"artifact_iri": IRI, "approval_id": "apr-1"}
    assert set(seen) == {f.name for f in ARTIFACT_PUBLISH.inputs}
    assert "apr-1" in consumer._describe(SimpleNamespace(inputs={"artifact_iri": IRI, "approval_id": "apr-1"}))
    assert host.run_fields({"artifact_iri": IRI, "baseline": {"version": "1"}}) == {"artifact_iri": IRI, "baseline": {"version": "1"}}
