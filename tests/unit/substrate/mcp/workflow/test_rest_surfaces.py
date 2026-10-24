"""The /api verbs a PRESENTATION surface needs to stop reaching the substrate in-process.

TO-BE (24 Oct 2026): a surface — the review app, a Power Apps page, a Teams tab — is a client of the
one seam. These routes are what it was reaching around the seam for: artifact bytes, uploads, the
run board, submissions it made, decided history, and an approval's full payload. Bytes are FORWARDED
to storage-mcp (the front door holds Redis only); everything else is the same Redis read the review
app made in-process, now behind the gateway's role check.

Offline: fake Redis, a fake storage forwarder, Starlette's test client.
"""
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fixtures.fakes import FakeRedis
from lab.platform import runlog, workflows
from lab.platform.contracts import ApprovalKind, MEETING_TO_TRANSCRIPT
from lab.substrate import approvals
from lab.substrate.mcp.workflow import rest
from lab.substrate.mcp.workflow import server as srv

MEETING = MEETING_TO_TRANSCRIPT.name


class Storage:
    """Stands in for storage-mcp: records what was forwarded, answers like it would."""

    def __init__(self):
        self.calls = []

    async def __call__(self, method, path, *, params=None, body=b"", content_type=""):
        self.calls.append((method, path, params, body, content_type))
        if path == "/artifacts":
            if params.get("ref") == "art://a1/model.xml":
                return 200, {"content-type": "application/xml",
                             "content-disposition": 'attachment; filename="model.xml"'}, b"<m/>"
            return 404, {"content-type": "application/json"}, b'{"error": "no artifact"}'
        return 201, {"content-type": "application/json"}, b'{"refs": ["art://u0/brief.docx"]}'


class Semantic:
    """Stands in for semantic-mcp's vocabulary routes."""

    def __init__(self):
        self.calls = []

    async def __call__(self, method, path, *, params=None, body=b"", content_type=""):
        self.calls.append((method, path, params, body, content_type))
        return 201 if method == "POST" else 200, {"content-type": "application/json"}, b'{"ok": true}'


SEMANTIC = Semantic()


@pytest.fixture
def api():
    r, storage = FakeRedis(), Storage()
    SEMANTIC.calls.clear()
    with srv.server.container.redis.override(r):
        yield (TestClient(Starlette(routes=rest.routes(srv.server, storage=storage, semantic=SEMANTIC))),
               r, storage)


# ------------------------------------------------------------------ bytes, forwarded
def test_an_artifact_is_forwarded_to_storage_and_comes_back_as_bytes(api):
    client, _, storage = api
    got = client.get("/api/artifacts", params={"ref": "art://a1/model.xml"})
    assert got.status_code == 200 and got.content == b"<m/>"
    assert got.headers["content-type"].startswith("application/xml")
    assert "model.xml" in got.headers["content-disposition"]
    assert storage.calls[0][:3] == ("GET", "/artifacts", {"ref": "art://a1/model.xml"})


def test_storage_s_refusal_is_passed_through_not_rewritten(api):
    client, _, _ = api
    assert client.get("/api/artifacts", params={"ref": "art://zz/x"}).status_code == 404


def test_an_upload_is_forwarded_as_it_came(api):
    client, _, storage = api
    got = client.post("/api/uploads", files=[("files", ("brief.docx", b"DOCX"))])
    assert got.status_code == 201 and got.json()["refs"] == ["art://u0/brief.docx"]
    method, path, _, body, ctype = storage.calls[0]
    assert (method, path) == ("POST", "/uploads")
    assert b"DOCX" in body and ctype.startswith("multipart/form-data")


# ------------------------------------------------------------------ the run board
def test_the_board_lists_runs_in_flight_and_finished(api):
    client, r, _ = api
    runlog.start("t-1", input="Run one", process=MEETING, client=r)
    body = client.get("/api/board").json()
    assert [h["run_id"] for h in body["active"]] == ["t-1"]
    assert body["recent"] == []


def test_one_run_on_the_board_and_an_unknown_one(api):
    client, r, _ = api
    runlog.start("t-2", input="Run two", process=MEETING, client=r)
    assert client.get("/api/board/t-2").json()["run_id"] == "t-2"
    assert client.get("/api/board/nope").status_code == 404


# ------------------------------------------------------------------ submissions
def test_recent_submissions_and_one_by_id_whatever_its_process(api):
    client, r, _ = api
    rid = workflows.request(MEETING, {"owner": "maria@contoso.com",
                                      "recording": "collab://item/d/i"}, "review-app", client=r)
    listed = client.get("/api/requests", params={"limit": 5}).json()["requests"]
    assert [x["request_id"] for x in listed] == [rid]
    assert client.get(f"/api/requests/{rid}").json()["process"] == MEETING
    assert client.get("/api/requests/wfr-nope").status_code == 404


# ------------------------------------------------------------------ approvals, in full
def _staged(r, **payload):
    return approvals.request(ApprovalKind.EA_IMPORT, "Model X", payload, "wf-visio", client=r)


def test_an_approval_carries_its_whole_payload_so_a_surface_needs_no_redis(api):
    client, r, _ = api
    aid = _staged(r, xml_ref="art://a1/model.xml", summary={"elements": 3},
                  instructions="import it", import_artifacts=[
                      {"ref": "art://x/objects.xlsx", "label": "Objects", "note": "", "media_type": ""}])
    got = client.get(f"/api/approvals/{aid}").json()
    assert got["payload"]["summary"] == {"elements": 3}
    assert got["instructions"] == "import it"
    assert [a["ref"] for a in got["import_artifacts"]] == ["art://x/objects.xlsx"]


def test_decided_history_is_the_listing_with_a_history_parameter(api):
    client, r, _ = api
    aid = _staged(r, xml_ref="art://a1/model.xml")
    approvals.human_decision(aid, "approve", "maria@contoso.com", "review-app", "", client=r)
    hist = client.get("/api/approvals", params={"history": 5}).json()["history"]
    assert hist and hist[0]["request_id"] == aid and hist[0]["decision"] == "approve"


# ------------------------------------------------------------------ the card a low-code surface posts
def test_an_approval_renders_as_the_same_adaptive_card_the_teams_channel_posts(api):
    from lab.substrate import approval_card
    client, r, _ = api
    aid = _staged(r, summary={"elements": 3, "violations": 1})
    got = client.get(f"/api/approvals/{aid}/card").json()
    assert got["type"] == "AdaptiveCard"
    state = approvals.status(aid, client=r)
    assert got == approval_card.card(state, review_url=srv.server.container.config.review_app_url(),
                                     jaeger_url=srv.server.container.config.jaeger_ui_url())


def test_a_card_carries_answer_inputs_only_when_the_caller_can_receive_them(api):
    client, r, _ = api
    aid = _staged(r, question={"prompt": "Admit these?", "items": [{"label": "term-1", "samples": ["x"]}]},
                  answer_labels=["term-1"])
    plain = client.get(f"/api/approvals/{aid}/card").json()
    waiting = client.get(f"/api/approvals/{aid}/card", params={"answers": "true"}).json()
    assert not any(a["type"] == "Action.Submit" for a in plain["actions"])
    submit = next(a for a in waiting["actions"] if a["type"] == "Action.Submit")
    assert submit["data"] == {"labels": ["term-1"], "request_id": aid}


def test_the_card_of_an_unknown_approval_is_a_404(api):
    client, _, _ = api
    assert client.get("/api/approvals/apr-nope/card").status_code == 404


# ------------------------------------------------------------------ the connector's own document
def test_the_door_serves_its_own_connector_document_naming_the_public_gateway(api):
    client, _, _ = api
    with srv.server.container.config.public_gateway_url.override("https://gw.example.com"):
        doc = client.get("/api/openapi.json").json()
    assert doc["swagger"] == "2.0" and doc["host"] == "gw.example.com"
    assert "/processes" in doc["paths"] and "/openapi.json" in doc["paths"]



def test_storage_unreachable_is_a_503_with_a_sentence_not_a_bare_500():
    import asyncio
    with srv.server.container.config.storage_mcp_url.override("http://127.0.0.1:9/mcp"):
        status, _, body = asyncio.run(rest.storage_forwarder(srv.server)(
            "GET", "/artifacts", params={"ref": "art://a/b"}))
    assert status == 503 and b"unreachable" in body


def test_storage_not_configured_is_a_503_too():
    import asyncio
    with srv.server.container.config.storage_mcp_url.override(""):
        status, _, body = asyncio.run(rest.storage_forwarder(srv.server)("GET", "/artifacts"))
    assert status == 503 and b"STORAGE_MCP_URL" in body


def test_a_history_limit_that_is_not_a_number_is_400(api):
    client, _, _ = api
    assert client.get("/api/approvals", params={"history": "abc"}).status_code == 400


def test_the_queue_in_full_is_one_call(api):
    client, r, _ = api
    aid = _staged(r, xml_ref="art://a1/model.xml", summary={"elements": 3})
    rows = client.get("/api/approvals", params={"full": 1}).json()["approvals"]
    assert rows[0]["request_id"] == aid and rows[0]["payload"]["summary"] == {"elements": 3}



# ------------------------------------------------------------------ the vocabulary, forwarded (FR-6)
def test_the_stable_vocabulary_verbs_are_forwarded_to_semantic_mcp_as_they_came(api):
    client, _, _ = api
    assert client.get("/api/vocabulary/match", params={"term": "eRx"}).status_code == 200
    got = client.post("/api/vocabulary/proposals", json={"label": "x", "actor": "a@b"})
    assert got.status_code == 201
    assert [(m, p) for m, p, *_ in SEMANTIC.calls] == [("GET", "/vocabulary/match"),
                                                        ("POST", "/vocabulary/proposals")]
    assert SEMANTIC.calls[0][2] == {"term": "eRx"} and b'"label"' in SEMANTIC.calls[1][3]


def test_the_in_flux_verbs_are_not_on_the_door(api):
    client, _, _ = api
    for path in ("/api/vocabulary/resolve", "/api/vocabulary/place", "/api/vocabulary/relate"):
        assert client.post(path, json={}).status_code in (404, 405), path
