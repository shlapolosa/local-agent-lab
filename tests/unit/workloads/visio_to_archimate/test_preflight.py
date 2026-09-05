"""The workload refuses to start a run when the gateway does not expose the tools it needs.

Why this exists: a cloud run failed 320 s in with "tool *adoit_request_import not exposed by gateway"
because the workload was deployed from one commit and the gateway from another. The guard was right
but fired at the step that needed the tool, AFTER the reading agent had run and spent tokens. The tool
list is known before the first node executes, so the mismatch must be refused there. Offline: the MCP
client is faked; no gateway, no Redis, no LLM.
"""
import asyncio

import pytest

from lab.platform.contracts import EATools, SemanticTools, StorageTools
from lab.workloads import gateway
from lab.workloads.visio_to_archimate import workflow as W


def _exposed(*catalogues):
    """What a healthy gateway lists: every tool of each server, gateway-qualified."""
    return [c.gateway(t) for c in catalogues for t in c.names()]


class FakeClient:
    def __init__(self, names): self.names = names
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def list_tools(self):
        return [type("T", (), {"name": n})() for n in self.names]


def _patch_client(monkeypatch, names):
    # the transport is shared by every workload (lab.workloads.gateway); this still exercises it
    # THROUGH this workload, which is what must keep working — its own tool list, its own message.
    monkeypatch.setattr(gateway, "Client", lambda *a, **k: FakeClient(names))
    monkeypatch.setattr(W, "StreamableHttpTransport", lambda *a, **k: None)


def test_required_tools_come_from_the_contract_not_from_literals():
    """The set is derived from the catalogues, so a rename cannot leave a stale literal behind."""
    required = W.REQUIRED_TOOLS
    assert required, "the workload must declare what it needs"
    assert EATools.stage_import in required
    assert StorageTools.read_vsdx in required
    assert SemanticTools.store_spec in required


def test_preflight_is_alias_agnostic_like_the_call_path(monkeypatch):
    """The workload resolves tools by SUFFIX, so a gateway that renames its server alias still works.
    Preflight must not be stricter than the code it guards, or it fails runs that would succeed."""
    _patch_client(monkeypatch, [f"anything-{t}" for t in W.REQUIRED_TOOLS])
    asyncio.run(W.preflight({"ar_headers": {}, "mcp_url": "http://gw/mcp/"}))


def test_preflight_passes_when_the_gateway_exposes_everything(monkeypatch):
    _patch_client(monkeypatch, _exposed(EATools, SemanticTools, StorageTools))
    asyncio.run(W.preflight({"ar_headers": {}, "ba_headers": {}, "mcp_url": "http://gw/mcp/"}))


def test_preflight_refuses_a_version_mismatch_and_names_what_is_missing(monkeypatch):
    """The exact production failure: the gateway serves the renamed tools, the workload expects the
    old ones (or vice versa). It must fail BEFORE any node runs, naming the gap."""
    stale = [n for n in _exposed(EATools, SemanticTools, StorageTools)
             if not n.endswith(EATools.stage_import)]     # the tool was renamed away
    _patch_client(monkeypatch, stale)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(W.preflight({"ar_headers": {}, "ba_headers": {}, "mcp_url": "http://gw/mcp/"}))
    msg = str(e.value)
    assert EATools.stage_import in msg
    assert "version" in msg.lower() or "deploy" in msg.lower(), msg   # says WHY, not just what


def test_run_workflow_preflights_before_building_or_running(monkeypatch):
    """Ordering is the whole point: no node may execute when the contract cannot be satisfied."""
    order = []

    async def fake_preflight(cfg):
        order.append("preflight")
    monkeypatch.setattr(W, "preflight", fake_preflight)
    monkeypatch.setattr(W, "build_workflow", lambda cfg: order.append("build") or _FakeWf())
    out = asyncio.run(W.run_workflow({"run_id": None}, {"diagram": "art://a/b.vsdx", "requirements": []}))
    assert order == ["preflight", "build"] and out == {"ok": True}


class _FakeWf:
    async def run(self, inputs):
        return type("R", (), {"get_outputs": lambda self: [{"ok": True}]})()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
