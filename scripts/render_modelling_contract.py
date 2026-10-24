"""Write contracts/modelling.json and the paragraph goldens a channel vendors (ADR 2026-10-24, D9).

    PYTHONPATH=src .venv/bin/python scripts/render_modelling_contract.py

  contracts/modelling.json                        lab.core.modelling.contract (pure, offline)
  contracts/goldens/paragraphs/<name>/extracted.txt   docparse.document_text of <name>/source.*
  contracts/goldens/paragraphs/<name>/paragraphs.json paragraphs.split of that text, by media type

Bump lab.core.modelling.envelope.CONTRACT_VERSION when the shape changes, and tell the channels that
vendor it. tests/governance/test_modelling_contract.py fails until the committed files match.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lab.core.modelling import contract, paragraphs  # noqa: E402
from lab.platform import docparse, filetypes  # noqa: E402

GOLDENS = os.path.join(ROOT, "contracts", "goldens", "paragraphs")


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def golden(source: str) -> tuple[str, str]:
    """(extracted text, paragraphs.json) for one golden source file."""
    with open(source, "rb") as f:
        text = docparse.document_text(f.read(), docparse.ext_of(source))
    split = paragraphs.split(text, filetypes.content_type_for(source))
    return text, json.dumps(split, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    doc = contract.schema()
    write(os.path.join(ROOT, "contracts", "modelling.json"), contract.dumps(doc))
    sources = sorted(glob.glob(os.path.join(GOLDENS, "*", "source.*")))
    for source in sources:
        text, split = golden(source)
        write(os.path.join(os.path.dirname(source), "extracted.txt"), text)
        write(os.path.join(os.path.dirname(source), "paragraphs.json"), split)
    print(f"wrote contracts/modelling.json {doc['version']} and {len(sources)} paragraph golden(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
