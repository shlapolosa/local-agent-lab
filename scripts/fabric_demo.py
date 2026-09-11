"""The Documentation Fabric demonstration (docs/fabric/POC.md §7) against a running lab — local or cloud.

Drives the whole loop THROUGH THE GATEWAY, as an operator with the master key would, and prints the evidence
each step leaves behind (ids, rungs, counts — never content). Every step is a real call; nothing here fakes a
service. Stops at the first failed check and exits 1, so it doubles as the fabric's live smoke.

Steps
  1. contract: every `SemanticTools` tool the fabric declares is exposed by the LIVE gateway
  2. seed: the fabric's ontology and doc-type scheme are registered; the shapes conform on an empty fabric
  3. identify: a lab-produced artifact (a minutes ref you name, or a demo ref) is catalogued at C with its
     type as a FACT and its delivery edge (meeting:<id>) — CQ-01, CQ-02
  4. classify: a person's document gets a suggested type (S) and a looked-up label (C) — CQ-12, CQ-13
  5. link + propose: subjects matched by label (X); a miss becomes a candidate — CQ-15, CQ-17
  6. impact: the edge asserted at S is NOT in the impact answer; the one at X is — CQ-10 / NFR-7
  7. promote: a person (you, named on the command line) confirms the suggestion → H — CQ-05, CQ-06
  8. events: an ArtifactChanged for the document is emitted on `fabric:events`; the ingress admits/drops it
     per the allow-list (run `fabric-ingress` to watch it become an artifact_intake run and an approval)
  9. fitness: a content property is refused by the shapes — CQ-03 / NFR-2

Usage:
  set -a && source .env && set +a
  .venv/bin/python scripts/fabric_demo.py --actor you@tenant [--minutes-ref art://…] [--doc-handle collab://item/…]
Evidence lands in var/out/fabric-demo/<timestamp>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.core import ids                                                          # noqa: E402
from lab.platform import config, fabric_events, mcp_client                        # noqa: E402
from lab.platform.contracts import ArtifactChanged, SemanticTools                  # noqa: E402

OUT = config.VAR_DIR / "out" / "fabric-demo"
EVIDENCE: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    EVIDENCE.append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""), flush=True)
    if not ok:
        _write(); sys.exit(1)


def _write() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"gateway": config.GATEWAY_URL, "evidence": EVIDENCE}, indent=1))
    print(f"\nevidence: {path}")


class Gateway:
    def __init__(self, key: str):
        self.headers = {"Authorization": f"Bearer {key}"}

    def call(self, suffix: str, **args):
        return asyncio.run(mcp_client.call_tools(self.headers, config.GATEWAY_MCP_URL, [(suffix, args)]))[0]

    def tools(self) -> set[str]:
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        async def go():
            async with Client(StreamableHttpTransport(config.GATEWAY_MCP_URL, headers=self.headers)) as c:
                return {t.name for t in await c.list_tools()}
        return asyncio.run(go())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--actor", required=True, help="the person the promotion is recorded as (you)")
    ap.add_argument("--key", default=os.environ.get("LITELLM_MASTER_KEY", ""), help="a gateway key holding semantic_mcp")
    ap.add_argument("--minutes-ref", default="", help="an art:// ref a minutes run produced (default: a demo ref)")
    ap.add_argument("--doc-handle", default="", help="a collab://item/… handle of a person's document (default: a demo handle)")
    ap.add_argument("--meeting", default="AAMkDemo", help="the meeting id the minutes were delivered under")
    a = ap.parse_args(argv)
    if not a.key:
        print("a gateway key is required (--key or LITELLM_MASTER_KEY)", file=sys.stderr); return 2
    gw = Gateway(a.key)
    stamp = ids.ulid()
    minutes_ref = a.minutes_ref or f"art://demo-{stamp[-6:]}/meeting.minutes.json"
    doc_handle = a.doc_handle or f"collab://item/demo-drive/{stamp[-8:]}"

    print("1. contract")
    exposed = gw.tools()
    missing = sorted(t for t in SemanticTools.names() if not any(n.endswith(t) for n in exposed))
    check("every fabric tool is exposed by the live gateway", not missing, f"missing: {missing}" if missing else f"{len(exposed)} tools")

    print("2. seed")
    onts = {o["name"] for o in gw.call(SemanticTools.ontologies)}
    check("fabric ontology + doc-types registered", {"fabric", "doc-types"} <= onts, ", ".join(sorted(onts)))
    shapes = gw.call(SemanticTools.validate_shapes)
    check("the fabric conforms to its shapes", shapes.get("conforms") is True, "; ".join(shapes.get("messages") or []))

    print("3. identify (CQ-01, CQ-02)")
    row = gw.call(SemanticTools.catalog_upsert, pointer={"source": "lab", "ref": minutes_ref}, title=f"Minutes demo {stamp[-6:]}",
                  produced_by="transcript_to_minutes", context=f"meeting:{a.meeting}", source_kind="lab")
    m = row["iri"]
    check("a lab artifact is catalogued with its type as a FACT", row.get("document_type", "").endswith("#minutes"), m)
    got = gw.call(SemanticTools.catalog_get, iri=m)
    links = {(l["predicate"], l["rung"]) for l in got["links"]}
    check("delivered under the run's context at C", ("deliveredUnder", "C") in links and ("documentType", "C") in links, str(sorted(links)))

    print("4. classify (CQ-12, CQ-13)")
    doc = gw.call(SemanticTools.catalog_upsert, pointer={"source": "collab", "handle": doc_handle, "version": "1"},
                  title=f"ADR demo {stamp[-6:]}")
    d = doc["iri"]
    s = gw.call(SemanticTools.catalog_assert, iri=d, field="document_type", value="urn:fabric:scheme:doc-types#decision-record",
                rung="S", method="classifier-agent", confidence=0.83)
    check("a suggested type lands at S with its confidence", s.get("rung") == "S", s.get("assertion", ""))
    c = gw.call(SemanticTools.catalog_assert, iri=d, field="sensitivity_label", value="Confidential", rung="C", method="site-default")
    check("a looked-up label lands at C", c.get("rung") == "C")
    try:
        gw.call(SemanticTools.catalog_assert, iri=d, field="owner", value="urn:fabric:person:guess", rung="S", method="guess", confidence=0.5)
        check("a guessed owner is refused (NFR-3)", False, "it was accepted")
    except Exception as e:                                                       # noqa: BLE001
        check("a guessed owner is refused (NFR-3)", "NFR-3" in str(e), str(e)[:80])

    print("5. link + propose (CQ-15, CQ-17)")
    link = gw.call(SemanticTools.vocab_link, iri=d, terms=["Care Delivery", f"Novel Term {stamp[-4:]}"])
    check("label matches link at X; misses are reported", bool(link.get("missed")), f"linked={len(link.get('linked') or [])} missed={link.get('missed')}")
    cand = gw.call(SemanticTools.vocab_propose, label=link["missed"][0], actor="classifier-agent", definition="proposed in the demo")
    check("a miss becomes a candidate for a steward", cand.get("iri", "").startswith("urn:fabric:candidate:"), cand.get("iri", ""))

    print("6. impact (CQ-10 / NFR-7)")
    gw.call(SemanticTools.edge_assert, subject=d, predicate="urn:fabric:ont#references", object=m, rung="X", method="link-extraction")
    ghost = gw.call(SemanticTools.catalog_upsert, pointer={"source": "collab", "handle": f"{doc_handle}-s"}, title="suggested only")["iri"]
    gw.call(SemanticTools.edge_assert, subject=ghost, predicate="urn:fabric:ont#references", object=m, rung="S", method="nn", confidence=0.6)
    hit = gw.call(SemanticTools.impact, iri=m)
    iris = [h["iri"] for h in hit]
    check("impact lists the X edge and never the S edge", d in iris and ghost not in iris, f"{len(iris)} hit(s)")

    print("7. promote (CQ-05, CQ-06)")
    p = gw.call(SemanticTools.promote, subject=d, predicate="urn:fabric:ont#documentType",
                object="urn:fabric:scheme:doc-types#decision-record", actor=a.actor, method="demo-review")
    check("a person moves the suggestion to H", p.get("rung") == "H" and p.get("from") == "S", p.get("assertion", ""))
    try:
        gw.call(SemanticTools.promote, subject=d, predicate="urn:fabric:ont#references", object=m, actor="", method="x")
        check("a blank actor is refused", False, "it was accepted")
    except Exception as e:                                                       # noqa: BLE001
        check("a blank actor is refused", "actor" in str(e), str(e)[:80])

    print("8. events")
    ev = ArtifactChanged(event_id=ids.ulid(), pointer={"source": "collab", "handle": doc_handle, "version": "2"},
                         source_kind="collab", change="updated", actor_oid="demo",
                         occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    entry = fabric_events.publish(ev)
    admitted = any(doc_handle.split("/")[3] == s.split(":", 1)[1] or s == "collab:*" for s in config.FABRIC_ALLOWLIST)
    check("an ArtifactChanged is on fabric:events", bool(entry),
          f"entry {entry}; the ingress will {'ADMIT it (allow-listed)' if admitted else 'DROP it (not allow-listed: set FABRIC_ALLOWLIST)'}")

    print("9. fitness (CQ-03 / NFR-2)")
    try:
        gw.call(SemanticTools.edge_assert, subject=d, predicate="urn:fabric:ont#body", object="the whole document", rung="C", method="x")
        check("a content property is refused by the shapes", False, "it was accepted")
    except Exception as e:                                                       # noqa: BLE001
        check("a content property is refused by the shapes", "shapes" in str(e), str(e)[:80])
    check("the fabric still conforms", gw.call(SemanticTools.validate_shapes).get("conforms") is True)

    _write()
    print(f"\nrecords: minutes {m}\n         document {d}\nnext: watch fabric-ingress → wf-fabric → an approval in the review app; "
          f"approve it as {a.actor} to see the curator promote and wf-artifact-publish baseline the record.")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    print(f"done in {time.time() - t0:.0f}s")
    raise SystemExit(code)
