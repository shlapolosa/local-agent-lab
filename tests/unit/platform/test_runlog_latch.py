"""A Redis failure must not disable the run log for callers holding a working client.

`_redis` latches on ANY failure: one notice, then print-only for RETRY_AFTER_S. That is right for
the shared POOL — a run must not spend a round trip per node against a Redis that is down. It is
wrong for a caller that passed its OWN client, whose health the pool says nothing about.

Measured in CI 20 Sep 2026: a workload step stamped its shape through the pooled client, CI has no
Redis, the latch closed — and ten unrelated tests in a LATER file failed with `KeyError: 'status'`
because their `FakeRedis` writes were silently dropped. The suite passed locally only because a
brew Redis happened to be running.
"""
import time

import pytest

from fixtures.fakes import FakeRedis
from lab.platform import runlog


@pytest.fixture(autouse=True)
def _clear():
    runlog._RETRY_AT.clear()
    yield
    runlog._RETRY_AT.clear()


def _boom(_r):
    raise RuntimeError("redis is down")


def test_a_failing_client_latches_ITSELF_so_a_run_does_not_pay_per_node():
    assert runlog._redis(_boom) is None
    assert any(v > time.time() for v in runlog._RETRY_AT.values()), "not retried immediately"


def test_a_latched_client_does_not_silence_a_DIFFERENT_one():
    """The bug. One client being down says nothing about another's, and a single global latch meant
    it did — a workload stamping through the pool silenced every FakeRedis in the process."""
    runlog._redis(_boom)                                   # latch the pool
    r = FakeRedis()
    runlog.start("run-1", input="x", process="p", client=r)
    runlog.finish("run-1", "done", client=r)
    assert runlog.get("run-1", client=r)["status"] == "done"


def test_one_bad_client_does_not_latch_the_POOL():
    """Symmetry: the pool was never the thing that failed."""
    bad = FakeRedis()
    runlog._redis(_boom, client=bad)
    assert bad in runlog._RETRY_AT, "the client that failed is the one held back"
    assert runlog._redis(lambda r: "ok") == "ok", "the pool is untouched"


def test_success_clears_that_clients_latch():
    r = FakeRedis()
    runlog._redis(_boom, client=r)
    runlog._RETRY_AT[r] = time.time() - 1                  # the window elapses
    assert runlog._redis(lambda c: "ok", client=r) == "ok"
    assert r not in runlog._RETRY_AT
