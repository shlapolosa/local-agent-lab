"""The governed corpus as a workload's tests see it — fake `reference_*` tools serving the seed.

Serves what the CORPUS serves, not what the seed holds: every seed JSON is rendered to the same
(section, headers, rows) tables the masters are generated from, each cell ENCODED as the master
would carry it, and each artifact is named as `scripts/publish_usecase_corpus.py` names it. So a
workload reading `component-prices` under a fake pin sees exactly the strings `cells.rows` decodes
on a real run — a fixture that handed over the raw JSON would let a test pass on a shape the
corpus never returns (the last such gap sent a nested `variant` to `compose` as a string).
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path

from lab.core.reference import cells
from lab.core.reference.model import ArtifactKind

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "src" / "lab" / "core" / "usecase" / "seed"
VERSION = "v0.27"


@lru_cache(maxsize=1)
def _generator():
    spec = importlib.util.spec_from_file_location("extract_cafe_seed", ROOT / "scripts" / "extract_cafe_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def corpus() -> dict[str, list[dict]]:
    """artifact_id -> rows (cells encoded), for every seed table, named as the publisher names it."""
    out: dict[str, list[dict]] = {}
    for path in sorted(SEED.glob("*.json")):
        payload = json.loads(path.read_text())
        for index, (section, headers, rows) in enumerate(_generator()._tabular(payload)):
            stem = path.stem if index == 0 else f"{path.stem}_{section}"
            out[stem.replace("_", "-")] = [
                {h: cells.encode(c) for h, c in zip(headers, row)} for row in rows]
    return out


def record_type_of(artifact_id: str) -> str:
    """As the publish script declares it, so a lookup by the wrong type misses here too."""
    spec = importlib.util.spec_from_file_location("publish_usecase_corpus", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ARTIFACTS[artifact_id][0]


def tools(artifacts=(), *, version: str = VERSION, retrieval: dict | None = None) -> dict:
    """The fake gateway tools: `reference_pin` freezes what it is asked (or everything served),
    `reference_lookup` answers by artifact, type and key containment. Records are recorded on the
    returned `calls` the same way the Router records them."""
    served = corpus()
    modes = dict(retrieval or {})

    def pin(args):
        ids = list(args.get("artifact_ids") or served)
        return {"pin_id": "pin-test", "ring": 0, "pinned_at": "t", "expires_at": "t",
                "versions": [{"artifact_id": a, "version": version, "signature_id": "k1",
                              "retrieval": modes.get(a, "key")} for a in ids]}

    def lookup(args):
        rows = served.get(args.get("artifact_id") or "", [])
        key = args.get("key") or {}
        hit = [r for r in rows if all(str(r.get(k, "")) == str(v) for k, v in key.items())]
        limit = None if modes.get(args.get("artifact_id")) == "whole" else int(args.get("limit") or 20)
        hit = hit[:limit] if limit else hit
        return {"records": [{"record_id": f"rec-{i}", "key": {k: r.get(k) for k in key},
                             "body": r, "artifact_id": args.get("artifact_id"), "version": version}
                            for i, r in enumerate(hit)],
                "citations": [], "matched": len(hit), "near": []}

    return {"reference_pin": pin, "reference_lookup": lookup}


def seeded(artifact_id: str, **over):
    """A `SeededArtifact` for the in-memory library, from the same rows."""
    from fixtures.reference import SeededArtifact
    rows = [{"record_id": f"rec-{i}", **r} for i, r in enumerate(corpus()[artifact_id])]
    return SeededArtifact(artifact_id=artifact_id, kind=ArtifactKind.RECORD, title=artifact_id,
                          record_type=record_type_of(artifact_id), version=VERSION, records=rows,
                          **over)
