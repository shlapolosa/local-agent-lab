"""Write contracts/modelling.json, the modelling envelope a channel vendors (ADR 2026-10-24, D9).

    PYTHONPATH=src .venv/bin/python scripts/render_modelling_contract.py

Generated from lab.core.modelling (pure, offline: no server to boot, unlike render_ea_contracts.py).
Bump lab.core.modelling.envelope.CONTRACT_VERSION when the shape changes, and tell the channels that
vendor it. tests/governance/test_modelling_contract.py fails until the committed file matches.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lab.core.modelling import contract  # noqa: E402


def main() -> int:
    path = os.path.join(ROOT, "contracts", "modelling.json")
    doc = contract.schema()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(contract.dumps(doc))
    print(f"wrote contracts/modelling.json {doc['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
