"""Finding a run somebody else started: one implementation, two surfaces, one cheap read."""
import json

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import USE_CASE_SCREENING as SCREENING, TRANSCRIPT_TO_MINUTES
from lab.substrate.mcp.workflow import listing, rest
from lab.substrate.mcp.workflow import server as srv


#: The smallest input each process's own contract accepts — a listing test still goes through the
#: real front door, because a run that could not be submitted is not one anybody will search for.
INPUTS = {"use_case_screening": {"submission": "art://a/use-case.md", "submitter": "ba@x.ae"},
          "transcript_to_minutes": {"transcript": "art://a/t.vtt", "speaker_map": {"SPEAKER_00": {"value": "A"}}}}


def _submitted(r, process, **fields):
    """A run on the board, as the consumer leaves it."""
    rid, _duplicate = workflows.submit(process.name, dict(INPUTS[process.name]), "tester", client=r)
    if fields:
        workflows.mark(rid, "done", client=r, **fields)
    return rid


@pytest.fixture
def api():
    r = FakeRedis()
    with srv.server.container.redis.override(r):
        yield TestClient(Starlette(routes=rest.routes(srv.server))), r


def test_the_runs_of_one_process_come_back_newest_first_with_what_each_says_about_itself(api):
    client, r = api
    _submitted(r, SCREENING, subject="Referral triage takes eleven days",
               criticality_band="business-critical", screening_ref="art://a/s.json")
    _submitted(r, TRANSCRIPT_TO_MINUTES, subject="a meeting")
    body = client.get(f"/api/processes/{SCREENING.name}/runs").json()
    assert body["process"] == SCREENING.name and body["count"] == 1
    row = body["runs"][0]
    assert row["subject"].startswith("Referral triage") and row["criticality_band"] == "business-critical"
    assert row["status"] == "done" and row["request_id"].startswith("wfr-")
    assert "summary" not in row and "trace_id" not in row, "a listing is not a run record"


def test_q_finds_a_run_by_what_a_person_remembers_rather_than_by_its_id(api):
    client, r = api
    _submitted(r, SCREENING, subject="Referral triage takes eleven days")
    _submitted(r, SCREENING, subject="Invoice coding is manual")
    assert client.get(f"/api/processes/{SCREENING.name}/runs?q=referral").json()["count"] == 1
    assert client.get(f"/api/processes/{SCREENING.name}/runs?q=INVOICE").json()["count"] == 1
    assert client.get(f"/api/processes/{SCREENING.name}/runs?q=nothing here").json()["count"] == 0
    assert client.get(f"/api/processes/{SCREENING.name}/runs").json()["count"] == 2


def test_the_listing_is_capped_and_a_bad_limit_is_refused(api):
    client, r = api
    for n in range(5):
        _submitted(r, SCREENING, subject=f"case {n}")
    assert client.get(f"/api/processes/{SCREENING.name}/runs?limit=2").json()["count"] == 2
    assert client.get(f"/api/processes/{SCREENING.name}/runs?limit=9999").json()["count"] == 5
    assert client.get(f"/api/processes/{SCREENING.name}/runs?limit=nope").status_code == 400
    assert listing.MAX_LIMIT <= 100


def test_a_continuation_only_process_is_findable_even_though_it_cannot_be_started(api):
    """Refusing to START is not refusing to FIND: the design runs a person follows are all
    continuations, and a caller that could not list them could not follow its own approval."""
    client, r = api
    _submitted(r, TRANSCRIPT_TO_MINUTES, subject="minutes for the Tuesday meeting")
    body = client.get(f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs").json()
    assert body["count"] == 1
    assert client.post(f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs", json={}).status_code == 405


def test_the_governed_tool_and_the_front_door_answer_identically(api):
    """Two surfaces, one implementation — a caller must not have to know which one it reached."""
    client, r = api
    _submitted(r, SCREENING, subject="Referral triage")
    tool = listing.search(SCREENING, q="referral", client=r)
    assert tool == client.get(f"/api/processes/{SCREENING.name}/runs?q=referral").json()
    assert tool["query"] == "referral" and tool["scanned"] == listing.SCANNED


def test_the_search_reads_the_stream_once_and_opens_nothing(api):
    """A listing must cost one read. A search that fetched every stored record would be a different
    feature wearing this one's name."""
    import inspect
    source = inspect.getsource(listing)
    assert "workflows.recent" in source
    for forbidden in ("storage_read", "artifacts(", "read_artifact", "http"):
        assert forbidden not in source, forbidden
