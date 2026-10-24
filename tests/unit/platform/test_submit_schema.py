"""`input_schema(spec)` — the ONE JSON schema of a process's submit body, shared by every inbound surface.

The MCP tool, the REST route and the generated OpenAPI document all describe the same submit call. If
each derived its own schema they would drift; so the schema is computed once, in the platform, and the
MCP server builds its tool signature from the same parameter list. The parity test below is exact on
purpose — two descriptions of one contract must agree in both directions.
"""
import asyncio

import pytest
from fastmcp import Client

from lab.platform.contracts import PROCESSES, InputKind
from lab.platform.submit_schema import annotation_of, input_schema, submit_parameters

STARTABLE = [s for s in PROCESSES.values() if s.external]


@pytest.mark.parametrize("spec", STARTABLE, ids=lambda s: s.name)
def test_the_schema_names_every_input_plus_the_two_envelope_fields(spec):
    schema = input_schema(spec)
    assert set(schema["properties"]) == {f.name for f in spec.inputs} | {"requester", "idempotency_key"}
    assert set(schema.get("required", [])) == {f.name for f in spec.inputs if f.required}
    assert schema["additionalProperties"] is False
    assert all(p.get("description") for p in schema["properties"].values()), "a caller reads these"


def test_the_schema_is_self_contained_so_a_connector_can_import_it():
    text = repr([input_schema(s) for s in STARTABLE])
    assert "$ref" not in text and "$defs" not in text


def test_a_choice_reaches_the_schema_as_an_enum():
    choice = next((f for s in STARTABLE for f in s.inputs if f.kind is InputKind.CHOICE), None)
    if choice is None:
        pytest.skip("no CHOICE input registered")
    spec = next(s for s in STARTABLE if choice in s.inputs)
    prop = input_schema(spec)["properties"][choice.name]
    assert set(choice.choices) <= set(repr(prop).replace("'", " ").split()) or "enum" in repr(prop)


def test_submit_parameters_end_with_the_envelope():
    names = [p[0] for p in submit_parameters(STARTABLE[0])]
    assert names[-2:] == ["requester", "idempotency_key"]


def test_annotation_of_still_lets_an_optional_ref_be_null():
    field = next(f for s in PROCESSES.values() for f in s.inputs
                 if not f.required and f.kind is InputKind.REF)
    assert type(None) in getattr(annotation_of(field), "__args__", ())


def _mcp_schemas():
    from lab.substrate.mcp.workflow import server as srv

    async def go():
        async with Client(srv.build().mcp) as c:
            return {t.name: t.inputSchema for t in await c.list_tools()}
    return asyncio.run(go())


@pytest.mark.parametrize("spec", STARTABLE, ids=lambda s: s.name)
def test_the_mcp_tool_and_the_platform_schema_are_the_same_contract(spec):
    mcp = _mcp_schemas()[spec.tool("submit")]
    ours = input_schema(spec)
    assert mcp["properties"] == ours["properties"]
    assert set(mcp.get("required", [])) == set(ours.get("required", []))
