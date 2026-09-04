"""pytest wiring for the suite. `src/` and `tests/` are on sys.path (pyproject `pythonpath`), so tests
import the shared doubles as `from fixtures.fakes import FakeRedis` — and still run as plain scripts with
PYTHONPATH=src:tests (tests/run.sh sets it). The fixtures below wrap the same doubles for pytest users.

ISOLATION (why the whole suite runs in ONE pytest process again)
---------------------------------------------------------------
These modules used to pin `os.environ` at IMPORT time, so in a shared process the last-imported test
module's environment leaked into every other module's tests. Two process-global seams are now closed
here, once, for every test — so a test module never has to pin anything at import:

  * `_isolated_env` — os.environ is snapshotted before each test and restored after it. That covers
    ad-hoc `os.environ[...] = ...` inside a test AND the big one: `runpy`-ing a module whose
    `__main__` block calls `load_dotenv()` (devui_entry) used to pour the real `.env` — Entra client
    ids included — into the process and make later tests reach for MSAL.
  * `_isolated_otel` — OpenTelemetry allows ONE global TracerProvider per process and
    `lab.platform.otel` is first-call-wins, so the module that installs a provider (tests/unit/
    platform/test_otel.py) would otherwise decide what every later `container.tracer()` returns.
    The OTel globals and `otel._STATE` are snapshotted and restored around each test.

`pytest_configure` sets the offline baseline BEFORE collection imports any test module: tracing off,
so importing a server or building a container never installs an exporter.
"""
import os

import pytest

from fixtures.fakes import FakeRedis, patched_client


def pytest_configure(config):
    """The offline baseline, established BEFORE collection imports any test module.

    `import litellm` calls `load_dotenv()`, so the FIRST test module that imports it (the gateway
    tier does, at module scope) used to pour the whole repo `.env` into the process for the rest of
    the session: real Entra client secrets (a unit test then made a live MSAL token request), the
    Neon `DATABASE_URL`, the cloud `REDIS_URL`. Import it here and put the environment back, so the
    suite's baseline is the shell's environment and nothing else; later imports are no-ops.
    """
    before = dict(os.environ)
    import litellm  # noqa: F401  — imported for its side effect, so it happens exactly once, here
    os.environ.clear()
    os.environ.update(before)
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)


@pytest.fixture(autouse=True)
def _isolated_env():
    """Every test gets the environment it started with back. Higher-scoped fixtures (a module's own
    env pinning) are set up before this one, so their values are part of the snapshot and survive."""
    saved = dict(os.environ)
    yield
    if os.environ != saved:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture(autouse=True)
def _isolated_otel():
    """Restore the process-global tracer provider (OTel's `set_tracer_provider` is once-only) and
    `lab.platform.otel`'s install-once state, so a test that installs a provider cannot decide what
    the next test's `otel.tracer()` returns."""
    from opentelemetry import trace as _trace
    from opentelemetry.util._once import Once

    from lab.platform import otel

    saved_provider = _trace._TRACER_PROVIDER
    saved_once = _trace._TRACER_PROVIDER_SET_ONCE
    saved_state = dict(otel._STATE)
    yield
    _trace._TRACER_PROVIDER = saved_provider
    _trace._TRACER_PROVIDER_SET_ONCE = saved_once if saved_provider is not None else Once()
    otel._STATE.clear()
    otel._STATE.update(saved_state)


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def patched_redis():
    """Route lab.platform.redis_client.client() to a FakeRedis for the test."""
    with patched_client(FakeRedis()) as r:
        yield r
