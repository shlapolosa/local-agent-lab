"""src/lab/workloads/visio_to_archimate/agents.py — the workflow's Agent Framework agents: instruction
composition (prompts + method + the registered visio-reader skill, frontmatter stripped), the
tools-mode addenda, the local-dev function tools, the gateway MCP tool factories (allow-lists +
per-agent identity headers), and `make_agent` (OpenAIChatClient -> gateway /v1, stateless,
traceparent as default headers, bounded timeout/retries). Offline: constructing an OpenAI client,
an MCP tool and an Agent opens no connection.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_agents.py   (also pytest-compatible)"""
import importlib
import os
import sys
import tempfile

import pytest

from lab.platform import config
from lab.workloads.visio_to_archimate import agents as A

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
GATEWAY_URL = "http://gw.test:4000/"


@pytest.fixture(autouse=True)
def _test_gateway(monkeypatch):
    """The agents take the gateway address from `lab.platform.config` (read once, at ITS import) —
    so point the CONFIG at a test host, not the environment, and undo the model/store toggles a
    reloading test may leave behind."""
    monkeypatch.setattr(config, "GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setattr(config, "GATEWAY_MCP_URL", GATEWAY_URL.rstrip("/") + "/mcp/")
    monkeypatch.delenv("AGENT_RESPONSES_STORE", raising=False)
    monkeypatch.delenv("VISIO_AGENT_MODEL", raising=False)
    yield
    if (A.MODEL, A.STORE) != ("kimi-k3", False):
        importlib.reload(A)

FIXTURE = os.path.join(ROOT, "var", "inputs", "visio_to_archimate", "malaffi-application-solution-arch.vsdx")
HERE = os.path.join(ROOT, "src", "lab", "workloads", "visio_to_archimate")


def _prompt(rel):
    return open(os.path.join(HERE, rel), encoding="utf-8").read()


def test_strip_frontmatter():
    assert A._strip_frontmatter("---\nname: x\ndescription: y\n---\n\n# Body\ntext") == "# Body\ntext"
    assert A._strip_frontmatter("  ---\nname: x\n---\nbody") == "body"
    assert A._strip_frontmatter("# no frontmatter\n---\nrule") == "# no frontmatter\n---\nrule"


def test_instructions_compose_prompts_method_and_skill():
    ba = A.ba_instructions()
    assert ba.startswith(_prompt("prompts/ba.md"))
    assert "## Conversion method\n\n" + _prompt("references/method.md") in ba
    assert "## Visio-reading skill\n\n" in ba and not ba.split("## Visio-reading skill")[1].lstrip().startswith("---")
    ar = A.architect_instructions()
    assert ar == _prompt("prompts/architect.md") + "\n\n## Conversion method\n\n" + _prompt("references/method.md")
    assert A.resolve_instructions() == _prompt("prompts/resolve.md")
    assert A.ba_tools_addendum() == "\n\n" + _prompt("prompts/ba_tools.md")
    assert A.architect_tools_addendum() == "\n\n" + _prompt("prompts/architect_tools.md")


def test_local_dev_function_tools_read_paths():
    read_vsdx = A.read_vsdx_tool()
    assert read_vsdx.__name__ == "read_vsdx" and "BEFORE describing" in read_vsdx.__doc__
    d = read_vsdx(FIXTURE + "#Shafafiya")
    assert set(d) >= {"pages", "shapes", "connectors"} and d["page"] == "Shafafiya"
    read_document = A.read_document_tool()
    assert read_document.__name__ == "read_document"
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "req.txt"); open(p, "w").write("Users MUST authenticate.")
        assert "Users MUST authenticate." in read_document(p)


def test_mcp_tool_factories_filter_to_the_governed_tools_with_the_callers_identity():
    ba = A.ba_tools({"Authorization": "Bearer ba-key", "traceparent": "00-a-b-01"})
    ar = A.architect_tools({"Authorization": "Bearer ar-key"})
    assert type(ba).__name__ == "MCPStreamableHTTPTool" and ba.name == "storage" and ar.name == "ea-tools"
    assert set(ba.allowed_tools) == set(A.BA_MCP_TOOLS) and set(ar.allowed_tools) == set(A.ARCHITECT_MCP_TOOLS)
    assert "adoit_mcp-adoit_request_import" not in ar.allowed_tools         # import staging stays human-gated
    assert ba._header_provider({}) == {"Authorization": "Bearer ba-key", "traceparent": "00-a-b-01"}
    assert ar._header_provider({}) == {"Authorization": "Bearer ar-key"}
    hdr = ba._header_provider({}); hdr["x"] = 1
    assert ba._header_provider({}) == {"Authorization": "Bearer ba-key", "traceparent": "00-a-b-01"}  # a copy
    for t in (ba, ar):
        assert t.url == "http://gw.test:4000/mcp/"


def test_make_agent_points_at_the_gateway_stateless_with_trace_headers(monkeypatch):
    monkeypatch.setenv("AGENT_REQUEST_TIMEOUT", "42"); monkeypatch.setenv("AGENT_MAX_RETRIES", "1")
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "1234")
    ag = A.make_agent("ba", "do the BA thing", "sk-ba", traceparent={"traceparent": "00-abc-def-01"})
    for k in ("AGENT_REQUEST_TIMEOUT", "AGENT_MAX_RETRIES", "AGENT_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(k)
    assert type(ag).__name__ == "Agent" and ag.name == "ba"
    http = ag.client.client
    assert str(http.base_url) == "http://gw.test:4000/v1/" and http.api_key == "sk-ba"
    assert dict(http.default_headers)["traceparent"] == "00-abc-def-01"
    assert float(http.timeout) == 42.0 and http.max_retries == 1
    assert ag.default_options["store"] is False and ag.default_options["max_tokens"] == 1234
    # defaults: no traceparent, 300 s timeout, 3 retries, 32000 output cap
    ag2 = A.make_agent("architect", "x", "sk-ar")
    http2 = ag2.client.client
    assert "traceparent" not in dict(http2.default_headers) and float(http2.timeout) == 300.0 and http2.max_retries == 3
    assert ag2.default_options["max_tokens"] == 32000


def test_model_and_store_toggles_come_from_env(monkeypatch):
    assert A.MODEL == "kimi-k3" and A.STORE is False
    monkeypatch.setenv("AGENT_RESPONSES_STORE", "TRUE"); monkeypatch.setenv("VISIO_AGENT_MODEL", "glm-flash")
    try:
        importlib.reload(A)
        assert A.STORE is True and A.MODEL == "glm-flash"
    finally:
        monkeypatch.delenv("AGENT_RESPONSES_STORE"); monkeypatch.delenv("VISIO_AGENT_MODEL")
        importlib.reload(A)
    assert A.STORE is False and A.MODEL == "kimi-k3"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
