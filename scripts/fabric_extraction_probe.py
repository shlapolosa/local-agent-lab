"""Phase 0 of the classifier inversion: measure before building. READ-ONLY, no production change.

The inversion proposes that a model read an artifact and emit [{term, evidence_span, salience}], after
which a deterministic lane grounds the span, normalises the term and matches it in two tiers — lexical
first (`DomainScheme.find`), then semantic against concept DEFINITIONS. Three of those steps rest on
numbers nobody has: how often a quoted span can be found in the excerpt at all, how often a lexical hit
is a HOMONYM, and whether the semantic tier simply re-creates the hub bias it is meant to cure.

This script produces those numbers and nothing else. It may cancel two of the three tiers.

  (a) excerpt branch per record            — how many records can support grounding at all
  (b) grounding pass rate, three strictnesses — the real cost of the word "verbatim"
  (c) lexical hit rate + the spans behind each hit — a human reads these for homonyms
  (e) argmax distribution + top1-top2 margin  — whether tier 2 piles onto the same hub concepts

(d) definition coverage was measured first and separately: 123/123, median 73 chars.

    set -a && source .env && set +a
    .venv/bin/python scripts/fabric_extraction_probe.py [--limit N] [--out DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.platform import filetypes                                      # noqa: E402
from lab.substrate import fabric_gateway                                # noqa: E402

EXCERPT_CHARS = 2000          # workflow.EXCERPT_CHARS — the probe must cut where the pipeline cuts
PROMPT = """You are reading ONE document. Say what it is ABOUT, in its own words.

Return ONLY a JSON object: {"terms": [{"term": "...", "evidence_span": "...", "salience": 0.0}]}

- `term`: a concept the document is about — a short noun phrase. It need NOT appear verbatim in the text;
  name the idea even when the document never names it.
- `evidence_span`: a SHORT quotation from the text, copied EXACTLY, that evidences the term.
- `salience`: 0..1, how central the term is to this document.
At most 10 terms. No prose outside the JSON.

DOCUMENT:
"""


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def ground(span: str, text: str) -> str:
    """The strictest level at which `span` is present in `text`: verbatim | whitespace | casefold | none."""
    if not span or not text:
        return "none"
    if span in text:
        return "verbatim"
    if _norm_ws(span) in _norm_ws(text):
        return "whitespace"
    if _norm_ws(span).casefold() in _norm_ws(text).casefold():
        return "casefold"
    return "none"


def branch_of(row: dict) -> str:
    """Which arm of `_excerpt` this record would take — decided by pointer and file kind, as it is there."""
    p = row.get("pointer") or {}
    src, title = p.get("source"), (row.get("title") or "")
    if src == "collab":
        return "read_document" if filetypes.kind_for(title) == "document" else "read_artifact"
    if src == "lab":
        return "read_document" if filetypes.kind_for(title) == "document" else "read_artifact(json)"
    return "unknown"


def embed(texts: list[str], purpose: str) -> list[list[float]]:
    """The gateway's own embedder, same model the fabric indexes with."""
    key = os.environ.get("REFERENCE_EMBED_KEY") or os.environ["FABRIC_CURATOR_KEY"]
    prefix = {"document": "search_document: ", "query": "search_query: "}[purpose]
    req = urllib.request.Request(
        os.environ["PUBLIC_GATEWAY_URL"].rstrip("/") + "/v1/embeddings",
        data=json.dumps({"model": os.environ.get("REFERENCE_EMBED_MODEL", "nomic-embed-text"),
                         "input": [prefix + t for t in texts]}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return [d["embedding"] for d in json.load(r)["data"]]


def cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return num / (na * nb) if na and nb else 0.0


def ask(prompt: str) -> dict:
    req = urllib.request.Request(
        os.environ["PUBLIC_GATEWAY_URL"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps({"model": os.environ.get("FABRIC_AGENT_MODEL", "kimi-k3"),
                         "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0, "max_tokens": 3000}).encode(),
        headers={"Authorization": f"Bearer {os.environ['FABRIC_CURATOR_KEY']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.load(r)["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"terms": [], "unparsed": text[:120]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        # A probe REPORTS a malformed answer; it does not die of one. An evidence span is quoted text and
        # will eventually contain a quote mark the model fails to escape — which is itself a finding about
        # asking a model for verbatim spans, so it is counted rather than hidden.
        return {"terms": [], "unparsed": f"{type(e).__name__}: {str(e)[:80]}"}


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--limit", type=int, default=8, help="documents to extract from (default 8)")
    ap.add_argument("--match", default="", help="only documents whose title contains this (case-insensitive)")
    ap.add_argument("--out", default="var/out/extraction-probe")
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- the catalogue
    after, rows = "", []
    while True:
        r = (await fabric_gateway.call([("semantic_catalog_list", {"after": after, "limit": 100})]))[0]
        r = json.loads(r) if isinstance(r, str) else r
        rows += r["items"]
        if not r.get("more"):
            break
        after = r["cursor"]

    # (a) which arm of _excerpt each record would take
    import collections
    branches = collections.Counter(branch_of(x) for x in rows)
    print(f"(a) EXCERPT BRANCH over {len(rows)} records")
    for k, n in branches.most_common():
        print(f"      {n:4}  {k}")

    # (d) the vocabulary, with its definitions
    cs = (await fabric_gateway.call([("semantic_concepts", {"scheme": "cafe", "kind": ""})]))[0]
    cs = json.loads(cs) if isinstance(cs, str) else cs
    concepts = cs if isinstance(cs, list) else (cs.get("concepts") or [])
    defined = [c for c in concepts if (c.get("definition") or "").strip()]
    print(f"\n(d) VOCABULARY  {len(concepts)} concepts · {len(defined)} with a definition")

    # the documents worth extracting from: collab-held documents, read through the provider
    from lab.platform import config
    from lab.substrate.mcp.graph import graph_repository as gr
    gc = gr.app_client(config.GRAPH_WRITER_CLIENT_ID, config.GRAPH_WRITER_CLIENT_SECRET,
                       tenant_id=config.ENTRA_TENANT_ID)
    docs = [x for x in rows if (x.get("pointer") or {}).get("source") == "collab"
            and x.get("state") != "withdrawn"
            and filetypes.kind_for(x.get("title") or "") == "document"
            and a.match.casefold() in (x.get("title") or "").casefold()][:a.limit]
    print(f"\nextracting from {len(docs)} collab documents\n")

    labels = {(c.get("label") or "").strip().casefold(): c for c in concepts}
    ids = {(c.get("id") or "").strip().casefold(): c for c in concepts}
    defs = [f"{c['label']}. {c.get('definition') or ''}".strip() for c in defined]
    dvecs = embed(defs, "document")

    results, unparsed = [], []
    levels, tiers, argmax = collections.Counter(), collections.Counter(), collections.Counter()
    margins = []
    for x in docs:
        handle = (x.get("pointer") or {}).get("handle", "")
        item_id = handle.rsplit("/", 1)[-1]
        drive = handle.split("/item/")[-1].split("/")[0] if "/item/" in handle else ""
        try:
            raw = gc.stream(f"/drives/{drive}/items/{item_id}/content").fileobj.read(8000)
            excerpt = raw.decode("utf-8", "replace")[:EXCERPT_CHARS]
        except Exception as e:                                   # noqa: BLE001 — a probe reports, never fails
            print(f"  {str(x.get('title'))[:44]:46} UNREADABLE {type(e).__name__}")
            continue
        got = ask(PROMPT + excerpt)
        if got.get("unparsed"):
            unparsed.append({"title": x.get("title"), "why": got["unparsed"]})
            print(f"  {str(x.get('title'))[:44]:46} UNPARSED {got['unparsed'][:50]}")
            continue
        terms = got.get("terms") or []
        rec = {"title": x.get("title"), "iri": x["iri"], "terms": []}
        for t in terms:
            term, span = str(t.get("term") or ""), str(t.get("evidence_span") or "")
            lvl = ground(span, excerpt)
            levels[lvl] += 1
            hit = labels.get(term.strip().casefold()) or ids.get(term.strip().casefold())
            tier = "1-lexical" if hit else ("3-none" if lvl == "none" else "2-semantic")
            tiers[tier] += 1
            row = {"term": term, "span": span[:90], "grounded": lvl, "salience": t.get("salience"),
                   "lexical": (hit or {}).get("label", "")}
            if tier == "2-semantic":
                tv = embed([f"{term}. {span}"], "query")[0]
                scored = sorted(((cos(tv, dv), defined[i]) for i, dv in enumerate(dvecs)), reverse=True,
                                key=lambda s: s[0])
                (s1, c1), (s2, _c2) = scored[0], scored[1]
                argmax[c1["label"]] += 1
                margins.append(round(s1 - s2, 4))
                row |= {"nearest": c1["label"], "score": round(s1, 4), "margin": round(s1 - s2, 4)}
            rec["terms"].append(row)
        results.append(rec)
        print(f"  {str(x.get('title'))[:44]:46} {len(terms):2} terms")

    total = sum(levels.values()) or 1
    print(f"\n(b) GROUNDING over {total} terms")
    for k in ("verbatim", "whitespace", "casefold", "none"):
        print(f"      {levels[k]:4}  {levels[k]*100//total:3}%  {k}")
    print(f"\n(c) TIER over {total} terms")
    for k, n in tiers.most_common():
        print(f"      {n:4}  {n*100//total:3}%  {k}")
    print(f"\n(e) SEMANTIC ARGMAX — {len(margins)} terms reached tier 2")
    for lab, n in argmax.most_common(10):
        print(f"      {n:4}  {lab}")
    if margins:
        margins.sort()
        print(f"      margin: min {margins[0]} · median {margins[len(margins)//2]} · max {margins[-1]}")
    (out / "probe.json").write_text(json.dumps(
        {"branches": dict(branches), "levels": dict(levels), "tiers": dict(tiers),
         "argmax": dict(argmax), "margins": margins, "unparsed": unparsed, "records": results}, indent=1))
    if unparsed:
        print(f"\n    {len(unparsed)} answers were not valid JSON — a finding about asking for verbatim spans")
    print(f"\nwrote {out / 'probe.json'} — read (c)'s spans by eye for homonyms")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
