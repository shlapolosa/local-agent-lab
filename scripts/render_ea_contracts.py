"""Write the modelling contracts a channel vendors (FR-11): the engine spec schema, the EA port's tools,
and the golden layout fixtures.

    PYTHONPATH=src .venv/bin/python scripts/render_ea_contracts.py

  contracts/archimate-spec.schema.json   lab.core.archimate.spec_schema (generated from the engine)
  contracts/ea-tools.json                adoit-mcp's tool listing (lab.substrate.mcp.adoit.contract), with result schemas
  contracts/ea-approval.schema.json      the ea-import approval payload (lab.platform.ea_contract)
  contracts/goldens/out/<spec>/          lab.core.archimate.goldens.render for each contracts/goldens/specs/*.json

Offline: adoit-mcp is imported with a throwaway file:// store and no tracing. Re-run after any change
to the engine, the spec shape or an EA tool, and bump the matching VERSION (spec_schema.VERSION covers the
schema and the goldens; adoit.contract.VERSION covers ea-tools.json). Governance tests fail until the
committed files match.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
GOLDENS = os.path.join(CONTRACTS, "goldens")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def render_goldens() -> int:
    from lab.core.archimate import goldens
    out_root = os.path.join(GOLDENS, "out")
    shutil.rmtree(out_root, ignore_errors=True)            # a spec removed must take its goldens with it
    n = 0
    for name in sorted(os.listdir(os.path.join(GOLDENS, "specs"))):
        if not name.endswith(".json"):
            continue
        spec = json.load(open(os.path.join(GOLDENS, "specs", name), encoding="utf-8"))
        for fname, text in goldens.render(spec).items():
            write(os.path.join(out_root, name[:-5], fname), text)
        n += 1
    return n


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ea-contract-")
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    from lab.platform import config
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    from lab.core.archimate import spec_schema
    from lab.substrate.mcp.adoit import contract, server
    write(os.path.join(CONTRACTS, "archimate-spec.schema.json"), spec_schema.dumps(spec_schema.schema()))
    doc = contract.render(server.server.mcp)
    write(os.path.join(CONTRACTS, "ea-tools.json"), contract.dumps(doc))
    write(os.path.join(CONTRACTS, "ea-approval.schema.json"), contract.dumps(contract.approval()))
    n = render_goldens()
    print(f"wrote archimate-spec.schema.json {spec_schema.VERSION}, ea-tools.json {doc['contract_version']} "
          f"({len(doc['tools'])} tools), goldens for {n} spec(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
