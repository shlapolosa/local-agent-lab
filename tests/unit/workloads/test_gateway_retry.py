"""A governed TOOL call survives a gateway restart, the way an agent call already does.

`survive_restart` exists for exactly one measured event: a deploy restarts the gateway with no
zero-downtime cutover, so every call in flight gets a 5xx for one to three minutes. It was wired to
agent calls (`gates.run_gated`) and never to `gateway.call` — so half the traffic was protected and
half was not. Measured 20 Sep 2026: a screening run died at `derive` with
`HTTPStatusError: 500 … /mcp/` two minutes into a CD rollout, having already completed steps 3 and 4.

Retrying is NOT unconditional. A tool that mints a durable, human-facing object must not be asked
twice: two `approvals_ask` calls are two people asked to decide one thing. Those are declared, not
guessed.
"""
import asyncio

import pytest

from lab.platform.contracts import ApprovalTools, EATools, ReferenceTools
from lab.workloads import gateway


class _Boom(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def _call(suffix, attempts, *, fail_times, status=500):
    """Run `gateway.call` against a tool that fails `fail_times` before succeeding."""
    async def fake_call_tools(headers, url, pairs):
        attempts.append(pairs[0][0])
        if len(attempts) <= fail_times:
            raise _Boom(status)
        return ["ok"]

    cfg = {"headers": {}, "mcp_url": "http://gw/mcp"}
    return asyncio.run(gateway.call(cfg, suffix, {}, _call_tools=fake_call_tools,
                                    _sleep=lambda s: asyncio.sleep(0)))


def test_a_READ_survives_the_gateway_coming_back():
    attempts = []
    assert _call(ReferenceTools.lookup, attempts, fail_times=2) == "ok"
    assert len(attempts) == 3, "retried until it worked"


def test_a_4xx_is_not_retried_because_it_will_still_be_there():
    attempts = []
    with pytest.raises(_Boom):
        _call(ReferenceTools.lookup, attempts, fail_times=9, status=403)
    assert len(attempts) == 1, "a refused key is not a restart"


@pytest.mark.parametrize("tool", [ApprovalTools.ask, EATools.stage_import])
def test_a_tool_that_mints_a_durable_object_is_never_asked_twice(tool):
    """Two `approvals_ask` calls are two people asked to decide one thing, and the second is
    invisible to the first. A failed write here is reported, not repeated."""
    attempts = []
    with pytest.raises(_Boom):
        _call(tool, attempts, fail_times=1)
    assert len(attempts) == 1


def test_the_non_retryable_set_is_declared_rather_than_inferred_from_a_name():
    """A rule like "anything containing 'ask'" would silently mis-classify the next tool added."""
    assert ApprovalTools.ask in gateway.NEVER_RETRIED
    assert ReferenceTools.lookup not in gateway.NEVER_RETRIED
