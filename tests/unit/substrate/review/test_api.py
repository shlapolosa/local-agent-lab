"""The review app's client of the seam — `/api` and gateway MCP, never Redis or a store.

What is pinned: each method calls the operation the policy table names, carries the app's own
credential, maps the door's refusals onto the exceptions the pages already handle (KeyError for a
missing thing, ValueError for a refusal a person can read), and relays the signed-in reviewer as
`actor` / `requester` rather than the app's own name. Offline: httpx MockTransport.
"""
import json

import httpx
import pytest

from lab.substrate.review.api import LabApi

BASE = "https://gw.example/api"


def _api(handler, calls=None):
    def record(request):
        if calls is not None:
            calls.append(request)
        return handler(request)
    return LabApi(BASE, lambda: {"Authorization": "Bearer app-token"},
                  mcp=None, transport=httpx.MockTransport(record))


def test_every_call_carries_the_app_credential():
    calls = []
    _api(lambda r: httpx.Response(200, json={"approvals": [], "count": 0}), calls).pending()
    assert calls[0].headers["authorization"] == "Bearer app-token"
    assert str(calls[0].url).startswith(f"{BASE}/approvals")


def test_an_artifact_comes_back_as_bytes_and_a_missing_one_is_a_key_error():
    api = _api(lambda r: httpx.Response(200, content=b"<m/>") if r.url.params["ref"] == "art://a/m.xml"
               else httpx.Response(404, json={"error": "no artifact"}))
    assert api.artifact("art://a/m.xml") == b"<m/>"
    with pytest.raises(KeyError):
        api.artifact("art://z/none")


def test_pending_returns_each_open_approval_in_full_in_ONE_call():
    calls = []
    api = _api(lambda r: httpx.Response(200, json={"approvals": [
        {"request_id": "apr-1", "payload": {"xml_ref": "art://a/m.xml"}}], "count": 1}), calls)
    assert api.pending() == [{"request_id": "apr-1", "payload": {"xml_ref": "art://a/m.xml"}}]
    assert len(calls) == 1 and calls[0].url.params["full"] == "1"


def test_history_and_an_unknown_approval():
    def handler(r):
        if "history" in r.url.params:
            return httpx.Response(200, json={"history": [{"request_id": "apr-1", "decision": "approve"}]})
        return httpx.Response(404, json={"error": "no such approval"})
    api = _api(handler)
    assert api.history(5)[0]["decision"] == "approve"
    assert api.status("apr-x") == {}


def test_a_decision_relays_the_signed_in_person_and_a_refusal_is_a_value_error():
    calls = []

    def handler(r):
        body = json.loads(r.content)
        if body["decision"] == "approve":
            return httpx.Response(200, json={"decision": "approve", "actor": body["actor"]})
        return httpx.Response(422, json={"error": "already decided"})
    api = _api(handler, calls)
    api.decide("apr-1", "approve", "maria@contoso.com", "looks right", answer={"a": "b"})
    sent = json.loads(calls[0].content)
    assert sent["actor"] == "maria@contoso.com" and sent["decision"] == "approve"
    assert sent["channel"] == "review-app" and sent["answer"] == {"a": "b"}
    with pytest.raises(ValueError, match="already decided"):
        api.decide("apr-1", "decline", "maria@contoso.com", "")


def test_submit_sends_the_reviewer_as_requester_and_surfaces_the_contract_s_refusal():
    calls = []

    def handler(r):
        body = json.loads(r.content)
        if body.get("recording"):
            return httpx.Response(202, json={"request_id": "wfr-1"})
        return httpx.Response(422, json={"error": "recording is required"})
    api = _api(handler, calls)
    assert api.submit("meeting_to_transcript", {"recording": "collab://x"}, "maria@contoso.com") == "wfr-1"
    assert json.loads(calls[0].content)["requester"] == "maria@contoso.com"
    assert calls[0].url.path.endswith("/processes/meeting_to_transcript/runs")
    with pytest.raises(ValueError, match="recording is required"):
        api.submit("meeting_to_transcript", {}, "maria@contoso.com")


def test_an_upload_keeps_the_filename():
    calls = []
    api = _api(lambda r: httpx.Response(201, json={"refs": ["art://u0/brief.docx"]}), calls)
    assert api.upload("brief.docx", b"DOCX", "application/vnd.openxmlformats") == "art://u0/brief.docx"
    assert b'filename="brief.docx"' in calls[0].content


def test_board_requests_and_runs():
    def handler(r):
        p = r.url.path
        if p.endswith("/board"):
            return httpx.Response(200, json={"active": [{"run_id": "t1"}], "recent": []})
        if p.endswith("/board/t1"):
            return httpx.Response(200, json={"run_id": "t1"})
        if p.endswith("/requests"):
            return httpx.Response(200, json={"requests": [{"request_id": "wfr-1"}]})
        if p.endswith("/requests/wfr-1"):
            return httpx.Response(200, json={"request_id": "wfr-1", "status": "done"})
        return httpx.Response(404, json={"error": "no"})
    api = _api(handler)
    assert api.board(20) == ([{"run_id": "t1"}], [])
    assert api.run("t1")["run_id"] == "t1" and api.run("nope") == {}
    assert api.recent_requests(10)[0]["request_id"] == "wfr-1"
    assert api.request_status("wfr-1")["status"] == "done" and api.request_status("x") == {}


def test_a_corpus_read_goes_through_gateway_mcp_and_returns_the_records():
    seen = []

    async def mcp(calls):
        seen.extend(calls)
        if calls[0][0] == "reference_pin":
            return [{"pin_id": "pin-1"}]
        return [{"records": [{"body": {"Field group": "Volumes"}}]}]
    api = LabApi(BASE, lambda: {}, mcp=mcp)
    rows = api.corpus_records("finance-fields", "field-group", field="intake")
    assert rows == [{"Field group": "Volumes"}]
    assert seen[0] == ("reference_pin", {"artifact_ids": ["finance-fields"]})
    lookup = seen[1][1]
    assert lookup["pin_id"] == "pin-1" and lookup["artifact_id"] == "finance-fields"
    assert lookup["process"] == "review-app" and lookup["field"] == "intake"


def test_without_its_own_entra_registration_the_app_says_what_to_set(monkeypatch):
    """`/api` refuses a virtual key, so there is no key fallback to fall into: a KeyError on a variable
    nobody provisions was the old failure. Now it is a sentence naming the settings and the script."""
    from lab.platform import identity
    from lab.substrate.review import api as api_mod
    monkeypatch.setattr(identity, "agent_token", lambda prefix: None)
    lab = api_mod.from_config()
    with pytest.raises(RuntimeError, match="REVIEW_ENTRA_CLIENT_ID"):
        lab.pending()
