"""Write contracts/semantic-tools.json — the semantic tools' contract an external consumer vendors.

    PYTHONPATH=src .venv/bin/python scripts/render_semantic_contract.py [out.json]

Offline: semantic-mcp is imported with a throwaway file:// store and no tracing, and its tools are
listed in-process — no gateway, database or network. Re-run after any change to a semantic tool, and
bump `lab.substrate.mcp.semantic.contract.VERSION` when the surface changed; the governance test
`tests/governance/test_semantic_contract_is_current.py` fails until the committed file matches.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "contracts", "semantic-tools.json")


def main(argv: list[str]) -> int:
    tmp = tempfile.mkdtemp(prefix="semantic-contract-")
    os.makedirs(os.path.join(tmp, "no-ref-models"))
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    from lab.platform import config
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    config.REFERENCE_MODELS_DIR = os.path.join(tmp, "no-ref-models")
    from lab.substrate.mcp.semantic import contract, server
    out = argv[0] if argv else OUT
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = contract.render(server.server.mcp)
    with open(out, "w", encoding="utf-8") as f:
        f.write(contract.dumps(doc))
    print(f"wrote {out}: {len(doc['tools'])} tools, contract {doc['contract_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
