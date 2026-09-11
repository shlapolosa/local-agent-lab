"""Documentation Fabric capability map v1.3 — BIZBOK levelling and naming, drilled to L5.

Changes from v1.2 (verified against BIZBOK naming guidance, TOGAF business-capability guide,
ISO 30401 §4.4 and APQC PCF 13.5):
  * Levels re-anchored: Knowledge Management is an L2 under an enterprise L1 (Information Management,
    shown as CONTEXT — the actual L1 is whatever DOH's enterprise map says). Groups are L3, chips L4,
    lines inside a chip are L5 sub-capabilities.
  * Every capability is a noun phrase (business object + management/action), never a verb, outcome,
    mechanism or technology. Verbs appear only as the italic "what it lets us do" gloss.
  * Remediation Management added (FR-10 had no capability home in v1.0–v1.2).

    python scripts/fabric_capability_map_v1_3.py [out.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PHASE = {"mvp": ("#ececec", "#8c8c8c"), "transitional": ("#f5d78e", "#c9950c"), "target": ("#f2a39c", "#c0392b")}
NEW = "#2b6cb0"
W, H = 192.0, 166.0
CH, L2PAD, L2HDR, GAP = 18.6, 1.6, 3.2, 1.4
GH = L2PAD + L2HDR + CH + L2PAD  # group (L3) box height


def chip(ax, x, y, w, title, num, subs, phase, new=False):
    fill, edge = PHASE[phase]
    ax.add_patch(FancyBboxPatch((x, H - y - CH), w, CH, boxstyle="round,pad=0,rounding_size=1.2",
                                fc=fill, ec=NEW if new else edge, lw=2.2 if new else 1.6,
                                ls=(0, (5, 2.5)) if new else "-"))
    fs = min(12.5, 12.5 * (w - 2.4) / (0.98 * len(title)))
    ax.text(x + w / 2, H - y - 2.6, title, ha="center", va="center", fontsize=fs, fontweight="bold", color="#222")
    ax.text(x + w / 2, H - y - 5.0, num, ha="center", va="center", fontsize=9, color="#777")
    ax.plot([x + 2.0, x + w - 2.0], [H - y - 6.3] * 2, color=edge, lw=0.6, alpha=0.6)
    for i, s in enumerate(subs):
        ax.text(x + 2.2, H - y - 8.2 - 2.45 * i, "· " + s, ha="left", va="center", fontsize=9.6, color="#444")


def group(ax, x, y, w, num, title, gloss, chips):
    ax.add_patch(FancyBboxPatch((x, H - y - GH), w, GH, boxstyle="round,pad=0,rounding_size=1.2",
                                fc="white", ec="#b5b5b5", lw=1.2))
    ax.text(x + 1.6, H - y - 1.9, f"{num}  {title}", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
    ax.text(x + w - 1.6, H - y - 1.9, f"L3 · {gloss}", ha="right", va="center", fontsize=10, color="#777", style="italic")
    n = len(chips)
    cw = (w - 2 * L2PAD - GAP * (n - 1)) / n
    for i, c in enumerate(chips):
        chip(ax, x + L2PAD + i * (cw + GAP), y + L2PAD + L2HDR, cw, *c)


def main(out: Path) -> None:
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "Capability map v1.3 — Knowledge Management (L2), decomposed to L5, phased MVP → transitional → target",
            ha="center", va="center", fontsize=18, fontweight="bold", color="#222")

    m, pad = 2.2, 2.2
    # L1 context band
    y = 6.6
    ax.add_patch(FancyBboxPatch((m, H - y - 8.4), W - 2 * m, 8.4, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="#f7f7f7", ec="#999", lw=1.4, ls=(0, (3, 2))))
    ax.text(m + 2.6, H - y - 2.4, "L1 · Information Management  (enterprise context — anchor to DOH's enterprise capability map)",
            ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
    sibs = ["Data Management", "Document & Content Management", "Records Management", "Knowledge Management  ◀ this map"]
    sx = m + 2.6
    for s in sibs:
        this = s.startswith("Knowledge")
        ww = 0.86 * len(s) + 3.6
        ax.add_patch(FancyBboxPatch((sx, H - y - 7.4), ww, 3.0, boxstyle="round,pad=0,rounding_size=0.8",
                                    fc="white" if this else "#efefef", ec="#444" if this else "#bbb", lw=1.6 if this else 1.0))
        ax.text(sx + ww / 2, H - y - 5.9, s, ha="center", va="center", fontsize=10.5,
                fontweight="bold" if this else "normal", color="#222" if this else "#888")
        sx += ww + 2.0
    ax.text(W - m - 2.6, H - y - 5.9, "siblings are L2 peers, out of scope", ha="right", va="center",
            fontsize=10, color="#888", style="italic")

    # L2 box
    y0 = y + 8.4 + 2.0
    rows = 4
    inner = W - 2 * m - 2 * pad
    h1 = pad + 5.4 + rows * GH + (rows - 1) * 1.6 + pad
    ax.add_patch(FancyBboxPatch((m, H - y0 - h1), W - 2 * m, h1, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="white", ec="#444", lw=2.0))
    ax.text(m + 2.6, H - y0 - 3.2, "L2 · Knowledge Management", ha="left", va="center", fontsize=16, fontweight="bold", color="#222")
    ax.text(W - m - 2.6, H - y0 - 3.2,
            "L3 groups follow ISO 30401 §4.4 knowledge-development stages · names are noun phrases per BIZBOK · chip = L4 · lines = L5",
            ha="right", va="center", fontsize=10.5, color="#777", style="italic")
    x0 = m + pad
    ry = y0 + pad + 5.4

    unit = (inner - 1.6) / 6
    group(ax, x0, ry, unit * 2, "1", "Knowledge Organisation", "define meaning and identity", [
        ("Vocabulary Management", "1.1 · MVP · new", ["Ontology Management", "Concept Scheme Management",
                                                   "Vocabulary Alignment", "Concept Lifecycle (propose · deprecate)"], "mvp", True),
        ("Catalog Management", "1.2 · MVP · new", ["Artifact Identification (one IRI)", "Pointer Management (never content)",
                                                "Lifecycle State Management"], "mvp", True)])
    group(ax, x0 + unit * 2 + 1.6, ry, unit * 4, "2", "Knowledge Production", "create managed artifacts", [
        ("Content Synthesis", "2.1 · MVP", ["Template Management", "Draft Generation", "Re-draft on Source Change"], "mvp"),
        ("Knowledge Classification", "2.2 · MVP", ["Type Classification", "Owner Resolution", "Sensitivity Resolution", "Concept Linking"], "mvp"),
        ("Version Management", "2.3 · MVP", ["Baseline Management", "Source Version Confirmation"], "mvp"),
        ("Traceability Management", "2.4 · MVP", ["Delivery Association (ladder)", "Reference Extraction",
                                                "Association Confirmation", "Orphan Management"], "mvp")])

    ry += GH + 1.6
    group(ax, x0, ry, inner, "3", "Knowledge Governance", "decide what is trusted and who may see it", [
        ("Ownership & Stewardship", "3.1 · MVP", ["Owner Assignment", "Steward Assignment", "Steward Queue Management"], "mvp"),
        ("Knowledge Review", "3.2 · MVP", ["Owner Approval", "Rework", "Escalation"], "mvp"),
        ("Duplicate Management", "3.3 · Transitional", ["Overlap Detection", "Merge Adjudication"], "transitional"),
        ("Access Management", "3.4 · MVP", ["Label Pass-through", "Principal Scoping (parity)"], "mvp"),
        ("Audit Management", "3.5 · MVP", ["Event Logging", "Audit Query"], "mvp"),
        ("Records Retention", "3.6 · Target", ["Retention Policy Application", "Disposition"], "target")])

    ry += GH + 1.6
    group(ax, x0, ry, inner, "4", "Knowledge Discovery", "find and reuse what exists", [
        ("Knowledge Retrieval", "4.1 · MVP", ["Semantic Search", "Catalog & Graph Traversal", "Agent Tool Access (MCP)"], "mvp"),
        ("Knowledge Recommendation", "4.2 · Transitional", ["Reuse Suggestion", "Related-artifact Joins"], "transitional"),
        ("Expertise Identification", "4.3 · Target", ["Authorship Analysis", "Ownership Analysis"], "target")])

    ry += GH + 1.6
    group(ax, x0, ry, inner, "5", "Knowledge Currency", "keep published knowledge current", [
        ("Change Detection", "5.1 · MVP", ["Event Capture", "Event Filtering (allow-list)", "Loop Guard"], "mvp"),
        ("Change Impact Analysis", "5.2 · Transitional", ["Trusted-edge Traversal", "Affected-set Determination", "Depth Bounding"], "transitional"),
        ("Subscription Management", "5.3 · Transitional", ["Follow", "Notification", "Digest"], "transitional"),
        ("Republication", "5.4 · Transitional", ["Projection Rebuild", "Index Refresh"], "transitional"),
        ("Catalog Reconciliation", "5.5 · Transitional", ["Drift Detection", "Drift Resolution"], "transitional"),
        ("Remediation Management", "5.6 · Target · new", ["Fix Drafting", "Native-review Filing", "Whitelisted Auto-apply"], "target", True)])

    # principles
    py = y0 + h1 + 2.0
    ph = 15.0
    ax.add_patch(FancyBboxPatch((m, H - py - ph), W - 2 * m, ph, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="#fafafa", ec="#999", lw=1.4, ls=(0, (2, 2))))
    ax.text(m + 2.6, H - py - 2.4, "Constraining principles  (apply to every cell — constraints, not capabilities)",
            ha="left", va="center", fontsize=12.5, fontweight="bold", color="#444")
    principles = [
        "Metadata-only fabric — no document content in any fabric store; enforced as a CI fitness function",
        "The source decides access, at read time — labels pass through; the fabric is never a policy engine",
        "People and agents are peers — same interfaces, label trimming, principal identity and audit",
        "Edges are captured, never guessed — impact analysis is served only over constructed, extracted or confirmed edges",
    ]
    for i, t in enumerate(principles):
        ax.text(m + 3.2, H - py - 5.0 - 2.35 * i, "•  " + t, ha="left", va="center", fontsize=10.5, color="#444")

    ly = py + ph + 2.4
    items = [("mvp", "MVP — ADR thin slice · new items only", False),
             ("transitional", "+ Transitional — trace graph · dedup · currency loop", False),
             ("target", "+ Target — corpus-scale effects", False),
             ("mvp", "new capability in v1.3", True)]
    lx = 8
    for p, label, new in items:
        fill, edge = PHASE[p]
        ax.add_patch(FancyBboxPatch((lx, H - ly - 3.2), 3.4, 2.6, boxstyle="round,pad=0,rounding_size=0.6",
                                    fc=fill, ec=NEW if new else edge, lw=2.0 if new else 1.6, ls=(0, (4, 2)) if new else "-"))
        ax.text(lx + 4.6, H - ly - 1.9, label, ha="left", va="center", fontsize=12, color="#222")
        lx += 4.6 + 0.8 * len(label) + 8

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=100, facecolor="white")
    print(out, f"{int(W*10)}x{int(H*10)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/capability-map-v1.3.png"))
