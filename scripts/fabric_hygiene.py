"""One-off fabric hygiene (Part 2, WP12/WP13) — through the gateway, as an operator.

WP12: a review card whose record is a WORKING FILE (a recording, a transcript or per-lane segment file, a
person's submission record) is declined and the record withdrawn: BRS principle 8, only managed artifacts enter
the lifecycle. WP13: of two records for the same product of the same context (a re-run before versioning), the
earlier is withdrawn and its card declined.

Dry-run by default — prints what it WOULD do. `--apply` acts, recording every decline under `--actor`.

  set -a && source .env && set +a
  .venv/bin/python scripts/fabric_hygiene.py --actor you@tenant [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.platform import mcp_client                                              # noqa: E402
from lab.platform.contracts import PROCESSES, ApprovalTools, SemanticTools      # noqa: E402

WORKING_FILE = "not a managed artifact — a working file stays a pointer (WP12)"
SUPERSEDED = "superseded by a later run of the same product (WP13)"


def is_working_file(row: dict) -> bool:
    """PURE: the rule. A lab record whose pointer is not one of its producer's declared products."""
    pointer = row.get("pointer") or {}
    if pointer.get("source") != "lab":
        return False
    process = row.get("produced_by") or ""
    spec = PROCESSES.get(process)
    if spec is None or not spec.products:
        return True                                    # a non-producer's output (recording, transcript)
    ref = str(pointer.get("ref") or "")
    if process == "transcript_to_minutes":
        return not ref.endswith("minutes.json")
    if process == "use_case_screening":
        return not (row.get("title") or "").startswith("screening")
    return False


def superseded(rows: list[dict]) -> list[dict]:
    """PURE: for lab records sharing (produced_by, title) — two runs of one product before WP13 gave products
    an identity — keep the LATEST; the rest are superseded."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if (r.get("pointer") or {}).get("source") == "lab":
            groups.setdefault((r.get("produced_by"), r.get("title")), []).append(r)
    out = []
    for members in groups.values():
        members.sort(key=lambda r: r.get("created_at") or "")
        out.extend(members[:-1])
    return out


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--actor", required=True); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    url = os.environ["PUBLIC_GATEWAY_URL"].rstrip("/") + "/mcp/"
    # the fabric's own identities, never the admin plane: the bot reads and decides approvals, the curator
    # moves a record's lifecycle — exactly the grants a person's channel and the runner hold
    keys = {ApprovalTools.SERVER: os.environ["FABRIC_BOT_KEY"], SemanticTools.SERVER: os.environ["FABRIC_CURATOR_KEY"]}

    async def call(name, **args):
        server = ApprovalTools.SERVER if name.startswith("approvals_") else SemanticTools.SERVER
        h = {"Authorization": f"Bearer {keys[server]}"}
        return (await mcp_client.call_tools(h, url, [(name, args)]))[0]

    listing = await call(ApprovalTools.list)
    cards = [c for c in listing["approvals"] if c.get("kind") == "draft-review"]
    # `approvals_get` keeps a card's continuation private (an operator must not learn what a decision releases),
    # so the record behind a card is found the way a person finds it: by the title the subject names, among the
    # records still pending — read from the catalog the operator already reaches.
    import psycopg
    dsn = os.environ.get("FABRIC_DB_URL") or os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as db:
        pending = [dict(zip(("iri", "title", "pointer", "produced_by", "context", "created_at"), r))
                   for r in db.execute("select iri, title, pointer, produced_by, context, created_at::text "
                                       "from fabric_artifact where state = 'pending' order by created_at")]
    rows_by_card: dict[str, dict] = {}
    for c in sorted(cards, key=lambda c: c.get("created_at") or ""):
        title = str(c.get("subject") or "").split(" — ", 1)[0]
        match = next((r for r in pending if r["title"] == title and r["iri"] not in {v["iri"] for v in rows_by_card.values()}), None)
        if match:
            rows_by_card[c["request_id"]] = match
    noise = {rid: row for rid, row in rows_by_card.items() if is_working_file(row)}
    older = {r["iri"] for r in superseded([r for rid, r in rows_by_card.items() if rid not in noise])}
    dupes = {rid: row for rid, row in rows_by_card.items() if rid not in noise and row["iri"] in older}
    print(f"open draft-review cards: {len(cards)}  working files: {len(noise)}  superseded: {len(dupes)}  "
          f"kept: {len(cards) - len(noise) - len(dupes)}")
    for label, group, why in (("WP12", noise, WORKING_FILE), ("WP13", dupes, SUPERSEDED)):
        for rid, row in group.items():
            print(f"  [{label}] {'DECLINE' if a.apply else 'would decline'} {rid}  {row['title'][:60]!r}  ({row.get('produced_by')})")
            if a.apply:
                await call(ApprovalTools.decide, request_id=rid, decision="decline", actor=a.actor, channel="cli", comment=why)
                await call(SemanticTools.catalog_state, iri=row["iri"], state="withdrawn")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
