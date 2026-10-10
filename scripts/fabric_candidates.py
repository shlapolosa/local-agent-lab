"""One-off cleanup of the steward's CANDIDATE backlog — through the gateway, as an operator.

The sibling of `scripts/fabric_hygiene.py`, which cleans the ARTIFACT backlog: same shape, same two fabric
identities, dry-run by default, `--apply` acts and every decline is recorded under `--actor`.

Measured 10 Oct 2026, the backlog this was written for. The steward path had been raising nothing for weeks
(`approvals_ask` was being handed `payload=` where it takes `context=`); the moment it worked it produced
**71 open `concept-admission` cards for 44 distinct labels**, of which **25 cards across 7 labels name a term
the vocabulary ALREADY HOLDS as a DOCUMENT TYPE** — `Decision record` x12, `Meeting minutes` x6,
`Architecture model` x2, `Solution design` x2, `Architecture decision record`, `Decision Record`,
`Requirements`. The classifier had confused what a document IS with what it is ABOUT. The rest are one card
per PROPOSAL where one card per TERM was wanted: a steward answering the first settles the term for all.

So two verdicts are declined and one is left for a person — `classify`, the pure rule, tested in
`tests/unit/substrate/test_fabric_candidates_rule.py`.

WHAT THIS DOES NOT DO: it does not retire the candidates, because no tool can. See `CANNOT_RETIRE`.

  set -a && source .env && set +a
  .venv/bin/python scripts/fabric_candidates.py --actor you@tenant [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.core.semantic.fabric.ontology import DocumentTypes          # noqa: E402
from lab.platform import mcp_client                                  # noqa: E402
from lab.platform.contracts import ApprovalKind, ApprovalTools, SemanticTools   # noqa: E402

HELD, DUPLICATE, KEEP = "held", "duplicate", "keep"

#: `fabric_vocabulary.ask_open` writes the candidate's subject as `f'{label!r} has no concept — …'`, and
#: `approvals_get` deliberately withholds the card's `context` (an operator must not learn what a decision
#: releases), so the subject is the ONLY place the term is readable from. Anchored on "has no concept" rather
#: than on the quotes alone: the same `concept-admission` kind also carries the CONFLICT question ("…means
#: more than one thing"), which this cleanup must never touch — a conflict is settled by naming the meaning
#: to keep, and it quotes a term that is held by definition.
_SUBJECT = re.compile(r"""^(['"])(?P<label>.+?)\1\s+has no concept""")

#: Why the candidates themselves are left open. `SemanticTools.vocab_retire` supersedes a concept a scheme
#: ALREADY HOLDS: `Scheme.retire` refuses both a `cid` and a `resolves_to` the scheme does not hold, and a
#: candidate lives in the candidates graph with no scheme membership at all — so there is no id to retire and
#: nothing to resolve it to. `vocab_amend` cannot close these either: it teaches a concept OF THE CANDIDATE'S
#: OWN SCHEME another name, and the 7 held labels are held by `doc-types`, a different vocabulary. The gate's
#: own `decline` answer (`fabric_vocabulary.plan`) returns NO calls by design — "recorded on the approval; the
#: vocabulary is untouched" — which is exactly what this script does.
#: That is not a gap this script may paper over: openness is DERIVED (`FabricService.vocab_candidates` drops a
#: candidate whose label the scheme now finds), so the one honest fix is in that derivation, not here.
CANNOT_RETIRE = ("the candidates stay open: vocab_retire supersedes a concept a SCHEME HOLDS, and a candidate "
                 "has no scheme membership — closing them belongs in vocab_candidates' own derivation")

_HELD_WHY = ("the vocabulary already holds this term in {holder} — a document's TYPE is not what the document "
             "is ABOUT, so there is no subject concept to admit")
_DUPE_WHY = ("the same term is already open as {first} — one card per term, not one per proposal; answering "
             "that one settles this")


def normalise(label: str | None) -> str:
    """PURE: the one matching rule — casefold, trim, collapse internal whitespace.

    Internal whitespace is what separates this from the vocabulary's own lookup: `Scheme.find` casefolds and
    strips, so it would already have matched `Decision Record`, but not `Decision  record`. A term the
    vocabulary holds can therefore still be sitting in the candidates, which is half of why this backlog
    exists. In one place because every surface's matching depends on agreeing about it."""
    return " ".join(str(label or "").split()).casefold()


def label_of_card(subject: str | None) -> str:
    """PURE: the term a candidate card asks about, from its subject — `""` for anything else (a conflict
    card, or a subject this rule cannot read), which `classify` then KEEPS."""
    m = _SUBJECT.match(str(subject or "").strip())
    return m.group("label") if m else ""


def classify(rows: Sequence[Mapping], held: Mapping[str, str]) -> list[dict]:
    """PURE: one verdict per row, in order. `held` maps a label to the vocabulary that holds it.

    HELD beats DUPLICATE deliberately: for a held term there is nothing for a steward to admit, so keeping
    its first card would read as "a person still has to answer this". A row with no label is KEPT — silence
    is the safe answer, and the alternative is declining somebody's question because a regex changed."""
    held_n = {normalise(k): v for k, v in held.items()}
    seen: dict[str, str] = {}
    out = []
    for row in rows:
        label = str(row.get("label") or "")
        n = normalise(label)
        if not n:
            verdict, why = KEEP, "no term could be read from this card — a person decides"
        elif n in held_n:
            verdict, why = HELD, _HELD_WHY.format(holder=held_n[n])
        elif n in seen:
            verdict, why = DUPLICATE, _DUPE_WHY.format(first=seen[n])
        else:
            verdict, why = KEEP, "a term the vocabulary has no concept for — a steward decides"
        seen.setdefault(n, f"{label!r} ({row.get('request_id') or '?'})")
        out.append({**row, "verdict": verdict, "reason": why})
    return out


def document_type_labels() -> dict[str, str]:
    """Every name `doc-types` answers to, mapped to how a decline comment should describe its holder. Read
    from the bundled scheme, not through the gateway: it is a git artifact, and `semantic_concepts` would not
    return the ALT labels anyway — `Requirements` and `Architecture decision record` are alts, and they are
    two of the seven labels in this backlog."""
    out: dict[str, str] = {}
    for t in DocumentTypes().types().values():
        out[t["label"]] = "doc-types"
        for alt in t["alt"]:
            out[alt] = f"doc-types (another name for {t['label']!r})"
    return out


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--actor", required=True); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    url = os.environ["PUBLIC_GATEWAY_URL"].rstrip("/") + "/mcp/"
    # the fabric's own identities, never the admin plane: the bot reads and decides approvals, the curator
    # reads the vocabulary — exactly the grants a person's channel and the runner hold
    keys = {ApprovalTools.SERVER: os.environ["FABRIC_BOT_KEY"],
            SemanticTools.SERVER: os.environ["FABRIC_CURATOR_KEY"]}

    async def call(name, **args):
        server = ApprovalTools.SERVER if name.startswith("approvals_") else SemanticTools.SERVER
        h = {"Authorization": f"Bearer {keys[server]}"}
        return (await mcp_client.call_tools(h, url, [(name, args)]))[0]

    candidates = await call(SemanticTools.vocab_candidates) or []
    held = document_type_labels()
    # ...and the schemes the OPEN candidates name, as a cross-check. They should hold none of these labels —
    # `vocab_candidates` already drops a candidate its own scheme can find — so a hit here means the two
    # lookups disagree, which is worth seeing rather than assuming away.
    for scheme in sorted({str(c.get("scheme") or "") for c in candidates} - {""}):
        for row in await call(SemanticTools.concepts, scheme=scheme, kind="") or []:
            held.setdefault(str(row.get("label") or ""), scheme)

    listing = await call(ApprovalTools.list, kind=ApprovalKind.CONCEPT_ADMISSION.value, limit=200)
    cards = [c for c in (listing.get("approvals") or []) if c.get("open")]
    if (listing.get("open_total") or 0) > len(listing.get("approvals") or []):
        print(f"! {listing['open_total']} open approvals in all — this read {len(listing['approvals'])}; "
              "run again after applying")
    # oldest first, because DUPLICATE means "a later card for a term already asked about"
    rows = sorted(({**c, "label": label_of_card(c.get("subject"))} for c in cards),
                  key=lambda c: c.get("created_at") or "")
    verdicts = classify(rows, held)
    counts = {v: sum(1 for r in verdicts if r["verdict"] == v) for v in (HELD, DUPLICATE, KEEP)}
    labels = {normalise(r["label"]) for r in verdicts if r["label"]}
    print(f"open concept-admission cards: {len(cards)}  distinct terms: {len(labels)}  "
          f"candidates open: {len(candidates)}")
    print(f"  held: {counts[HELD]}  duplicate: {counts[DUPLICATE]}  keep: {counts[KEEP]}")
    for r in verdicts:
        if r["verdict"] == KEEP:
            continue
        print(f"  [{r['verdict']}] {'DECLINE' if a.apply else 'would decline'} {r['request_id']}  "
              f"{r['label']!r}  — {r['reason']}")
        if a.apply:
            await call(ApprovalTools.decide, request_id=r["request_id"], decision="decline",
                       actor=a.actor, channel="cli", comment=r["reason"])
    print(f"! {CANNOT_RETIRE}")
    stuck = [c for c in classify([{**c, "request_id": c.get("iri")} for c in candidates], held)
             if c["verdict"] != KEEP]
    for c in stuck[:10]:
        print(f"    still open: {c.get('iri')}  {c.get('label')!r}  [{c['verdict']}]")
    if len(stuck) > 10:
        print(f"    ... and {len(stuck) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
