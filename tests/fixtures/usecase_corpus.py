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
from functools import lru_cache
from pathlib import Path

from lab.core.usecase import seed
from lab.core.reference.model import ArtifactKind

ROOT = Path(__file__).resolve().parents[2]
VERSION = "v0.27"


@lru_cache(maxsize=1)
def corpus() -> dict[str, list[dict]]:
    """artifact_id -> rows, for every committed MASTER, named as the publisher names it.

    The masters ARE what is published — the publisher derives records from exactly these tables —
    so their cells are already encoded the way the corpus serves them. This read the seed JSON
    until the CAFÉ workbook (28 Sep 2026) replaced it as the corpus's source; after that the JSON
    was an HTML-era fixture, and a workload test served from it would pass against a corpus that
    no longer exists. The PRIVATE masters are not in this repository, so they are not served here:
    a test that needs one supplies its own rows."""
    return {path.stem.replace("_", "-"): seed.master_rows(path.stem)
            for path in sorted(seed.MASTERS_DIR.glob("*.md"))}


def record_type_of(artifact_id: str) -> str:
    """As the publish script declares it, so a lookup by the wrong type misses here too."""
    spec = importlib.util.spec_from_file_location("publish_usecase_corpus", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ARTIFACTS[artifact_id][0]


def tools(artifacts=(), *, version: str = VERSION, retrieval: dict | None = None,
          extra: dict | None = None) -> dict:
    """The fake gateway tools: `reference_pin` freezes what it is asked (or everything served),
    `reference_lookup` answers by artifact, type and key containment. Records are recorded on the
    returned `calls` the same way the Router records them.

    `extra` serves artifacts this repository does not carry — the PRIVATE masters — as
    `{artifact_id: rows}`, for a test that needs one (their real content is not public)."""
    served = {**corpus(), **dict(extra or {})}
    modes = dict(retrieval or {})

    def pin(args):
        # `or served` would be wrong: an EMPTY list means "pin nothing", which is not the same as
        # the key being absent ("pin everything served"). A real gateway distinguishes them, and
        # conflating them made a run that pins no artifact look like one that pinned all 36.
        asked = args.get("artifact_ids")
        ids = list(served if asked is None else asked)
        # As the SERVER does (`pg_library.pin`): an artifact with no published release fails the
        # WHOLE pin. This double used to freeze whatever it was asked for, so a run pinning a
        # private master nobody had uploaded passed here and died at the pin in the cloud —
        # every "optional corpus" test asserted behaviour production could not reach.
        unpublished = [a for a in ids if a not in served]
        if unpublished:
            raise RuntimeError(f"reference unavailable: {unpublished[0]} has no release on ring 0")
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

    def catalogue(args):
        return {"ring": 0, "artifacts": [
            {"artifact_id": a, "version": version, "retrieval": modes.get(a, "key"),
             "record_type": record_type_of(a) if a in _declared() else "", "kind": "record",
             "title": a, "owner": ""} for a in served]}

    return {"reference_pin": pin, "reference_lookup": lookup, "reference_catalogue": catalogue}


@lru_cache(maxsize=1)
def _declared() -> set[str]:
    spec = importlib.util.spec_from_file_location("publish_usecase_corpus_d",
                                                  ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.ARTIFACTS)


def seeded(artifact_id: str, **over):
    """A `SeededArtifact` for the in-memory library, from the same rows."""
    from fixtures.reference import SeededArtifact
    rows = [{"record_id": f"rec-{i}", **r} for i, r in enumerate(corpus()[artifact_id])]
    return SeededArtifact(artifact_id=artifact_id, kind=ArtifactKind.RECORD, title=artifact_id,
                          record_type=record_type_of(artifact_id), version=VERSION, records=rows,
                          **over)
