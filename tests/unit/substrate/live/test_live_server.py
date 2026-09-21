"""`live` — a small page that WATCHES a run, updating in place.

Streamlit cannot do this. It is server-rendered: the browser receives element deltas over
Streamlit's own socket and the only way to change anything is a script rerun, so an SSE feed cannot
patch the page. Every workaround collapses into "rerun or reload", and both lose scroll position,
open expanders and — until the page was moved into the URL — which page you were on at all.

So the live view is its own substrate service, on the review app's trust model: its own gate, Redis
directly, no credential beyond those. It serves BOTH the page and the stream, which is what makes
them same-origin and the whole thing possible — the browser holds no Entra token, so it could never
have called the front door's `/api` stream.

What it shows is what the RUN LOG knows: status, the step running now, each step's start/finish and
error. Reviewing a run's OUTPUT stays in the review app; this answers "what is happening".
"""
import json

import pytest

from fixtures.fakes import FakeRedis
from lab.platform import runlog
from lab.substrate.live import server as live


@pytest.fixture
def redis():
    return FakeRedis()


def _run(redis, rid="e7fb30be", **fields):
    runlog.start(rid, input="screening art://a/u.md", process="use_case_screening",
                 trace_id=rid, client=redis)
    if fields:
        runlog.update(rid, client=redis, **fields)
    return rid


# ---------------------------------------------------------------- what a frame says


def test_a_frame_carries_what_a_watcher_needs_and_nothing_it_does_not():
    """Counts, ids and step names — never model output. This page is reachable by anyone who holds
    the gate, and a run's content is the review app's business, behind its own decision surface."""
    rid = _run(redis := FakeRedis(), subject="Referral triage takes too long")
    runlog.node(rid, "step_3", "done", client=redis, elapsed=8.0)
    frame = live.frame(runlog.get(rid, client=redis))
    assert frame["status"] == "running" and frame["subject"] == "Referral triage takes too long"
    assert frame["steps"][0] == {"name": "step_3", "title": "", "derived": False,
                                 "status": "done", "at": frame["steps"][0]["at"],
                                 "elapsed": 8.0, "error": "", "key": "", "produced": {},
                                 "artifacts": []}
    assert "record_ref" not in json.dumps(frame), "no artifact refs: this page never reads content"


def test_a_run_with_no_subject_yet_says_what_it_was_given():
    rid = _run(redis := FakeRedis())
    assert live.frame(runlog.get(rid, client=redis))["subject"] == "screening art://a/u.md"


def test_an_unknown_run_is_an_empty_frame_not_an_exception():
    assert live.frame({}) == {}


# ---------------------------------------------------------------- when to send


def test_only_a_run_that_MOVED_is_sent_again():
    """A stream that resent an unchanged run every tick would be a busy loop with extra steps —
    and `elapsed` is recomputed on every read, so it must not count as movement."""
    a = {"status": "running", "node": "step_3", "nodes": [{"name": "step_3", "status": "start"}]}
    assert live.token(a) == live.token({**a, "elapsed": 99.0})
    assert live.token(a) != live.token({**a, "node": "step_4"})
    assert live.token(a) != live.token({**a, "nodes": [{"name": "step_3", "status": "done"}]})


def test_a_settled_run_is_terminal():
    """Nothing will change again, so the stream closes rather than holding a connection open for
    an event that cannot arrive. The browser's EventSource is what decides whether to come back."""
    assert live.settled({"status": "done"}) and live.settled({"status": "failed"})
    assert not live.settled({"status": "running"}) and not live.settled({})


# ---------------------------------------------------------------- the page


def test_the_page_updates_in_place_rather_than_reloading():
    """The entire reason this exists. A page that reloaded would have the same faults as the
    Streamlit one it replaces."""
    html = live.page("e7fb30be")
    assert "EventSource" in html and "location.reload" not in html
    assert "e7fb30be" in html


def test_the_page_carries_no_secret_and_names_no_store():
    html = live.page("e7fb30be")
    for leak in ("postgres://", "redis://", "art://", "sk-"):
        assert leak not in html


# ---------------------------------------------------------------- the service


def _client(redis, password=""):
    from types import SimpleNamespace
    from starlette.testclient import TestClient
    import lab.platform.config as cfg
    live.config = SimpleNamespace(**{**cfg.__dict__, "REVIEW_APP_PASSWORD": password})
    return TestClient(live.build(SimpleNamespace(redis=lambda: redis)))


def test_the_stream_sends_a_frame_and_closes_when_the_run_settles(redis, monkeypatch):
    monkeypatch.setattr(live, "POLL_S", 0)
    rid = _run(redis, subject="Referral triage")
    runlog.node(rid, "step_3", "done", client=redis, elapsed=8.0)
    runlog.finish(rid, "done", client=redis)
    r = _client(redis).get(f"/events/{rid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert frames and frames[-1]["status"] == "done"
    assert frames[-1]["steps"][0]["name"] == "step_3"


def test_nothing_may_buffer_the_stream(redis, monkeypatch):
    monkeypatch.setattr(live, "POLL_S", 0)
    rid = _run(redis)
    runlog.finish(rid, "done", client=redis)
    r = _client(redis).get(f"/events/{rid}")
    assert r.headers.get("x-accel-buffering") == "no"


def test_the_gate_refuses_without_the_password_and_admits_with_it(redis, monkeypatch):
    monkeypatch.setattr(live, "POLL_S", 0)
    rid = _run(redis)
    runlog.finish(rid, "done", client=redis)
    c = _client(redis, password="s3cret")
    assert c.get(f"/run/{rid}").status_code == 401
    assert c.get(f"/run/{rid}?k=s3cret").status_code == 200


def test_an_open_deployment_needs_no_password_exactly_like_the_review_app(redis):
    rid = _run(redis)
    assert _client(redis).get(f"/run/{rid}").status_code == 200


def test_health_needs_no_gate_because_a_probe_holds_no_password(redis):
    assert _client(redis, password="s3cret").get("/healthz").status_code == 200


def test_the_live_port_collides_with_nothing_else_in_the_substrate():
    """9800 was the first choice and is already `DECISION_MCP_PORT`. Two services on one port is a
    deployment that starts and then does not, with a message about neither of them."""
    from lab.platform import config as cfg
    ports = [v for k, v in vars(cfg).items() if k.endswith("_PORT") and isinstance(v, int)]
    assert len(ports) == len(set(ports)), sorted(ports)


def test_the_page_asks_for_an_ABSOLUTE_stream_url():
    """A relative "events/<id>" resolves against `/run/<id>` to `/run/events/<id>` — the last path
    segment is REPLACED, not appended to — and that matches no route. Measured live: the page
    rendered, the EventSource 404'd, and all the reader saw was "reconnecting…".

    It passed a curl check because curl was given the absolute path the route actually declares.
    The browser is the only thing that resolves the relative one, so the browser is the only thing
    that could find this."""
    html = live.page("abc123")
    assert 'EventSource("/events/' in html, "absolute, from the site root"
    assert 'EventSource("events/' not in html


def test_the_declared_routes_include_the_one_the_page_asks_for():
    """Belt and braces: the URL the page builds must be a route that exists."""
    from types import SimpleNamespace
    paths = {r.path for r in live.build(SimpleNamespace(redis=lambda: None)).routes}
    assert "/events/{run_id}" in paths


def test_it_announces_its_build_like_every_other_role(monkeypatch, capsys):
    """`substrate versions` compares what a service was ASKED to run with what it SAYS it is
    running, and a service that says nothing gets "(no build line in its logs)" — which is worth
    nothing precisely when somebody is trying to find out what is serving. A NEW service inherits
    that gap unless it inherits the line, and this one did: it shipped silent."""
    from lab.platform import config as cfg

    monkeypatch.setattr(live, "build", lambda container: None)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn",
                        type("U", (), {"run": staticmethod(lambda *a, **k: None)}))
    monkeypatch.setattr("lab.substrate.container.build", lambda name: None)
    live.main()
    said = capsys.readouterr().out
    assert "live: serving" in said and cfg.build_id() in said


def test_the_line_matches_what_the_version_report_greps_for():
    """A line in a different shape is the same as no line."""
    import re
    from lab.platform import config as cfg
    assert re.search(r"build=([0-9a-f]{7,40}|dev)", f"live: serving on http://x  {cfg.build_id()}")


def test_everything_named_in___all___actually_exists():
    """It listed `app`, which this module has never had — the ASGI app is built by `build(...)`
    because the container is injected. A name in `__all__` that resolves to nothing is an import
    error waiting for the first person who trusts it."""
    for name in live.__all__:
        assert hasattr(live, name), name


# ---------------------------------------------------------------- one row per step

def test_a_step_appears_ONCE_however_many_transitions_it_recorded():
    """The run log records `start` and then `done` as separate entries, and the page rendered every
    one — so every step showed twice, once as "• receive" and again as "✓ receive". Seen on the
    live page 20 Sep 2026. A step is a THING, not a stream of its transitions."""
    h = {"nodes": [{"name": "receive", "status": "start", "attrs": {}},
                   {"name": "receive", "status": "done", "attrs": {"elapsed": 0.4}},
                   {"name": "step_3", "status": "start", "attrs": {}}]}
    steps = live.frame({**h, "run_id": "r", "status": "running"})["steps"]
    assert [s["name"] for s in steps] == ["receive", "step_3"]


def test_the_LATEST_transition_is_the_one_shown():
    h = {"nodes": [{"name": "receive", "status": "start", "attrs": {}},
                   {"name": "receive", "status": "done", "attrs": {"elapsed": 0.4}}]}
    [step] = live.frame({**h, "run_id": "r", "status": "running"})["steps"]
    assert step["status"] == "done" and step["elapsed"] == 0.4


def test_a_failure_is_not_overwritten_by_anything_after_it():
    """`fail` is terminal for that step. If a later transition could replace it the page would
    quietly lose the only row anybody is looking for."""
    h = {"nodes": [{"name": "step_5", "status": "start", "attrs": {}},
                   {"name": "step_5", "status": "fail", "attrs": {"error": "gate refused"}},
                   {"name": "step_5", "status": "start", "attrs": {}}]}
    [step] = live.frame({**h, "run_id": "r", "status": "failed"})["steps"]
    assert step["status"] == "fail" and step["error"] == "gate refused"


def test_the_order_is_the_order_they_STARTED():
    """Sorting by anything else — completion, name — would make the list jump around under a
    reader as a run progresses."""
    h = {"nodes": [{"name": "a", "status": "start", "attrs": {}},
                   {"name": "b", "status": "start", "attrs": {}},
                   {"name": "a", "status": "done", "attrs": {"elapsed": 9.0}}]}
    steps = live.frame({**h, "run_id": "r", "status": "running"})["steps"]
    assert [s["name"] for s in steps] == ["a", "b"]


# ---------------------------------------------------------------- what a step carries

def test_a_step_carries_the_detail_a_reader_opens_it_for():
    """Whatever the workload stamped on the node travels: counts and shapes, the step's own key,
    and its timings. NOT model output — this page is reachable by anyone holding the gate, and a
    run's content stays behind the review app's decision surface."""
    h = {"nodes": [{"name": "step_3", "status": "done", "ts": "2026-09-20T05:00:01",
                    "attrs": {"elapsed": 6.7, "key": "frame", "produced": {"problem": "str",
                                                                           "gap_flags": 2}}}]}
    [step] = live.frame({**h, "run_id": "r", "status": "running"})["steps"]
    assert step["key"] == "frame" and step["produced"] == {"problem": "str", "gap_flags": 2}
    assert step["at"] == "2026-09-20T05:00:01"


def test_a_step_with_nothing_stamped_still_renders():
    h = {"nodes": [{"name": "corpora", "status": "done", "attrs": {"elapsed": 1.9}}]}
    [step] = live.frame({**h, "run_id": "r", "status": "running"})["steps"]
    assert step["key"] == "" and step["produced"] == {} and step["elapsed"] == 1.9


def test_the_page_renders_each_step_as_something_a_reader_can_OPEN():
    html = live.page("r1")
    assert "<details>" in html and "<summary>" in html
    assert "function detail(" in html


def test_an_open_step_STAYS_open_when_the_next_frame_arrives():
    """A frame arrives every time the run moves. A details element that closed itself on each one
    would be unusable — the reader would be fighting the stream to read anything."""
    html = live.page("r1")
    assert "details[open]" in html and "det.open = true" in html


def test_the_page_still_carries_no_secret_and_no_reload():
    html = live.page("r1")
    assert "location.reload" not in html
    for leak in ("postgres://", "redis://", "sk-"):
        assert leak not in html


def test_a_step_keeps_the_title_its_start_declared_after_it_finishes():
    """`span_node` stamps the declaration's label on the START entry; the `done` entry it writes
    afterwards carries only timings. Collapsing to the latest transition therefore LOST the label
    at the moment the step finished — every completed step falling back to its bare id, which is
    the state the page was in when this was asked for."""
    rows = live._steps([
        {"name": "derive", "status": "start", "ts": "t0",
         "attrs": {"title": "run the screening steps"}},
        {"name": "derive", "status": "done", "ts": "t1", "attrs": {"elapsed": 2.0}}])
    assert rows[0]["title"] == "run the screening steps" and rows[0]["elapsed"] == 2.0


def test_a_later_title_wins_so_a_renamed_step_is_not_pinned_by_its_first_frame():
    rows = live._steps([
        {"name": "step_5", "status": "start", "ts": "t0", "attrs": {"title": "old"}},
        {"name": "step_5", "status": "done", "ts": "t1", "attrs": {"title": "match capabilities"}}])
    assert rows[0]["title"] == "match capabilities"


def test_a_step_that_declared_no_title_reports_none_rather_than_inventing_one():
    """The page falls back to the id. A label invented here would be this service naming somebody
    else's step, which is the whole thing being avoided."""
    rows = live._steps([{"name": "corpora", "status": "done", "ts": "t", "attrs": {}}])
    assert rows[0]["title"] == ""


def test_a_derived_step_is_carried_as_such_and_is_sticky_like_its_title():
    """"No model formed this answer" is a thing a reviewer is entitled to see: there is nothing to
    have hallucinated and nothing a retry would change. It rides the node as a flag, so this page
    still holds no list of which step numbers are deterministic."""
    rows = live._steps([
        {"name": "step_18", "status": "start", "ts": "t0",
         "attrs": {"title": "derive exposure and influence", "derived": True}},
        {"name": "step_18", "status": "done", "ts": "t1", "attrs": {"elapsed": 0.4}}])
    assert rows[0]["derived"] is True and rows[0]["title"] == "derive exposure and influence"


def test_an_ordinary_step_is_not_marked_derived():
    rows = live._steps([{"name": "step_5", "status": "done", "ts": "t", "attrs": {}}])
    assert rows[0]["derived"] is False


def test_a_step_carries_the_artifacts_it_wrote():
    rows = live._steps([{"name": "step_5", "status": "done", "ts": "t",
                         "attrs": {"artifacts": [{"ref": "art://a/one.json",
                                                  "name": "one.json"}]}}])
    assert rows[0]["artifacts"] == [{"ref": "art://a/one.json", "name": "one.json"}]


def test_a_step_that_wrote_nothing_carries_an_empty_list():
    rows = live._steps([{"name": "step_5", "status": "done", "ts": "t", "attrs": {}}])
    assert rows[0]["artifacts"] == []


def test_the_download_link_points_at_the_review_app_which_holds_the_credentials():
    """This service has no ARTIFACTS_URL, no DATABASE_URL and no S3 keys — by design, and that
    stays true. So it hands out a LINK and never bytes: the review app reads the store, and it
    authenticates the person before it does."""
    url = live.download_url("https://review.example", "art://a/one.json")
    assert url.startswith("https://review.example/?")
    assert "artifact=art%3A%2F%2Fa%2Fone.json" in url and "mode=Runs" in url


def test_no_review_app_configured_means_no_link_rather_than_a_broken_one():
    assert live.download_url("", "art://a/one.json") == ""


def test_the_frame_hands_the_page_a_finished_url_so_the_browser_builds_none():
    rid = _run(redis := FakeRedis(), subject="x")
    runlog.node(rid, "step_5", "done", client=redis,
                artifacts=[{"ref": "art://a/one.json", "name": "one.json"}])
    art = live.frame(runlog.get(rid, client=redis))["steps"][0]["artifacts"][0]
    assert art["name"] == "one.json"
    assert art["url"] == "" or "artifact=art%3A%2F%2Fa%2Fone.json" in art["url"]
