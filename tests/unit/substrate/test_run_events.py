"""`GET /api/processes/<p>/runs/<id>/events` — watch one run without polling it.

Asked for as "can we use websocket or SSE to update the UI". SSE rather than a WebSocket because
this is one-way (the server reports, the client never sends), so it needs no protocol upgrade, no
framing, and reconnects on its own. The value is not only the review app — a Copilot connector, a
Teams card or a CLI can watch a run over the same governed surface.

Authorised exactly like reading the run once: watching a run and fetching it in a loop are the same
power, so they take the same role. A second, weaker rule for the streaming version would be a way
around the first.
"""
import pytest

from lab.substrate import apipolicy
from lab.platform.contracts import ApiRoles


def test_the_events_route_is_governed_by_the_policy_not_left_to_default_deny_by_accident():
    """Everything under /api is governed, and an unmatched path is DENIED — so a route with no
    operation would be unreachable rather than open. It still has to be declared, or the feature
    simply does not work and the reason is invisible."""
    assert apipolicy.governs("/api/processes/use_case_screening/runs/wfr-1/events")
    op = apipolicy.operation("GET", "/api/processes/use_case_screening/runs/wfr-1/events")
    assert op is not None, "declared, not accidentally denied"


def test_watching_a_run_takes_the_same_role_as_reading_it():
    """A weaker rule for the streaming version would be a way around the stronger one."""
    stream = apipolicy.role_for("GET", "/api/processes/use_case_screening/runs/wfr-1/events")
    once = apipolicy.role_for("GET", "/api/processes/use_case_screening/runs/wfr-1")
    assert stream == once == ApiRoles.SUBMIT


def test_the_events_path_does_not_swallow_the_plain_run_read():
    """`/runs/{id}` and `/runs/{id}/events` are different operations; a pattern loose enough to
    match both would give one of them the other's role."""
    assert apipolicy.operation("GET", "/api/processes/p/runs/r").name == "processes.run"
    assert apipolicy.operation("GET", "/api/processes/p/runs/r/events").name == "processes.run.events"


def test_every_operation_still_has_a_role_and_the_vocabulary_is_unchanged():
    """`ApiRoles.ALL` is asserted elsewhere to equal the roles OPERATIONS uses — a new operation
    must not need a new role, because a role with no operation fails as dead."""
    assert {o.role for o in apipolicy.OPERATIONS} <= set(ApiRoles.ALL)


# ---------------------------------------------------------------- the stream itself

@pytest.fixture
def front_door(monkeypatch):
    """A front door whose run status walks through the states a test gives it.

    `monkeypatch`, not assignment: the suite runs in ONE process, and a module-level client left
    swapped is exactly the process-global leak `tests/conftest.py` exists to close everywhere else.
    """
    from types import SimpleNamespace
    from starlette.applications import Starlette
    from lab.platform import workflows
    from lab.substrate.mcp.workflow import rest

    def build(states):
        seq, last = iter(states), {}

        def status(rid, client=None):
            nonlocal last
            try:
                last = next(seq)
            except StopIteration:
                pass
            return last

        monkeypatch.setattr(rest, "workflows",
                            SimpleNamespace(**{**workflows.__dict__, "status": status}))
        monkeypatch.setattr(rest, "EVENTS_POLL_S", 0)
        server = SimpleNamespace(container=SimpleNamespace(redis=lambda: None))
        return Starlette(routes=rest.routes(server))
    return build


RUNNING = {"request_id": "wfr-1", "process": "use_case_screening", "status": "running",
           "trace_id": "t" * 32}
DONE = {**RUNNING, "status": "done", "finished_at": "2026-09-19T13:20:07"}


def test_the_stream_sends_the_run_and_closes_when_it_settles(front_door):
    """A stream held open on a finished run is a connection waiting for an event that cannot
    arrive."""
    from starlette.testclient import TestClient
    app = front_door([RUNNING, RUNNING, DONE])
    with TestClient(app) as c:
        r = c.get("/api/processes/use_case_screening/runs/wfr-1/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [l for l in r.text.splitlines() if l.startswith("data: ")]
    assert len(frames) == 2, "one for running, one for done — the repeat is not resent"
    assert '"status": "done"' in frames[-1]


def test_nothing_may_buffer_an_event_stream(front_door):
    """A proxy that waits for a complete response turns "live" into "all at once at the end",
    which from the client's side is indistinguishable from broken."""
    from starlette.testclient import TestClient
    app = front_door([DONE])
    with TestClient(app) as c:
        r = c.get("/api/processes/use_case_screening/runs/wfr-1/events")
    assert r.headers.get("x-accel-buffering") == "no"
    assert r.headers.get("cache-control") == "no-cache"


def test_an_id_from_another_process_is_a_conflict_not_a_not_found(front_door):
    """The caller has the right id and the wrong path; saying "no such run" would send them
    looking for a run that exists."""
    from starlette.testclient import TestClient
    app = front_door([{**RUNNING, "process": "visio_to_archimate"}])
    with TestClient(app) as c:
        r = c.get("/api/processes/use_case_screening/runs/wfr-1/events")
    assert r.status_code == 409


def test_an_unknown_run_is_a_404_before_any_stream_is_opened(front_door):
    from starlette.testclient import TestClient
    app = front_door([{}])
    with TestClient(app) as c:
        r = c.get("/api/processes/use_case_screening/runs/nope/events")
    assert r.status_code == 404
