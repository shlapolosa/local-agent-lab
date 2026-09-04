"""src/lab/workloads/visio_to_archimate/devui_entry.py — the DevUI host: `build_cfg(root)` (the tracer and
every address from DevUI's OWN container — host.SERVICE is never mutated; one session span whose context parents everything,
W3C traceparent, the SAME make_cfg as host.run_once with run_id=None), `build(root)` (a real Workflow,
named and described for DevUI), `main()` (container.build(SERVICE) once; argparse flags ->
enable_instrumentation / serve arguments, the stdout banner) and the module entry via runpy.
Offline: the container's tracer is a local SDK provider with no exporter, host._cred is a stub (no MSAL),
the DevUI `serve` and AF `enable_instrumentation` are recorders. Same collaborator fakes as test_host.py.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_devui_entry.py   (also pytest-compatible)"""
import contextlib
import importlib
import io
import json
import os
import runpy
import sys

import pytest

import agent_framework.devui as devui_mod
import agent_framework.observability as obs_mod
from fixtures.host import Patched, Recorder, make_root
from lab.platform import config
from lab.platform import container as container_mod
from lab.workloads.visio_to_archimate import devui_entry as D
from lab.workloads.visio_to_archimate import host as H

HOST_SERVICE = "process-visio-to-archimate"


@pytest.fixture(autouse=True)
def _devui_env(monkeypatch):
    """devui_entry loads the repo .env only when it IS the script (never on import), so a plain import
    adds nothing to the environment; the runpy entry test still gets it with override=False — hence
    the pins below (an empty OTLP endpoint means "tracing off" to lab.platform.otel and blocks the
    .env value, and the agent credentials must not reach for MSAL). `DEVUI_PORT` is read once, at
    devui_entry's import, so the module is reloaded under the pin and reloaded back afterwards;
    tests/conftest.py restores the environment the .env load pours in. Addresses come from the
    CONTAINER (lab.platform.config, read once at ITS import), so those are pinned on the config
    module, not the environment."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("GATEWAY_URL", "http://gw.test:4000/")
    monkeypatch.setenv("DEVUI_PORT", "8099")
    monkeypatch.setenv("JAEGER_UI_URL", "http://jaeger.test")
    for prefix in ("BA_AGENT", "ARCHITECT_AGENT"):
        monkeypatch.setenv(f"{prefix}_CLIENT_ID", ""); monkeypatch.setenv(f"{prefix}_CLIENT_SECRET", "")
        monkeypatch.setenv(f"{prefix}_KEY", f"sk-{prefix.lower()}")
    monkeypatch.setattr(config, "JAEGER_UI_URL", "http://jaeger.test")
    importlib.reload(D)
    yield
    monkeypatch.undo()
    importlib.reload(D)


def _seams(*extra):
    return Patched((H, "_cred", lambda p: f"cred-{p}"),
                   (H, "_load_schema", lambda: {"type": "object", "properties": {}, "faked": True}),
                   *extra)


def test_module_constants():
    assert D.SERVICE == "process-visio-to-archimate-devui" and D.SERVICE != H.SERVICE
    assert D.DEFAULT_PORT == 8099                                          # DEVUI_PORT env honoured at import
    assert D.DEFAULT_DIAGRAM.endswith("inputs/visio_to_archimate/malaffi-application-solution-arch.vsdx#Shafafiya")
    assert D.DEFAULT_INPUT == {"diagram": D.DEFAULT_DIAGRAM, "requirements": []}
    assert json.loads(json.dumps(D.DEFAULT_INPUT)) == D.DEFAULT_INPUT     # what the banner tells the user to paste
    assert D.DEFAULT_DIAGRAM.startswith(str(D.config.VAR_DIR))            # inputs live under var/, never in the package


def test_build_cfg_uses_its_own_container_and_builds_host_cfg_under_one_session_span():
    root = make_root(D.SERVICE)
    with _seams():
        cfg, trace_id = D.build_cfg(root)
    assert H.SERVICE == HOST_SERVICE                                       # the host's service name is NOT mutated
    assert root.config.service_name() == D.SERVICE                        # DevUI's container carries ITS name
    assert len(trace_id) == 32 and int(trace_id, 16) != 0
    assert cfg["ba_cred"] == "cred-BA_AGENT" and cfg["ar_cred"] == "cred-ARCHITECT_AGENT"
    assert cfg["mcp_url"] == "http://gw.test:4000/mcp/" and cfg["run_id"] is None
    assert cfg["schema"] == {"type": "object", "properties": {}, "faked": True}
    assert cfg["traceparent"]["traceparent"].split("-")[1] == trace_id   # the session span parents every run
    assert cfg["ba_headers"] == {"Authorization": "Bearer cred-BA_AGENT", **cfg["traceparent"]}
    assert cfg["ar_headers"]["Authorization"] == "Bearer cred-ARCHITECT_AGENT"
    assert cfg["root_ctx"] is not None and cfg["tracer"] is root.tracer()  # the tracer comes from the container
    # the session span was ENDED (exported) yet its context is still a valid parent
    with cfg["tracer"].start_as_current_span("node", context=cfg["root_ctx"]) as s:
        assert format(s.get_span_context().trace_id, "032x") == trace_id
    # a second session gets its own trace id (nothing is cached)
    with _seams():
        _, trace_id2 = D.build_cfg(root)
    assert trace_id2 != trace_id


def test_build_cfg_takes_the_gateway_address_from_the_container_not_the_environment():
    """The Azure/APIM swap is an .env edit read ONCE by lab.platform.config into the container — a host
    never re-derives the address itself (so it cannot drift from the other hosts)."""
    root = make_root(D.SERVICE, gateway_mcp_url="https://apim.example/mcp/")
    with _seams(), Patched((os, "environ", {**os.environ, "GATEWAY_URL": "http://ignored.test"})):
        cfg, _ = D.build_cfg(root)
    assert cfg["mcp_url"] == "https://apim.example/mcp/"


def test_build_returns_a_named_described_workflow():
    with _seams():
        wf, trace_id = D.build(make_root(D.SERVICE))
    assert len(trace_id) == 32
    assert wf.name == "visio-to-archimate"
    assert wf.description.startswith("Visio/diagram (+ requirements) -> BA -> resolve existing (ADOIT) -> Architect ->")
    assert wf.description.endswith("Input is JSON, e.g. " + json.dumps(D.DEFAULT_INPUT))
    assert [getattr(e, "id", e) for e in wf.get_executors_list()] == [
        "ba", "resolve_existing", "architect_design", "store", "architect_finalize", "stage_import"]


# ---------------------------------------------------------------------------- main()
class FakeWorkflow:
    name = "visio-to-archimate"

    def get_executors_list(self):
        return [type("E", (), {"id": "ba"})(), "store"]


def _main(argv, *, real_build=False, **root_overrides):
    serve, enable, built = Recorder(), Recorder(), []
    buf = io.StringIO()

    def build_container(service, **kw):
        built.append(service)
        return make_root(service, **root_overrides)
    extra = () if real_build else ((D, "build", lambda root: (FakeWorkflow(), "f" * 32)),)
    with _seams(*extra), Patched((devui_mod, "serve", serve), (obs_mod, "enable_instrumentation", enable),
                                 (container_mod, "build", build_container)), \
            contextlib.redirect_stdout(buf):
        D.main(argv)
    assert len(serve.calls) == 1 and len(enable.calls) == 1
    assert built == [D.SERVICE] and H.SERVICE == HOST_SERVICE     # ONE container, DevUI's own service name
    return serve.calls[0][1], enable.calls[0][1], buf.getvalue()


def test_main_default_flags():
    kw, inst, text = _main([])
    assert inst == {"enable_sensitive_data": False}                        # prompt bodies stay off by default
    assert kw["port"] == 8099 and kw["host"] == "127.0.0.1" and kw["auto_open"] is False
    assert kw["ui_enabled"] is True and kw["auth_enabled"] is False and kw["instrumentation_enabled"] is False
    assert len(kw["entities"]) == 1 and kw["entities"][0].name == "visio-to-archimate"
    assert "DevUI:          http://127.0.0.1:8099   (UI; auth off)\n" in text
    assert "workflow:       visio-to-archimate  nodes: ba -> store\n" in text
    assert "gateway MCP:    http://gw.test:4000/mcp/   (./lab.sh up first)\n" in text
    assert f"paste as input: {json.dumps(D.DEFAULT_INPUT)}\n" in text
    assert f"session trace:  http://jaeger.test/trace/{'f' * 32}   (service {D.SERVICE}; every run this session joins it)\n" in text
    assert text.rstrip().endswith("NOTE: each run makes real gateway LLM + MCP calls and stages an ADOIT approval request.")


def test_main_headless_auth_open_port_and_sensitive_spans():
    kw, inst, text = _main(["--headless", "--auth", "--open", "--port", "9001", "--sensitive-spans"])
    assert inst == {"enable_sensitive_data": True}
    assert kw["port"] == 9001 and kw["ui_enabled"] is False and kw["auth_enabled"] is True and kw["auto_open"] is True
    assert kw["instrumentation_enabled"] is False                          # never forced on by serve()
    assert "DevUI:          http://127.0.0.1:9001   (API only; auth on)\n" in text
    kw, inst, text = _main(["--headless"])
    assert kw["ui_enabled"] is False and kw["auth_enabled"] is False and inst == {"enable_sensitive_data": False}
    assert "(API only; auth off)" in text
    kw, _, text = _main(["--auth"])
    assert kw["ui_enabled"] is True and kw["auth_enabled"] is True and "(UI; auth on)" in text


def test_main_with_the_real_build_serves_the_named_workflow():
    kw, _, text = _main(["--headless"], real_build=True)
    wf = kw["entities"][0]
    assert wf.name == "visio-to-archimate" and "nodes: ba -> resolve_existing -> architect_design -> store -> architect_finalize -> stage_import" in text
    trace_id = text.split("/trace/")[1].split()[0]
    assert len(trace_id) == 32 and int(trace_id, 16) != 0


def test_main_jaeger_url_comes_from_the_container_and_bad_args_exit():
    _, _, text = _main([], jaeger_ui_url="http://jaeger.other")
    assert "session trace:  http://jaeger.other/trace/" in text
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            D.main(["--port", "not-a-number"])
        raise AssertionError("argparse must exit")
    except SystemExit as e:
        assert e.code == 2 and "invalid int value" in buf.getvalue()


# ---------------------------------------------------------------------------- __main__ (runpy)
def test_module_entry_runs_main():
    serve, enable = Recorder(), Recorder()
    saved_argv, buf = sys.argv, io.StringIO()
    sys.argv = ["devui_entry.py", "--headless", "--port", "8123"]
    try:
        with _seams(), Patched((devui_mod, "serve", serve), (obs_mod, "enable_instrumentation", enable),
                               (container_mod, "build", lambda service, **kw: make_root(service))), \
                contextlib.redirect_stdout(buf):
            runpy.run_module("lab.workloads.visio_to_archimate.devui_entry", run_name="__main__", alter_sys=True)
    finally:
        sys.argv = saved_argv
    kw = serve.calls[0][1]
    assert kw["port"] == 8123 and kw["ui_enabled"] is False and kw["entities"][0].name == "visio-to-archimate"
    assert enable.calls == [((), {"enable_sensitive_data": False})]
    assert "DevUI:          http://127.0.0.1:8123   (API only; auth off)" in buf.getvalue()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
