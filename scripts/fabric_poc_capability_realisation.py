"""POC capability realisation — the Knowledge Management L4 grid (same layout as capability-map-v1.6b/d),
each cell coloured by POC status and listing what realises it in the lab.

    python scripts/fabric_poc_capability_realisation.py [out.png]
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

STATUS = {  # fill, edge, label
    "exists": ("#d7ecd9", "#2f855a", "EXISTS — lab component used as is"),
    "extend": ("#fbe7b3", "#c9950c", "EXTEND — existing component gains fabric tools or data"),
    "new":    ("#fde8e6", "#c0392b", "NEW — built for the POC"),
    "dormant":("#cfe0f7", "#2b6cb0", "BUILT, DORMANT / READ-ONLY — proves a CQ, not live in the loop"),
    "out":    ("#f2f2f2", "#9a9a9a", "NOT IN THE POC"),
}
GROUPS = [
    ("1", "Knowledge Organisation", "define meaning and identity", [
        ("Vocabulary Management", "extend", "D3 · D8", ["semantic-mcp: healthcare + insurance SKOS schemes, exactMatch mappings", "fab: ontology + SHACL in git", "vocab_link · vocab_propose · vocab_promote", "steward decisions via the review app"]),
        ("Catalog Management", "new", "D1 · D11", ["fabric-mcp over Neon Postgres", "ULID IRIs · pointer JSONB · no content column", "fabric_catalog_upsert · _state"])]),
    ("2", "Knowledge Production", "create managed artifacts", [
        ("Content Synthesis", "new", "D6 · D7 · D4", ["synthesis-agent (kimi-k3 via gateway)", "ADR template as a registered skill", "draft by collab_put, fabric-tagged", "new event for the pointer replaces the draft"]),
        ("Knowledge Classification", "new", "D6 · D7", ["classifier-agent: type (S)", "owner map list via collab_list (C)", "label from the item via collab_item (C)", "label match + nomic nearest neighbour (X/S)"]),
        ("Version Management", "new", "D1", ["baseline fields on the catalog record", "SharePoint version id read at approval"]),
        ("Traceability Management", "new", "D1 · D2 · D8", ["rung 1: ado-mcp work_links", "rung 2: id regex over content", "rung 3: authorship + time window", "rung 4: association card; orphan queue"])]),
    ("3", "Knowledge Governance", "decide what is trusted", [
        ("Ownership & Stewardship", "extend", "D8", ["owner map = SharePoint list (collab_list)", "steward queues as review-app pages", "over the approvals streams"]),
        ("Knowledge Review", "extend", "D8", ["approvals_ask kind draft-review", "Teams adaptive card · human_decision (actor)", "rework re-runs synthesis", "escalation timer: follow-up"]),
        ("Duplicate Management", "dormant", "D1 · D11", ["fabric_similar over pgvector", "embeddings stored; gateway routes 'no'"]),
        ("Access Management", "exists", "consumed", ["Entra per agent · gateway grants", "per-tool ACLs · label read from the source", "one door for people and agents"]),
        ("Audit Management", "exists", "consumed", ["one OTel trace per run (Jaeger)", "spend ledger per key", "approvals:decisions stream"]),
        ("Records Retention", "out", "consumed", ["not in the POC"])]),
    ("4", "Knowledge Discovery", "find and reuse what exists", [
        ("Knowledge Retrieval", "new", "D1", ["fabric_search: embeddings + catalog joins", "fabric_traverse over chosen rung graphs", "reference_search for the corpus", "review app for people; same tools for agents"]),
        ("Knowledge Recommendation", "out", "Transitional", ["not in the POC"]),
        ("Expertise Identification", "out", "Target", ["CQ-26 runnable over fixtures only"])]),
    ("5", "Knowledge Currency", "keep published knowledge current", [
        ("Change Detection", "extend", "D4 · D2 · D5", ["collab_watch + ADO hooks → fabric:events", "consumer group wf-fabric", "allow-list + fabric-tag filter in the consumer"]),
        ("Change Impact Analysis", "dormant", "D1", ["fabric_impact: SPARQL over C·X·H(+D)", "depth bound; read-only in the POC (CQ-10)"]),
        ("Subscription Management", "extend", "D9", ["notifier pattern reused:", "workflow:finished → Teams webhook"]),
        ("Republication", "new", "D9", ["fabric-projector: Markdown via collab_put", "optional Obsidian vault", "embedding recomputed after baseline"]),
        ("Catalog Reconciliation", "new", "D10", ["fabric-reconciler timer sweep", "records vs sources via port 2 → events", "the laptop's substitute for callbacks"]),
        ("Remediation Management", "out", "Target", ["not in the POC"])]),
]


def box(ax, H, x, y, w, h, fc, ec, lw=1.4, ls="-", r=1.0):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, s, k=0.9):
    return min(fs, fs * (w - 2.4) / (k * max(1, len(s))))


def main(out: Path) -> None:
    W = 192.0
    m, pad, L2PAD, L2HDR, GAP = 2.2, 2.2, 1.6, 3.2, 1.4
    L4HDR, LINE = 7.4, 2.3
    inner = W - 2 * m - 2 * pad
    rows = [[GROUPS[0], GROUPS[1]], [GROUPS[2]], [GROUPS[3]], [GROUPS[4]]]

    def cw_for(row, g):
        if len(row) == 2:
            unit = (inner - 1.6) / 6
            gw = unit * 2 if g is row[0] else unit * 4
        else:
            gw = inner
        n = len(g[3]); return (gw - 2 * L2PAD - GAP * (n - 1)) / n

    def lines_for(cell, w):
        out = []
        for s in cell[3]:
            out += textwrap.wrap(s, max(12, int((w - 2.4) / 0.66)))
        return out

    row_h = []
    for r in rows:
        h = 0
        for g in r:
            w = cw_for(r, g)
            for c in g[3]:
                h = max(h, L4HDR + len(lines_for(c, w)) * LINE + 1.4)
        row_h.append(h)
    GHs = [L2PAD + L2HDR + h + L2PAD for h in row_h]
    h1 = pad + 5.4 + sum(GHs) + (len(rows) - 1) * 1.6 + pad
    H = 8.6 + h1 + 2.0 + 9.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "POC realisation of the Knowledge Management capabilities on the lab (same grid as capability-map-v1.6b)",
            ha="center", va="center", fontsize=17, fontweight="bold", color="#222")
    ax.text(W / 2, H - 6.4, "cell colour = POC status · lines = what realises it · D-refs point to the delta table (§2.1)", ha="center", va="center", fontsize=10, color="#777", style="italic")

    y0 = 8.6
    box(ax, H, m, y0, W - 2 * m, h1, "white", "#444", 2.0, r=1.6)
    ax.text(m + 2.6, H - y0 - 3.2, "L2 · Knowledge Management — POC", ha="left", va="center", fontsize=15, fontweight="bold", color="#222")
    x0 = m + pad; ry = y0 + pad + 5.4
    for r, gh, lh in zip(rows, GHs, row_h):
        xs = [x0] if len(r) == 1 else [x0, x0 + (inner - 1.6) / 6 * 2 + 1.6]
        for g, gx in zip(r, xs):
            gw = inner if len(r) == 1 else ((inner - 1.6) / 6 * (2 if g is r[0] else 4))
            box(ax, H, gx, ry, gw, gh, "white", "#b5b5b5", 1.2)
            ax.text(gx + 1.6, H - ry - 1.9, f"{g[0]}  {g[1]}", ha="left", va="center", fontsize=12, fontweight="bold", color="#555")
            ax.text(gx + gw - 1.6, H - ry - 1.9, f"L3 · {g[2]}", ha="right", va="center", fontsize=9.5, color="#777", style="italic")
            n = len(g[3]); cw = (gw - 2 * L2PAD - GAP * (n - 1)) / n
            for i, c in enumerate(g[3]):
                cx = gx + L2PAD + i * (cw + GAP); cy = ry + L2PAD + L2HDR
                fc, ec, _ = STATUS[c[1]]
                box(ax, H, cx, cy, cw, lh, fc, ec, 1.6, (0, (3, 2)) if c[1] == "out" else "-")
                ax.text(cx + cw / 2, H - cy - 2.6, c[0], ha="center", va="center", fontsize=fit(12, cw, c[0]), fontweight="bold", color="#222" if c[1] != "out" else "#777")
                tag = f"{c[1].upper()} · {c[2]}"
                ax.text(cx + cw / 2, H - cy - 5.1, tag, ha="center", va="center", fontsize=fit(8.4, cw, tag, 0.66), color=ec, fontweight="bold")
                for j, ln in enumerate(lines_for(c, cw)):
                    ax.text(cx + 1.6, H - cy - L4HDR - 1.1 - LINE * j, "· " + ln, ha="left", va="center", fontsize=8.6, color="#333" if c[1] != "out" else "#888")
        ry += gh + 1.6

    ly = y0 + h1 + 2.0 + 2.4; lx = 6
    for key, (fc, ec, lbl) in STATUS.items():
        box(ax, H, lx, ly, 3.4, 2.6, fc, ec, 1.4, (0, (3, 2)) if key == "out" else "-", r=0.6)
        ax.text(lx + 4.4, H - ly - 1.3, lbl, ha="left", va="center", fontsize=9.6, color="#222")
        lx += 4.4 + 0.66 * len(lbl) + 5
    fig.savefig(out, dpi=100, facecolor="white"); print(out, f"{int(W*10)}x{int(H*10)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/poc-capability-realisation-v1.0.png"))
