"""semantic-mcp's vocabulary routes — what the front door forwards `/api/vocabulary/*` to (FR-6).

The SAF pack, as taxonomy master until the fabric lands in the work tenant, binds to the fabric's
STABLE vocabulary verbs; a flow or a Dataverse custom API reaches them through a custom connector over
`/api`. These routes call the SAME domain methods the MCP tools call, so the two doors cannot answer
differently. Offline: a fake fabric service, Starlette's test client.
"""
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from lab.substrate.mcp.semantic import rest


class Fabric:
    def __init__(self):
        self.calls = []

    def concept_match(self, term, *, scheme="", limit=5):
        self.calls.append(("match", term, scheme, limit))
        return {"term": term, "concept": "Prescription", "score": 0.81}

    def vocab_propose(self, label, **kw):
        self.calls.append(("propose", label, kw))
        if not kw.get("actor"):
            raise ValueError("actor is required")
        return {"iri": f"urn:cand:{label}", "label": label}

    def vocab_amend(self, cid, *, scheme, alt, actor, reason=""):
        self.calls.append(("amend", cid, scheme, alt, actor, reason))
        return {"concept_id": cid, "alt": [alt]}


@pytest.fixture
def api():
    fab, staged = Fabric(), []

    async def master(scheme, owner, version):
        staged.append((scheme, owner, version))
        return {"ontology_concepts": {"ref": "art://m1/ontology_concepts.md", "rows": 3}}
    client = TestClient(Starlette(routes=rest.routes(fabric=lambda: fab, master=master)))
    return client, fab, staged


def test_a_term_is_matched_against_definitions(api):
    client, fab, _ = api
    got = client.get("/vocabulary/match", params={"term": "eRx", "scheme": "cafe"}).json()
    assert got["concept"] == "Prescription" and fab.calls[0] == ("match", "eRx", "cafe", 5)


def test_a_match_without_a_term_says_so(api):
    client, _, _ = api
    assert client.get("/vocabulary/match").status_code == 400


def test_a_proposal_is_parked_with_its_actor_and_provenance(api):
    client, fab, _ = api
    body = {"label": "Dispense audit event", "actor": "maria@contoso.com", "scheme": "cafe",
            "proposed_for": "urn:fab:doc:1", "definition": "x"}
    got = client.post("/vocabulary/proposals", json=body)
    assert got.status_code == 201 and got.json()["label"] == "Dispense audit event"
    _, label, kw = fab.calls[0]
    assert kw["actor"] == "maria@contoso.com" and kw["proposed_for"] == "urn:fab:doc:1"


def test_the_domain_s_refusal_is_a_422_with_its_sentence(api):
    client, _, _ = api
    got = client.post("/vocabulary/proposals", json={"label": "x"})
    assert got.status_code == 422 and "actor" in got.json()["error"]


def test_an_unknown_field_is_refused_rather_than_dropped(api):
    client, _, _ = api
    got = client.post("/vocabulary/proposals", json={"label": "x", "actor": "a", "nonsense": 1})
    assert got.status_code == 422 and "nonsense" in got.json()["error"]


def test_an_alias_is_the_steward_s_amend(api):
    client, fab, _ = api
    got = client.post("/vocabulary/aliases", json={"concept_id": "Prescription", "scheme": "cafe",
                                                   "alt": "eRx", "actor": "steward@contoso.com"})
    assert got.status_code == 201 and fab.calls[0][:4] == ("amend", "Prescription", "cafe", "eRx")


def test_the_master_is_staged_by_reference(api):
    client, _, staged = api
    got = client.get("/vocabulary/master", params={"scheme": "cafe"}).json()
    assert got["ontology_concepts"]["ref"].startswith("art://") and staged[0][0] == "cafe"


def test_an_embedder_that_cannot_answer_is_a_503_naming_it_not_a_bare_500():
    """Measured live 24 Oct 2026: a revoked upstream embedding key surfaced as `500 Internal Server
    Error` with no body. "I could not ask" is a claim about the deployment, and says so."""
    class Down(Fabric):
        def concept_match(self, term, *, scheme="", limit=5):
            raise RuntimeError("HTTP Error 401: Unauthorized")

    async def master(*_):
        return {}
    client = TestClient(Starlette(routes=rest.routes(fabric=lambda: Down(), master=master)))
    got = client.get("/vocabulary/match", params={"term": "eRx"})
    assert got.status_code == 503 and "401" in got.json()["error"]
