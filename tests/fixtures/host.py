"""Shared doubles/harness hoisted from the former `test_host` module (restructure): imported by every test that
needs them (`from fixtures.host import …`) instead of test-to-test imports.

`make_root()` is the hosts' composition root for tests: the platform container with test addresses, its
tracer overridden by a local SDK provider (real span/trace ids, nothing exported) and its Redis overridden
by a FakeRedis — so a host never reaches past the container for an address or a client.
"""
import contextlib
import io
import os
import runpy
import sys

from opentelemetry.sdk.trace import TracerProvider

from fixtures.fakes import FakeRedis
from lab.platform import container as container_mod
from lab.platform import otel, runlog
from lab.workloads import identity
from lab.workloads.visio_to_archimate import host
from lab.workloads.visio_to_archimate import workflow

# The offline baseline for every host test, applied when this harness is imported (its importers —
# test_host.py, test_devui_entry.py — all need the same one): tracing off, and STATIC agent keys with
# no Entra client id/secret, so `identity.agent_headers` never reaches for MSAL. Safe to set here
# because tests/conftest.py snapshots and restores os.environ around every test, so nothing a test
# (or a `load_dotenv` inside a runpy'd `__main__`) does can erode it.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
GATEWAY_URL = "http://gw.test:4000/"
GATEWAY_MCP_URL = "http://gw.test:4000/mcp/"
os.environ["GATEWAY_URL"] = GATEWAY_URL
for _p in ("BA_AGENT", "ARCHITECT_AGENT"):
    os.environ.pop(f"{_p}_CLIENT_ID", None); os.environ.pop(f"{_p}_CLIENT_SECRET", None)
    os.environ[f"{_p}_KEY"] = f"sk-{_p.lower()}"

FIXTURE = os.path.join(ROOT, "var", "inputs", "visio_to_archimate", "malaffi-application-solution-arch.vsdx")
OUT = {"request_id": "apr-1", "status": "pending", "xml_ref": "art://x/m.archimate.xml", "xlsx_ref": "art://x/o.xlsx",
       "svg_refs": {"Overview": "art://s/o.svg"}, "review_app": "http://review.test",
       "summary": {"elements": 5, "relations": 4, "views": 1, "semantic_warnings": 0}}
_PROVIDER = TracerProvider()            # no span processor -> spans are real but never exported
_REAL_BUILD = container_mod.build      # bound now: tests patch `container_mod.build` to record composition


def make_root(service: str = "test-host", redis=None, **overrides):
    """A host container for tests: the lab addresses pointed at test hosts, real trace ids (SDK provider,
    no exporter) and a FakeRedis (or `redis`). `overrides` are container config keys."""
    root = _REAL_BUILD(service, **{"gateway_url": GATEWAY_URL, "gateway_mcp_url": GATEWAY_MCP_URL, **overrides})
    root.tracer.override(_PROVIDER.get_tracer(service))
    root.redis.override(redis if redis is not None else FakeRedis())
    return root


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))


class Patched:
    """Swap module attributes for the duration of a test; restore on exit."""

    def __init__(self, *triples):
        self.triples, self.saved = triples, []

    def __enter__(self):
        for mod, name, value in self.triples:
            self.saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)
        return self

    def __exit__(self, *exc):
        for mod, name, value in reversed(self.saved):
            setattr(mod, name, value)
        return False


def _fake_workflow(out=OUT, error=None):
    seen = {}

    async def run_workflow(cfg, inputs):
        seen["cfg"], seen["inputs"] = cfg, inputs
        if error:
            raise error
        return dict(out)
    return run_workflow, seen


def _patches(run_workflow, start, finish):
    return Patched((host, "run_workflow", run_workflow), (runlog, "start", start), (runlog, "finish", finish))


# ---------------------------------------------------------------------------- __main__
def _run_main(argv, env):
    """Execute host.py as __main__ (runpy) with the workflow + run-log + otel + container seams faked.
    Returns (seen, stdout, roots) — `roots` records the service names the module composed."""
    run_workflow, seen = _fake_workflow()
    roots = []

    def build(service, **kw):
        roots.append(service)
        return make_root(service)
    saved_argv, saved_env = sys.argv, {k: os.environ.get(k) for k in ("VISIO_DIAGRAM", "VISIO_REQUIREMENTS")}
    buf = io.StringIO()
    os.environ.pop("VISIO_DIAGRAM", None); os.environ.pop("VISIO_REQUIREMENTS", None)
    os.environ.update(env)
    sys.argv = ["host.py", *argv]
    try:
        with Patched((workflow, "run_workflow", run_workflow), (container_mod, "build", build),
                     (otel, "shutdown", lambda: None), (runlog, "start", Recorder()), (runlog, "finish", Recorder()),
                     (identity, "agent_headers", lambda p: {"Authorization": f"Bearer k-{p}"})), \
                contextlib.redirect_stdout(buf):
            runpy.run_module("lab.workloads.visio_to_archimate.host", run_name="__main__", alter_sys=True)
    finally:
        sys.argv = saved_argv
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return seen, buf.getvalue(), roots
