"""`ProcessSpec.external` — a process an outside caller may NOT start, refused on every surface.

WHY THIS IS A PROCESS PROPERTY AND NOT A PERMISSION. `transcript_to_minutes` takes the speaker
mapping a HUMAN gave as input. A caller able to start it directly would supply its own attribution
and walk past the only gate the meeting pipeline has. That is true of every caller — a low-code
connector, an agent, the master key — so it is declared on the process and enforced by not generating
the entry point at all, rather than granted away correctly forever by role or ACL.

The asymmetry is deliberate and pinned here too: SUBMIT is refused, STATUS and RESULT are not. A
caller whose approval started the run may legitimately watch it.
"""
import asyncio

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fixtures.fakes import FakeRedis
from lab.platform.contracts import (MEETING_TO_TRANSCRIPT, PROCESSES, TRANSCRIPT_TO_MINUTES,
                                    VISIO_TO_ARCHIMATE)
from lab.substrate.mcp.workflow import rest
from lab.substrate.mcp.workflow import server as srv


def _tool_names() -> set[str]:
    """What the server actually PUBLISHES — the catalogue a gateway would list and a grant would
    name, not an internal registry that could differ from it."""
    return {t.name for t in asyncio.run(srv.build().mcp.list_tools())}


@pytest.fixture
def api():
    r = FakeRedis()
    with srv.server.container.redis.override(r):
        yield TestClient(Starlette(routes=rest.routes(srv.server))), r


# ------------------------------------------------------------------ the declaration
def test_the_continuation_only_process_is_the_minutes_run():
    """Membership, not an exact set: a new process must not have to edit this test, but the one
    process whose input is a human's answer must stay closed."""
    assert TRANSCRIPT_TO_MINUTES.external is False
    assert MEETING_TO_TRANSCRIPT.external is True and VISIO_TO_ARCHIMATE.external is True
    assert any(s.external for s in PROCESSES.values()), "a door that starts nothing is not a door"


def test_a_process_is_startable_by_default():
    """The flag defaults open, so declaring a process needs no ceremony; closing one is the
    deliberate act."""
    assert VISIO_TO_ARCHIMATE.external is True
    from dataclasses import replace
    assert replace(VISIO_TO_ARCHIMATE, name="x").external is True


# ------------------------------------------------------------------ the REST surface
def test_rest_generates_no_submit_route_for_a_continuation_only_process(api):
    client, _ = api
    paths = {r.path for r in rest.routes(srv.server)}
    assert f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs" not in paths
    assert f"/api/processes/{MEETING_TO_TRANSCRIPT.name}/runs" in paths
    # ... and the route genuinely is not served, rather than merely absent from a list
    r = client.post(f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs", json={})
    assert r.status_code == 404, r.text          # no such path at all — not merely a refused method


def test_rest_still_lets_a_caller_watch_a_continuation_run(api):
    """Refusing to START is not refusing to OBSERVE: the run was caused by the caller's own
    approval, and a flow that cannot poll it cannot tell a person the minutes are ready."""
    client, _ = api
    paths = {r.path for r in rest.routes(srv.server)}
    assert f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs/{{request_id}}" in paths
    assert client.get(f"/api/processes/{TRANSCRIPT_TO_MINUTES.name}/runs/wfr-nope").status_code == 404


def test_the_index_does_not_advertise_a_submit_url_that_would_404(api):
    """The catalogue is what a flow author reads to decide what to integrate; sending them to a
    path this door refuses is worse than saying it is closed."""
    client, _ = api
    by_name = {p["name"]: p for p in client.get("/api/processes").json()["processes"]}
    closed = by_name[TRANSCRIPT_TO_MINUTES.name]
    assert closed["submit"] is None and closed["startable"] is False
    assert closed["inputs"] and closed["outputs"], "still documented — it is closed, not hidden"
    openp = by_name[MEETING_TO_TRANSCRIPT.name]
    assert openp["startable"] is True and openp["submit"].endswith("/runs")


# ------------------------------------------------------------------ the MCP surface
def test_mcp_generates_no_submit_tool_for_a_continuation_only_process():
    """A tool that does not exist cannot be granted by mistake, discovered, or described to an agent
    as something it might try."""
    names = _tool_names()
    assert TRANSCRIPT_TO_MINUTES.tool("submit") not in names
    assert TRANSCRIPT_TO_MINUTES.tool("status") in names
    assert TRANSCRIPT_TO_MINUTES.tool("result") in names
    assert MEETING_TO_TRANSCRIPT.tool("submit") in names


def test_both_surfaces_refuse_the_same_process():
    """The one property that must never drift: an outside caller cannot do through one door what the
    other door refuses."""
    rest_submits = {r.path.split("/")[3] for r in rest.routes(srv.server)
                    if r.path.endswith("/runs") and "POST" in r.methods}
    tools = _tool_names()
    mcp_submits = {n for n, s in PROCESSES.items() if s.tool("submit") in tools}
    assert rest_submits == mcp_submits == {n for n, s in PROCESSES.items() if s.external}
