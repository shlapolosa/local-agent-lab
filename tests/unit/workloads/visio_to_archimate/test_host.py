"""src/lab/workloads/visio_to_archimate/host.py — the one-shot workflow host: `run_once(root, …)` (root span,
run-log start/finish through the CONTAINER's Redis client, ONE make_cfg, run_workflow), `main` (stdout
report), `_cred`, and the `__main__` composition (container.build(SERVICE) once, VISIO_DIAGRAM /
VISIO_REQUIREMENTS env for cloud jobs, the `#page` fragment stripped for the existence check, SystemExit
on a missing file). Offline: the workflow is a canned async fake, run-log writers are recorders, the
container's tracer is a local SDK provider with no exporter (real trace ids, nothing exported) and its
Redis a FakeRedis.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_host.py   (also pytest-compatible)"""
import asyncio
import contextlib
import io
import os
import tempfile

from lab.workloads.visio_to_archimate import host

from fixtures.host import (FIXTURE, OUT, Recorder, Patched, _fake_workflow, _patches, _run_main, make_root)


def test_cred_strips_bearer_from_the_agent_headers():
    assert host._cred("BA_AGENT") == "sk-ba_agent"
    with Patched((host, "agent_headers", lambda p: {"Authorization": f"Bearer  tok-{p} "})):
        assert host._cred("ARCHITECT_AGENT") == "tok-ARCHITECT_AGENT"


def test_load_schema_is_the_ba_output_contract():
    s = host._load_schema()
    assert s.get("type") == "object" and "properties" in s


def test_run_once_builds_one_cfg_runs_the_workflow_and_closes_the_run_log_via_the_container():
    run_workflow, seen = _fake_workflow()
    start, finish, traces = Recorder(), Recorder(), []
    root = make_root()
    with _patches(run_workflow, start, finish):
        out = asyncio.run(host.run_once(root, "/in/sys.vsdx#Page 1", ["/in/a.md", "art://r/b.docx"], on_trace=traces.append))
    tid = out["trace_id"]
    assert len(tid) == 32 and int(tid, 16) != 0 and traces == [tid]       # the container's tracer made the span
    assert out == {**OUT, "trace_id": tid}
    assert seen["inputs"] == {"diagram": "/in/sys.vsdx#Page 1", "requirements": ["/in/a.md", "art://r/b.docx"]}
    cfg = seen["cfg"]
    assert cfg["ba_cred"] == "sk-ba_agent" and cfg["ar_cred"] == "sk-architect_agent"
    assert cfg["mcp_url"] == root.config.gateway_mcp_url() == "http://gw.test:4000/mcp/" and cfg["run_id"] == tid
    assert cfg["traceparent"]["traceparent"].split("-")[1] == tid       # W3C header carries the run's trace
    assert cfg["ba_headers"]["traceparent"] == cfg["traceparent"]["traceparent"]
    assert cfg["schema"]["type"] == "object" and cfg["root_ctx"] is not None and cfg["tracer"] is root.tracer()
    # the run-log is written through the container's ONE Redis client, never a module-level pool
    assert start.calls == [((tid,), {"input": "sys.vsdx#Page 1", "trace_id": tid, "client": root.redis()})]
    assert finish.calls == [((tid, "done"), {"approval_id": "apr-1", "xml_ref": "art://x/m.archimate.xml",
                                             "xlsx_ref": "art://x/o.xlsx", "client": root.redis()})]


def test_run_once_marks_the_run_failed_and_reraises():
    run_workflow, _ = _fake_workflow(error=RuntimeError("gateway down " + "x" * 400))
    start, finish = Recorder(), Recorder()
    root = make_root()
    with _patches(run_workflow, start, finish):
        try:
            asyncio.run(host.run_once(root, "sys.vsdx"))
            raise AssertionError("the workflow error must propagate")
        except RuntimeError as e:
            assert str(e).startswith("gateway down")
    assert len(start.calls) == 1
    (rid, status), fields = finish.calls[0]
    assert status == "failed" and fields["error"].startswith("RuntimeError: gateway down")
    assert len(fields["error"]) == len("RuntimeError: ") + 300          # error text is bounded
    assert fields["client"] is root.redis()


def test_run_once_without_on_trace_and_requirements():
    run_workflow, seen = _fake_workflow()
    with _patches(run_workflow, Recorder(), Recorder()):
        out = asyncio.run(host.run_once(make_root(), "sys.vsdx", None))
    assert seen["inputs"]["requirements"] == [] and out["request_id"] == "apr-1"


def test_main_prints_the_report_and_flushes_the_exporter():
    run_workflow, _ = _fake_workflow()
    shutdown = Recorder()
    buf = io.StringIO()
    with _patches(run_workflow, Recorder(), Recorder()), Patched((host, "_shutdown", shutdown)), \
            contextlib.redirect_stdout(buf):
        asyncio.run(host.main(make_root(), "/in/sys.vsdx", ["/in/a.md"]))
    text = buf.getvalue()
    assert "input:    /in/sys.vsdx\nrequires: /in/a.md\n" in text
    assert "trace id: " in text and "model elements/relations: 5/4  views: 1  semantic warnings: 0" in text
    assert "artifacts: art://x/m.archimate.xml  (+1 svg refs)" in text
    assert "approval requested: apr-1 -> pending" in text and "review at: http://review.test" in text
    assert len(shutdown.calls) == 1


def test_main_module_exits_on_a_missing_input():
    for argv, env in (([], {"VISIO_DIAGRAM": "/nonexistent/sys.vsdx"}),
                      ([FIXTURE, "-r", "/nonexistent/req.md"], {}),
                      (["/nonexistent/sys.vsdx#Page 1"], {})):
        try:
            _run_main(argv, env)
            raise AssertionError("SystemExit expected")
        except SystemExit as e:
            assert str(e).startswith("no such file: /nonexistent/")


def test_main_module_composes_one_container_and_runs_cli_inputs_with_a_page_fragment():
    with tempfile.TemporaryDirectory() as d:
        req = os.path.join(d, "req.md"); open(req, "w").write("# req")
        seen, text, roots = _run_main([FIXTURE + "#Shafafiya", "-r", req], {})
    assert roots == [host.SERVICE]                                       # container.build(SERVICE), exactly once
    assert seen["inputs"] == {"diagram": FIXTURE + "#Shafafiya", "requirements": [req]}
    assert seen["cfg"]["ba_cred"] == "k-BA_AGENT" and "approval requested: apr-1 -> pending" in text


def test_main_module_takes_cloud_job_inputs_from_env_when_no_cli_args():
    seen, _, _ = _run_main([], {"VISIO_DIAGRAM": FIXTURE, "VISIO_REQUIREMENTS": "art://r/a.md art://r/b.docx"})
    assert seen["inputs"] == {"diagram": FIXTURE, "requirements": ["art://r/a.md", "art://r/b.docx"]}
    seen, _, _ = _run_main([], {"VISIO_DIAGRAM": FIXTURE, "VISIO_REQUIREMENTS": ""})
    assert seen["inputs"] == {"diagram": FIXTURE, "requirements": []}
    # no env at all -> the bundled default fixture (git-ignored, generated at container start)
    if os.path.exists(host.DEFAULT_VSDX):
        seen, _, _ = _run_main([], {})
        assert seen["inputs"] == {"diagram": str(host.DEFAULT_VSDX), "requirements": []}
    else:
        try:
            _run_main([], {})
            raise AssertionError("SystemExit expected")
        except SystemExit as e:
            assert str(e) == f"no such file: {host.DEFAULT_VSDX}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
