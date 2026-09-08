"""`lab.workloads.gateway` — the shape every workload shares, and what it refuses.

Preflight is the piece that earns its place: it costs zero tokens and it is the only thing standing
between a version-skewed deployment and a run that fails twenty minutes in on a tool the gateway no
longer has — or, as a live run showed, on an ARGUMENT the deployed tool no longer accepts.
"""
import asyncio

import pytest

from lab.workloads import gateway



class _Tool:
    def __init__(self, name, properties=None, closed=True):
        self.name = name
        self.inputSchema = ({"properties": {p: {} for p in properties or ()},
                             "additionalProperties": False} if closed
                            else {"properties": {p: {} for p in properties or ()}})


def _client(tools):
    class C:
        def __init__(self, transport): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def list_tools(self): return tools
    return C


def test_preflight_refuses_a_tool_that_will_not_accept_an_argument_we_send(monkeypatch):
    """The tool is THERE, under the right name, and the call still fails — because the deployed
    server is older than the workload. Measured: a screening run passed preflight, spent
    fifty-five minutes and six model calls deriving a complete record, and died at the approval on
    `'process' was unexpected`."""
    monkeypatch.setattr(gateway, "Client",
                        _client([_Tool("wf-approvals_ask", ("subject", "prompt"))]))
    with pytest.raises(RuntimeError) as e:
        asyncio.run(gateway.preflight("http://x/mcp", {},
                                      [("approvals_ask", ("subject", "prompt", "process"))]))
    assert "does not accept ['process']" in str(e.value)
    assert "costs the whole run" in str(e.value)


def test_preflight_accepts_a_tool_whose_schema_carries_every_argument(monkeypatch):
    monkeypatch.setattr(gateway, "Client",
                        _client([_Tool("wf-approvals_ask", ("subject", "prompt", "process"))]))
    asyncio.run(gateway.preflight("http://x/mcp", {},
                                  [("approvals_ask", ("subject", "prompt", "process"))]))


def test_a_bare_tool_name_still_works(monkeypatch):
    """Every existing caller passes names, and they must keep working unchanged."""
    monkeypatch.setattr(gateway, "Client", _client([_Tool("wf-approvals_ask", ("subject",))]))
    asyncio.run(gateway.preflight("http://x/mcp", {}, ["approvals_ask"]))


def test_an_open_schema_is_not_second_guessed(monkeypatch):
    """Argument checking is best effort: a server that accepts extra properties is entitled to,
    and refusing on a guess would be worse than the gap it closes."""
    monkeypatch.setattr(gateway, "Client",
                        _client([_Tool("wf-approvals_ask", ("subject",), closed=False)]))
    asyncio.run(gateway.preflight("http://x/mcp", {},
                                  [("approvals_ask", ("subject", "process"))]))
