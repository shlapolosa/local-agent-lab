"""The OpenAI vector-store façade — the second transport over the ONE read path.

What is worth testing is not that it speaks the OpenAI shape (LiteLLM's own type would reject it
otherwise) but that going through this door is not going AROUND governance: no run identity means
no read, an exact artifact is refused rather than ranked, and a hit names the record an exact read
can follow. Offline: the fake library, Starlette's test client, no gateway.
"""
import json

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from lab.core.reference.model import ArtifactKind
from lab.substrate.mcpauth import BearerAuthMiddleware
from lab.substrate.mcp.reference import server as S
from lab.substrate.mcp.reference import vectorstore

MAP = "capability-map-healthcare-provider-v2.0"


def _map():
    return SeededArtifact(
        artifact_id=MAP, kind=ArtifactKind.RECORD, title="Healthcare capability map",
        record_type="capability", retrieval="vector",
        records=[{"record_id": "rec-9", "id": "L3.4", "parent": "L2.1", "level": "3"}],
        passages=[{"passage_id": "psg-9", "text": "Care Delivery > Triage. Sorting by urgency",
                   "heading_path": ["id=L3.4"], "record_id": "rec-9",
                   "key": {"id": "L3.4", "parent": "L2.1", "level": "3"}},
                  {"passage_id": "psg-2", "text": "Finance > Billing. Invoicing payers",
                   "heading_path": ["id=L3.9"], "record_id": "rec-2"}])


def _register():
    return SeededArtifact(artifact_id="guardrail-mapping", kind=ArtifactKind.RECORD,
                          title="Risk mapping", record_type="risk-class",
                          records=[{"record_id": "rec-e2", "risk_class": "E2"}])


@pytest.fixture
def api():
    fake = FakeReferenceLibrary([_map(), _register()])
    with S.server.container.reference.override(fake):
        app = Starlette(routes=vectorstore.routes(S.server, max_hits=S.MAX_HITS))
        yield TestClient(app), fake


def _identity(fake, **over):
    pin = fake.pin()
    return {"pin_id": pin.pin_id, "run_id": "wfr-1", "process": "use_case_screening",
            "field": "coverage_map", **over}


# ---------------------------------------------------------------- the shape LiteLLM expects

def test_a_search_answers_the_openai_page_with_a_hit_that_names_its_record(api):
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "triage urgency", "max_num_results": 5,
                            "filters": _identity(fake)})
    assert got.status_code == 200, got.text
    page = got.json()
    assert page["object"] == "vector_store.search_results.page"
    hit = page["data"][0]
    assert hit["content"][0]["text"].startswith("Care Delivery > Triage")
    assert hit["file_id"] == "psg-9" and hit["filename"].startswith("art://")
    assert hit["attributes"]["record_id"] == "rec-9"
    assert json.loads(hit["attributes"]["key"])["parent"] == "L2.1"
    assert hit["attributes"]["path"] == "Care Delivery > Triage" and hit["attributes"]["label"] == "Triage"
    assert isinstance(hit["score"], float)


def test_a_search_through_the_facade_is_recorded_against_the_derived_field(api):
    """FR-44 through this door too: the consumption row is written inside the read."""
    client, fake = api
    client.post(f"/v1/vector_stores/{MAP}/search",
                json={"query": "billing", "filters": _identity(fake, field="quality_attributes")})
    rows = [c for c in fake.consumption if c.mode == "search"]
    assert rows and rows[0].field == "quality_attributes" and rows[0].artifact_id == MAP


def test_a_list_of_queries_is_one_question(api):
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": ["triage", "urgency"], "filters": _identity(fake)})
    assert got.status_code == 200 and got.json()["search_query"] == "triage urgency"


def test_the_hit_count_is_capped_however_many_are_asked_for(api):
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "care finance", "max_num_results": 5000,
                            "filters": _identity(fake)})
    assert got.status_code == 200 and len(got.json()["data"]) <= S.MAX_HITS


# ---------------------------------------------------------------- not a way around governance

@pytest.mark.parametrize("missing", ["run_id", "process", "field"])
def test_a_search_under_a_pin_that_omits_its_field_is_refused(api, missing):
    """A caller that names a pin is a workload, and a workload that forgot its field is refused —
    an unattributed read under a pin is the one FR-44 cannot accept."""
    client, fake = api
    filters = _identity(fake)
    filters.pop(missing)
    got = client.post(f"/v1/vector_stores/{MAP}/search", json={"query": "triage",
                                                               "filters": filters})
    assert got.status_code == 400 and missing in got.json()["missing"]


def test_a_search_with_no_pin_at_all_is_served_ad_hoc_pinned_and_in_the_trail(api):
    """The gateway UI's test box and a person with a key: served, under a pin the façade takes of
    that one store, and recorded as adhoc — still governed, only not a workload's field."""
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search", json={"query": "triage urgency"})
    assert got.status_code == 200, got.text
    assert got.json()["data"][0]["attributes"]["record_id"] == "rec-9"
    row = [c for c in fake.consumption if c.mode == "search"][-1]
    assert row.process == "adhoc" and row.field == "search" and row.run_id.startswith("gateway-")
    assert row.artifact_id == MAP


def test_an_exact_artifact_is_refused_as_a_store_rather_than_ranked(api):
    """A relevance answer over a nine-row register is the nearly-right predicate the exact side
    exists to prevent. The refusal points at the lookup."""
    client, fake = api
    got = client.post("/v1/vector_stores/guardrail-mapping/search",
                      json={"query": "E2", "filters": _identity(fake)})
    assert got.status_code == 409 and "reference_lookup" in got.json()["error"]


def test_a_store_the_pin_does_not_hold_is_refused_not_read_around_the_pin(api):
    client, fake = api
    pin = fake.pin(["guardrail-mapping"])
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "triage", "filters": _identity(fake, pin_id=pin.pin_id)})
    assert got.status_code == 404 and "not in pin" in got.json()["error"]


def test_an_expired_or_unknown_pin_is_gone(api):
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "triage", "filters": _identity(fake, pin_id="pin-nope")})
    assert got.status_code == 410 and "Remedy" in got.json()["error"]


def test_a_stale_index_refuses_as_a_sentence(api):
    client, fake = api
    fake.artifacts[MAP].indexed = False
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "triage", "filters": _identity(fake)})
    assert got.status_code == 409 and "Remedy:" in got.json()["error"]


@pytest.mark.parametrize("body", [{"filters": {}}, {"query": "", "filters": {}},
                                  {"query": 7, "filters": {}}])
def test_a_search_without_a_question_is_refused(api, body):
    client, _ = api
    assert client.post(f"/v1/vector_stores/{MAP}/search", json=body).status_code == 400


def test_the_facade_sits_behind_the_same_bearer_as_the_mcp_path(api):
    """`app_for` wraps every route in BearerAuthMiddleware; here the middleware is applied to the
    façade alone to show a call without the shared secret never reaches it."""
    _, fake = api
    app = BearerAuthMiddleware(Starlette(routes=vectorstore.routes(S.server, max_hits=5)),
                               secret="shh")
    client = TestClient(app)
    body = {"query": "triage", "filters": _identity(fake)}
    assert client.post(f"/v1/vector_stores/{MAP}/search", json=body).status_code == 401
    ok = client.post(f"/v1/vector_stores/{MAP}/search", json=body,
                     headers={"Authorization": "Bearer shh"})
    assert ok.status_code == 200


def test_no_span_attribute_carries_the_question_or_a_passage(api, monkeypatch):
    recorded: dict = {}

    class Span:
        def set_attribute(self, key, value): recorded[key] = value

    monkeypatch.setattr(vectorstore, "span", lambda: Span())
    client, fake = api
    client.post(f"/v1/vector_stores/{MAP}/search",
                json={"query": "a secret triage question", "filters": _identity(fake)})
    assert recorded and all(isinstance(v, (int, float, bool)) for v in recorded.values())


@pytest.mark.parametrize("body", [{"query": "x", "filters": ["pin-1"]},
                                  {"query": "x", "filters": "pin-1"}])
def test_filters_that_are_not_an_object_are_refused(api, body):
    client, _ = api
    got = client.post(f"/v1/vector_stores/{MAP}/search", json=body)
    assert got.status_code == 400 and "filters" in got.json()["error"]


def test_a_hit_count_that_is_not_a_number_is_refused(api):
    client, fake = api
    got = client.post(f"/v1/vector_stores/{MAP}/search",
                      json={"query": "triage", "max_num_results": "many",
                            "filters": _identity(fake)})
    assert got.status_code == 400 and "max_num_results" in got.json()["error"]


def test_the_facade_is_mounted_on_the_served_app_beside_mcp(api):
    """`serve()` mounts it under `__main__`; this proves the route survives `app_for`'s middleware
    chain — a refactor of `serve` that dropped `routes=` would otherwise remove the second
    transport silently."""
    from lab.substrate.mcpserver import app_for
    app = app_for(S.server.mcp, routes=vectorstore.routes(S.server, max_hits=S.MAX_HITS))
    with TestClient(app) as client:
        got = client.post(f"/v1/vector_stores/{MAP}/search", json={"query": ""})
    assert got.status_code == 400, "reached the façade (a 404 would mean it is not mounted)"
    assert "query" in got.json()["error"]
