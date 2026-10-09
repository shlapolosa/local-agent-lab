"""Re-read catalogued artifacts with better evidence — through the gateway, as an operator.

The catalogue measured 7 Oct 2026 held ~90 records classified from their FILE NAMES alone: the classifier
was shown a title, a path and 123 concepts and asked what a document is about, which put `Clinical document`
on 39 of 93 records and filed a meeting about a note-taking app under `Teleconsultation`. Since 6 Oct the
classifier reads a bounded excerpt of the document itself, but only NEW and CHANGED artifacts benefit: the
ingress submits on a CHANGE, and these pointers have not moved. This walks them back through intake.

Three things make it safe to run over the whole estate:

  * `vocab_link` REPLACES a record's extracted subjects (it used to only add), so a second pass can take a
    wrong subject back instead of leaving a union of both readings. Without that this script would make the
    catalogue worse, which is why it did not exist before.
  * intake is submitted with `reason=reclassify`, so it re-links and asks NOBODY — no second approval card
    for records whose first one is still open. A record that GAINS a type still asks.
  * it submits through `semantic_catalog_reclassify`, naming a record and supplying NOTHING else. Intake
    has no `_submit` tool by design (`external=False`: the ArtifactChanged event IS the provenance of a
    normal run), so the fabric reads the pointer, producer and context off the row it recorded itself —
    the same opening `workflow_replay` uses for a continuation-only process.

Dry-run by default — prints what it WOULD submit. `--apply` submits.

  set -a && source .env && set +a
  .venv/bin/python scripts/fabric_reclassify.py --state pending [--limit 20] [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.platform import mcp_client                                          # noqa: E402
from lab.platform.contracts import SemanticTools                             # noqa: E402

#: Seconds between submissions. Ollama Cloud's session limit is one bucket for the whole ACCOUNT, so a
#: burst of ninety classifications would starve anything else running — a live meeting, an eval, a
#: screening. Slow is free here: nothing is waiting on this.
PACE_S = 3.0


def plan(rows: list[dict]) -> list[dict]:
    """PURE: the records worth re-reading, and the pointer each one is submitted under.

    A record is skipped when its pointer cannot be resubmitted — the run is provenance, and intake reads
    the artifact THROUGH its pointer, so one without a source is not a thing that can be re-read.
    """
    out = []
    for r in rows:
        p = r.get("pointer") or {}
        if not p.get("source") or not (p.get("ref") or p.get("handle")):
            continue
        out.append({"iri": r["iri"], "title": r.get("title") or "", "pointer": p,
                    "produced_by": r.get("produced_by") or "", "context": r.get("context") or ""})
    return out


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--state", default="pending", help="lifecycle state to walk (default: pending)")
    ap.add_argument("--limit", type=int, default=200, help="stop after this many records")
    ap.add_argument("--pace", type=float, default=PACE_S, help=f"seconds between submits (default {PACE_S})")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    url = os.environ["PUBLIC_GATEWAY_URL"].rstrip("/") + "/mcp/"
    headers = {"Authorization": f'Bearer {os.environ["FABRIC_CURATOR_KEY"]}'}

    async def call(name, **args):
        return (await mcp_client.call_tools(headers, url, [(name, args)]))[0]

    rows, cursor = [], ""
    while len(rows) < a.limit:
        page = await call(SemanticTools.catalog_list, after=cursor, limit=min(100, a.limit - len(rows)),
                          state=a.state)
        items = page.get("items") or []
        if not items:
            break
        rows += items
        cursor = page.get("cursor") or ""
        if not page.get("more"):
            break

    work = plan(rows)[:a.limit]
    print(f"{a.state} records walked: {len(rows)}  re-readable: {len(work)}  "
          f"skipped (no usable pointer): {len(rows) - len(work)}")
    round_id = time.strftime("%Y%m%dT%H%M%S")
    started, failed = 0, 0
    for i, w in enumerate(work, 1):
        if not a.apply:
            print(f"  [{i}/{len(work)}] would re-read {w['title'][:64]!r}")
            continue
        try:
            got = await call(SemanticTools.catalog_reclassify, iri=w["iri"])
            started += 1
            print(f"  [{i}/{len(work)}] {got.get('request_id', '?')}  {w['title'][:56]!r}")
        except Exception as e:                      # noqa: BLE001 — one record must not stop the pass
            failed += 1
            print(f"  [{i}/{len(work)}] FAILED {w['title'][:48]!r}: {type(e).__name__}: {e}")
        await asyncio.sleep(max(0.0, a.pace))
    if a.apply:
        print(f"submitted: {started}  failed: {failed}  round: {round_id}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
