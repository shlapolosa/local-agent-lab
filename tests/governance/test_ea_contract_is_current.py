"""The committed modelling contracts ARE what the code produces — exactly, both directions (FR-11).

`contracts/ea-tools.json` (the EA port's tools) and `contracts/archimate-spec.schema.json` (the engine's
interchange) are what a channel vendors verbatim and diffs on every re-vendor. Exactness is the contract:
a tool, schema or enum that moved in the code but not in the file means a consumer binds to a surface that
no longer exists. On a difference the message says what to bump and how to re-render.

Offline: adoit-mcp is imported with a throwaway file:// store and no tracing.
"""
import importlib
import json
import os
import tempfile

import pytest

from lab.platform import config
from lab.platform.contracts import EATools

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "contracts", "ea-tools.json")
SCHEMA = os.path.join(ROOT, "contracts", "archimate-spec.schema.json")
RENDER = "`PYTHONPATH=src .venv/bin/python scripts/render_ea_contracts.py`"


@pytest.fixture(scope="module")
def server():
    tmp = tempfile.mkdtemp(prefix="ea-contract-")
    saved_env = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    saved = {k: getattr(config, k) for k in ("ARTIFACTS_URL", "UPLOADS_URL")}
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    yield importlib.import_module("lab.substrate.mcp.adoit.server").server.mcp
    for k, v in saved.items():
        setattr(config, k, v)
    if saved_env is not None:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = saved_env


def test_the_committed_ea_tools_contract_equals_what_the_server_registers(server):
    from lab.substrate.mcp.adoit import contract
    fresh = contract.dumps(contract.render(server))
    committed = open(TOOLS, encoding="utf-8").read()
    if fresh != committed:
        old, new = json.loads(committed), json.loads(fresh)
        bump = (" The tool surface changed but contract_version did not: bump "
                "lab.substrate.mcp.adoit.contract.VERSION (major for a removed/renamed stable tool or a "
                "breaking schema change, minor for an addition), then" if
                old.get("contract_version") == new.get("contract_version") else " Then")
        pytest.fail(f"contracts/ea-tools.json is stale.{bump} re-render with {RENDER} and commit it.")


def test_the_committed_approval_schema_equals_the_typed_payload():
    from lab.substrate.mcp.adoit import contract
    path = os.path.join(ROOT, "contracts", "ea-approval.schema.json")
    if contract.dumps(contract.approval()) != open(path, encoding="utf-8").read():
        pytest.fail("contracts/ea-approval.schema.json is stale — the ea-import payload moved "
                    "(lab.platform.ea_contract). Bump lab.substrate.mcp.adoit.contract.VERSION, re-render "
                    f"with {RENDER}, and notify channels that show EA approvals.")


def test_every_visualisation_tool_publishes_its_result_schema():
    doc = json.load(open(TOOLS, encoding="utf-8"))
    with_results = {t["name"] for t in doc["tools"] if "resultSchema" in t}
    assert {EATools.render, EATools.stage_import, EATools.import_status} <= with_results


def test_every_port_tool_has_a_stability_tier():
    tiers = EATools.stability()
    assert set(tiers) == EATools.names() and set(tiers.values()) <= {"stable", "in-flux", "internal"}


def test_the_committed_spec_schema_equals_the_engine_s():
    from lab.core.archimate import spec_schema
    fresh = spec_schema.dumps(spec_schema.schema())
    if fresh != open(SCHEMA, encoding="utf-8").read():
        pytest.fail("contracts/archimate-spec.schema.json is stale — the engine's types or the spec shape "
                    "moved. Bump lab.core.archimate.spec_schema.VERSION if the shape changed, re-render "
                    f"with {RENDER}, and notify channels porting the engine.")
