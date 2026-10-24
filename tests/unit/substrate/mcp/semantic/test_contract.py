"""The semantic tools' CONTRACT FILE — what an external consumer (SAF) vendors verbatim.

Pinned: the document is deterministic (same server, same bytes), names every tool the server
registers with its schemas, carries the grant tuples and a stability per tool, and leaks nothing
process-specific (fastmcp's `meta`). Offline: a fake FastMCP-like object, no server import.
"""
import json

from lab.platform.contracts import SemanticTools
from lab.substrate.mcp.semantic import contract


class _Tool:
    def __init__(self, name, schema):
        self.name, self.schema = name, schema

    def to_mcp_tool(self):
        tool = self

        class M:
            def model_dump(self, exclude_none=True):
                return {"name": tool.name, "description": f"{tool.name} does a thing",
                        "inputSchema": tool.schema, "meta": {"fastmcp": {"tags": []}}}
        return M()


class _Mcp:
    def __init__(self, tools):
        self.tools = tools

    async def list_tools(self):
        return list(self.tools)


def _render(names):
    return contract.render(_Mcp([_Tool(n, {"type": "object", "properties": {"b": {}, "a": {}}})
                                 for n in names]))


def test_the_document_is_deterministic_and_sorted():
    a, b = _render(["semantic_b", "semantic_a"]), _render(["semantic_a", "semantic_b"])
    assert contract.dumps(a) == contract.dumps(b)
    assert [t["name"] for t in a["tools"]] == ["semantic_a", "semantic_b"]


def test_each_tool_carries_its_schema_and_no_process_specific_meta():
    doc = _render([SemanticTools.vocab_propose])
    tool = doc["tools"][0]
    assert tool["inputSchema"]["type"] == "object" and "meta" not in tool
    assert doc["server"] == SemanticTools.SERVER and doc["contract_version"] == contract.VERSION


def test_grants_and_stability_come_from_the_catalogue():
    doc = _render([SemanticTools.vocab_propose, SemanticTools.vocab_resolve, SemanticTools.view_corpus])
    assert SemanticTools.vocab_link in doc["grants"]["PIPELINE"]
    assert doc["stability"][SemanticTools.vocab_propose] == "stable"
    assert doc["stability"][SemanticTools.vocab_resolve] == "in-flux"
    assert doc["stability"][SemanticTools.view_corpus] == "internal"


def test_every_catalogued_tool_has_a_stability_and_the_tiers_do_not_overlap():
    stability = SemanticTools.stability()
    assert set(stability) == set(SemanticTools.names())
    assert set(stability.values()) <= {"stable", "in-flux", "internal"}
    assert not set(SemanticTools.STABLE) & set(SemanticTools.IN_FLUX)
    assert set(SemanticTools.STABLE) | set(SemanticTools.IN_FLUX) <= SemanticTools.names()


def test_the_rendered_text_is_json_with_a_trailing_newline():
    text = contract.dumps(_render(["semantic_a"]))
    assert text.endswith("\n") and json.loads(text)["tools"][0]["name"] == "semantic_a"
