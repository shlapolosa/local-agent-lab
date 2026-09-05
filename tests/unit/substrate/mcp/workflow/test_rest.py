"""The REST ingress — the same front door, for clients that are not agents.

The property worth testing is not that REST works; it is that REST and MCP are ADAPTERS OVER ONE
PORT and therefore cannot disagree. Both validate with the process's own `ProcessSpec`, both publish
through `workflows.submit`, both record a decision through `approvals.human_decision`. A caller must
not be able to do through one door what the other would refuse.

Offline: fake Redis, Starlette's test client, no gateway and no network.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/workflow/test_rest.py
"""
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import ApprovalKind, MEETING_TO_TRANSCRIPT, PROCESSES
from lab.substrate import approvals
from lab.substrate.mcp.workflow import rest
from lab.substrate.mcp.workflow import server as srv

MEETING = MEETING_TO_TRANSCRIPT.name
GOOD = {"owner": "maria@contoso.com", "recording": "collab://item/drive-1/item-9"}


@pytest.fixture
def api():
    r = FakeRedis()
    with srv.server.container.redis.override(r):
        yield TestClient(Starlette(routes=rest.routes(srv.server))), r


# ------------------------------------------------------------------ discovery
def test_the_index_tells_a_flow_author_what_it_can_start_and_what_each_needs(api):
    client, _ = api
    body = client.get("/api/processes").json()
    names = {p["name"] for p in body["processes"]}
    assert MEETING in names
    spec = next(p for p in body["processes"] if p["name"] == MEETING)
    assert {i["name"] for i in spec["inputs"]} == {"owner", "recording"}
    assert all(i["description"] for i in spec["inputs"]), "a flow author reads these instead of guessing"


# ------------------------------------------------------------------ starting a run
def test_a_valid_submit_queues_exactly_what_the_mcp_tool_would(api):
    client, r = api
    got = client.post(f"/api/processes/{MEETING}/runs", json={**GOOD, "requester": "power-automate"})
    assert got.status_code == 202
    body = got.json()
    assert body["accepted"] is True and body["duplicate"] is False
    state = workflows.status(body["request_id"], client=r)
    assert state["process"] == MEETING and state["requester"] == "power-automate"
    assert state["inputs"] == GOOD          # status() already decodes it


def test_the_process_contract_refuses_the_same_things_on_both_doors(api):
    """One validator, so a REST caller cannot submit what the MCP tool would have rejected."""
    client, _ = api
    for bad, why in [({"owner": "maria@contoso.com"}, "recording"),
                     ({**GOOD, "recording": "https://example.com/rec.mp4"}, "recording"),
                     ({**GOOD, "owner": "Maria Perez"}, "owner")]:
        got = client.post(f"/api/processes/{MEETING}/runs", json=bad)
        assert got.status_code == 422, bad
        assert why in got.json()["error"]


def test_a_rejected_body_comes_back_with_the_field_descriptions(api):
    """A flow shows the caller whatever it is handed, so the refusal has to be self-explaining."""
    client, _ = api
    got = client.post(f"/api/processes/{MEETING}/runs", json={}).json()
    assert "expected" in got and "recording" in got["expected"]


def test_an_unknown_field_is_refused_rather_than_silently_dropped(api):
    client, _ = api
    got = client.post(f"/api/processes/{MEETING}/runs", json={**GOOD, "recordng": "typo"})
    assert got.status_code == 422


def test_a_retried_submit_returns_the_same_run_rather_than_starting_a_second(api):
    """A flow retries. A ten-minute transcription must not run twice because a step timed out."""
    client, _ = api
    body = {**GOOD, "idempotency_key": "recording-abc"}
    first = client.post(f"/api/processes/{MEETING}/runs", json=body).json()
    again = client.post(f"/api/processes/{MEETING}/runs", json=body).json()
    assert again["request_id"] == first["request_id"] and again["duplicate"] is True


def test_a_body_that_is_not_json_says_so(api):
    client, _ = api
    got = client.post(f"/api/processes/{MEETING}/runs", content=b"not json",
                      headers={"content-type": "application/json"})
    assert got.status_code == 400 and "JSON" in got.json()["error"]


# ------------------------------------------------------------------ following a run
def test_a_run_reports_the_outputs_its_process_declares(api):
    client, r = api
    rid = client.post(f"/api/processes/{MEETING}/runs", json=GOOD).json()["request_id"]
    workflows.mark(rid, "done", client=r, approval_id="apr-1", transcript_ref="art://t/x.json")
    got = client.get(f"/api/processes/{MEETING}/runs/{rid}").json()
    assert got["status"] == "done" and got["approval_id"] == "apr-1"


def test_an_unknown_run_is_a_404(api):
    client, _ = api
    assert client.get(f"/api/processes/{MEETING}/runs/wfr-nope").status_code == 404


def test_a_run_belonging_to_another_process_says_which(api):
    """The caller has the right id and the wrong path — a 404 would send them hunting for the id."""
    client, r = api
    rid = client.post("/api/processes/visio_to_archimate/runs",
                      json={"diagram": "art://d/a.vsdx"}).json()["request_id"]
    got = client.get(f"/api/processes/{MEETING}/runs/{rid}")
    assert got.status_code == 409 and got.json()["process"] == "visio_to_archimate"


# ------------------------------------------------------------------ answering a human's question
def _ask(r, labels=("SPEAKER_00", "SPEAKER_01")):
    return approvals.request(ApprovalKind.SPEAKER_MAPPING.value, "weekly sync",
                             {"question": {"prompt": "Who is each speaker?",
                                           "items": [{"label": l} for l in labels]},
                              "answer_labels": list(labels), "answer_required": True,
                              "transcript": "art://t/x.json"},
                             "wf-meeting", client=r)


def test_the_question_comes_back_flat_for_a_card_template(api):
    client, r = api
    aid = _ask(r)
    got = client.get(f"/api/approvals/{aid}").json()
    assert got["question"]["prompt"] == "Who is each speaker?"
    assert [s["label"] for s in got["speakers"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert got["answer_required"] is True
    assert got["artifacts"]["transcript"] == "art://t/x.json"


def test_a_relayed_answer_is_recorded_with_the_signed_in_person(api):
    client, r = api
    aid = _ask(r)
    got = client.post(f"/api/approvals/{aid}/decide", json={
        "decision": "approve", "actor": "maria@contoso.com", "channel": "power-automate",
        "answer": {"SPEAKER_00": {"identity": "maria@contoso.com"},
                   "SPEAKER_01": {"tag": "the vendor's architect"}}})
    assert got.status_code == 200 and got.json()["final"] is True
    state = approvals.status(aid, client=r)
    assert state["status"] == "approve" and state["decided_by"] == "maria@contoso.com"
    assert state["answer"]["SPEAKER_01"] == {"tag": "the vendor's architect"}


def test_the_relay_is_never_logged_as_a_decision_taken_at_the_review_app(api):
    client, r = api
    aid = _ask(r)
    client.post(f"/api/approvals/{aid}/decide",
                json={"decision": "approve", "actor": "maria@contoso.com", "channel": "power-automate",
                      "answer": {"SPEAKER_00": {"tag": "a"}, "SPEAKER_01": {"tag": "b"}}})
    assert approvals.status(aid, client=r)["decided_via"] == "api:power-automate"


def test_a_blank_actor_is_refused_because_the_audit_log_is_the_point(api):
    client, r = api
    aid = _ask(r)
    got = client.post(f"/api/approvals/{aid}/decide",
                      json={"decision": "approve", "actor": "  ",
                            "answer": {"SPEAKER_00": {"tag": "a"}, "SPEAKER_01": {"tag": "b"}}})
    assert got.status_code == 422 and "actor" in got.json()["error"]


def test_an_incomplete_answer_is_refused_and_names_the_missing_speaker(api):
    client, r = api
    aid = _ask(r)
    got = client.post(f"/api/approvals/{aid}/decide",
                      json={"decision": "approve", "actor": "maria@contoso.com",
                            "answer": {"SPEAKER_00": {"tag": "a"}}})
    assert got.status_code == 422 and "SPEAKER_01" in got.json()["error"]


def test_declining_needs_no_answer(api):
    client, r = api
    aid = _ask(r)
    got = client.post(f"/api/approvals/{aid}/decide",
                      json={"decision": "decline", "actor": "maria@contoso.com",
                            "comment": "cannot tell these voices apart"})
    assert got.status_code == 200 and approvals.status(aid, client=r)["status"] == "decline"


def test_an_already_decided_approval_is_refused_not_re_decided(api):
    client, r = api
    aid = _ask(r)
    answer = {"SPEAKER_00": {"tag": "a"}, "SPEAKER_01": {"tag": "b"}}
    client.post(f"/api/approvals/{aid}/decide",
                json={"decision": "approve", "actor": "maria@contoso.com", "answer": answer})
    again = client.post(f"/api/approvals/{aid}/decide",
                        json={"decision": "decline", "actor": "bob@contoso.com"})
    assert again.status_code == 422 and "already" in again.json()["error"]


def test_an_invalid_decision_lists_the_legal_ones(api):
    client, r = api
    aid = _ask(r)
    got = client.post(f"/api/approvals/{aid}/decide",
                      json={"decision": "maybe", "actor": "maria@contoso.com"})
    assert got.status_code == 422 and "approve" in got.json()["error"]


# ------------------------------------------------------------------ the shape of the design
def test_both_ingresses_are_generated_from_the_one_registry():
    """Registering a process gives MCP tools AND REST routes at once, so neither can drift — including
    the refusal: a continuation-only process gets neither a submit tool nor a submit route."""
    paths = {r.path for r in rest.routes(srv.server)}
    for name, spec in PROCESSES.items():
        assert (f"/api/processes/{name}/runs" in paths) is spec.external
        assert f"/api/processes/{name}/runs/{{request_id}}" in paths, "every run stays observable"


def test_rest_never_calls_mcp_it_calls_the_same_function():
    """A REST handler going out to the gateway to invoke MCP to reach a function it can call
    directly would be a round trip through the protocol REST exists to avoid."""
    import inspect
    src = inspect.getsource(rest)
    assert "workflows.submit" in src and "approvals.human_decision" in src
    assert "fastmcp" not in src and "call_tool" not in src


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
