"""The committed semantic-tools contract IS what the server registers — exactly, both directions.

`contracts/semantic-tools.json` is what an external consumer (the SAF pack) vendors verbatim and diffs
on every re-vendor. Exactness is the contract here: a tool, a schema, a grant or a stability that
changed in the code but not in the file means a consumer is binding to a surface that no longer
exists. So the file is regenerated in-process and compared byte for byte; on a difference the message
says to bump the version (when the surface changed) and re-render.

Offline: the server is imported with the environment pinned (a temp file:// store, no OTLP).
"""
import importlib
import os
import tempfile

import pytest

from lab.platform import config

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMITTED = os.path.join(ROOT, "contracts", "semantic-tools.json")


@pytest.fixture(scope="module")
def server(request):
    tmp = tempfile.mkdtemp(prefix="semantic-contract-")
    os.makedirs(os.path.join(tmp, "no-ref-models"))
    saved_env = {k: os.environ.get(k) for k in ("OTEL_EXPORTER_OTLP_ENDPOINT",)}
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    saved = {k: getattr(config, k) for k in ("ARTIFACTS_URL", "UPLOADS_URL", "REFERENCE_MODELS_DIR")}
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    config.REFERENCE_MODELS_DIR = os.path.join(tmp, "no-ref-models")
    yield importlib.import_module("lab.substrate.mcp.semantic.server").server.mcp
    for k, v in saved.items():
        setattr(config, k, v)
    for k, v in saved_env.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_the_committed_contract_equals_what_the_server_registers(server):
    from lab.substrate.mcp.semantic import contract
    fresh = contract.dumps(contract.render(server))
    assert os.path.exists(COMMITTED), "contracts/semantic-tools.json is missing — run scripts/render_semantic_contract.py"
    committed = open(COMMITTED, encoding="utf-8").read()
    if fresh != committed:
        import json
        old, new = json.loads(committed), json.loads(fresh)
        same_version = old.get("contract_version") == new.get("contract_version")
        changed = sorted({t["name"] for t in old["tools"]} ^ {t["name"] for t in new["tools"]}) or \
            sorted(a["name"] for a, b in zip(old["tools"], new["tools"]) if a != b)
        hint = (" The tool surface changed but contract_version did not: bump "
                "lab.substrate.mcp.semantic.contract.VERSION (major for a removed/renamed stable tool or "
                "a breaking schema change, minor for an addition), then" if same_version else " Then")
        pytest.fail(f"contracts/semantic-tools.json is stale (changed: {changed[:8]}).{hint} re-render with "
                    "`PYTHONPATH=src .venv/bin/python scripts/render_semantic_contract.py` and commit it.")
