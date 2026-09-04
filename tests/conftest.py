"""pytest wiring for the suite. `src/` and `tests/` are on sys.path (pyproject `pythonpath`), so tests
import the shared doubles as `from fixtures.fakes import FakeRedis` — and still run as plain scripts with
PYTHONPATH=src:tests (tests/run.sh sets it). The fixtures below wrap the same doubles for pytest users.
"""
import pytest

from fixtures.fakes import FakeRedis, patched_client


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def patched_redis():
    """Route lab.platform.redis_client.client() to a FakeRedis for the test."""
    with patched_client(FakeRedis()) as r:
        yield r
