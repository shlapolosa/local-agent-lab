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


def test_preflight_checks_the_tool_the_call_would_actually_pick(monkeypatch):
    """A FALSE refusal is worse than the gap this closes. Checking every tool whose name ends with
    a wanted suffix would refuse a run because of a tool that would never be called — a stale
    duplicate registration, or a second server exposing a same-named tool."""
    monkeypatch.setattr(gateway, "Client", _client([
        _Tool("wf-approvals_ask", ("subject", "prompt", "process")),   # the one `resolve` picks
        _Tool("old-approvals_ask", ("subject",))]))                    # a stale duplicate
    asyncio.run(gateway.preflight("http://x/mcp", {},
                                  [("approvals_ask", ("subject", "prompt", "process"))]))


# ---------------------------------------------------------------- relevance stores, through the gateway

class _Http:
    """Stands in for the one JSON POST/GET; records the call and answers what it was given."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, payload=None, *, headers=None, timeout=None):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        import json
        return json.dumps(self.reply)


def test_vector_search_posts_the_run_identity_as_filters_and_returns_the_hits():
    http = _Http({"object": "vector_store.search_results.page",
                  "data": [{"score": 0.9, "content": [{"type": "text", "text": "Triage"}],
                            "attributes": {"record_id": "rec-9"}}]})
    hits = asyncio.run(gateway.vector_search(
        "http://gw:4000/", {"Authorization": "Bearer sk-1"}, "capability-map-x", "triage",
        filters={"pin_id": "pin-1", "run_id": "r", "process": "p", "field": "f"}, k=12, http=http))
    call = http.calls[0]
    assert call["url"] == "http://gw:4000/v1/vector_stores/capability-map-x/search"
    assert call["payload"] == {"query": "triage", "max_num_results": 12,
                               "filters": {"pin_id": "pin-1", "run_id": "r", "process": "p",
                                           "field": "f"}}
    assert call["headers"]["Authorization"] == "Bearer sk-1"
    assert hits[0]["attributes"]["record_id"] == "rec-9"


def test_preflight_refuses_a_store_the_gateway_does_not_register_for_this_identity():
    """The same contract as tools, one level over: a missing registration or grant costs zero
    tokens here rather than a 401 twenty minutes in."""
    http = _Http({"object": "list", "data": [{"vector_store_id": "capability-map-a"}]})
    with pytest.raises(RuntimeError) as e:
        asyncio.run(gateway.preflight_stores("http://gw:4000", {}, ["capability-map-a",
                                                                   "capability-map-b"], http=http))
    assert "['capability-map-b']" in str(e.value) and "vector_stores" in str(e.value)
    assert http.calls[0]["url"].startswith("http://gw:4000/vector_store/list")


def test_preflight_passes_when_every_store_is_registered_and_asks_nothing_when_none_are_needed():
    http = _Http({"object": "list", "data": [{"vector_store_id": "capability-map-a"}]})
    asyncio.run(gateway.preflight_stores("http://gw:4000", {}, ["capability-map-a"], http=http))
    asyncio.run(gateway.preflight_stores("http://gw:4000", {}, [], http=http))
    assert len(http.calls) == 1


def test_run_graph_preflights_the_stores_a_run_will_search(monkeypatch):
    """The same zero-token contract as tools: a store the gateway does not register for this
    identity refuses the run before any model is called."""
    monkeypatch.setattr(gateway, "Client", _client([_Tool("srv-x", ("a",))]))
    seen = []

    async def stores(url, headers, required, *, http=None):
        seen.append((url, list(required)))
        raise RuntimeError("not registered")
    monkeypatch.setattr(gateway, "preflight_stores", stores)
    cfg = {"mcp_url": "http://x/mcp", "headers": {}, "gateway_url": "http://gw"}
    with pytest.raises(RuntimeError):
        asyncio.run(gateway.run_graph(cfg, lambda c: None, {}, what="w", required=["x"],
                                      required_stores=["capability-map-a"]))
    assert seen == [("http://gw", ["capability-map-a"])]


# ------------------------------------------------------------------ surviving a gateway restart
class _Status(Exception):
    def __init__(self, code): super().__init__(f"Error code: {code}"); self.status_code = code


def test_a_5xx_and_a_dropped_connection_are_transient_and_a_4xx_is_not():
    from lab.workloads import gateway as G
    assert G.is_transient(_Status(502)) and G.is_transient(_Status(503))
    assert not G.is_transient(_Status(429)) and not G.is_transient(_Status(400))
    wrapped = RuntimeError("ChatClientException: service failed", _Status(502))
    assert G.is_transient(wrapped), "the client's wrapper carries the HTTP error in its args"
    class APIConnectionError(Exception): ...
    assert G.is_transient(APIConnectionError("connection dropped"))
    assert not G.is_transient(ValueError("bad json"))


def test_survive_restart_retries_across_the_waits_then_gives_up_as_it_was():
    import asyncio
    from lab.workloads import gateway as G
    calls, slept = [], []
    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _Status(502)
        return "ok"
    async def nap(s): slept.append(s)
    assert asyncio.run(G.survive_restart(flaky, waits=(1, 2, 3), sleep=nap)) == "ok"
    assert slept == [1, 2], "one wait per failure, taken from the table in order"

    async def quota():
        raise _Status(429)
    with pytest.raises(_Status) as e:
        asyncio.run(G.survive_restart(quota, waits=(1,), sleep=nap))
    assert e.value.status_code == 429 and slept == [1, 2], "a 4xx is not waited on"

    async def dead():
        raise _Status(503)
    with pytest.raises(_Status):
        asyncio.run(G.survive_restart(dead, waits=(1, 1), sleep=nap))
    assert slept == [1, 2, 1, 1], "the waits are exhausted, then the failure is the real one"


def test_a_relevance_search_waits_longer_than_a_webhook_for_the_embedder():
    from lab.workloads import gateway as G
    from lab.platform import webhook
    assert G.SEARCH_TIMEOUT_S >= 120 > webhook.TIMEOUT_S
