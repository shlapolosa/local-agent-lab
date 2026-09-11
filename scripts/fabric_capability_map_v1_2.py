"""Documentation Fabric capability map v1.2 — one L1 (Knowledge management), five MECE L2 groups.

L2 groups partition by the verb applied to knowledge, in lifecycle order: Organise, Produce, Govern,
Discover, Propagate. Every L3 has exactly one home; constraints (metadata-only, source decides at read
time, consumer parity) are principles in the footer, not cells. The semantic layer is a REALISATION and
belongs in the architecture views, not here. Ids are fresh; every diagram is recreated from this map. Regenerate with:

    python scripts/fabric_capability_map.py [out.png]
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PHASE = {  # phase -> (fill, edge)
    "mvp": ("#ececec", "#8c8c8c"),
    "transitional": ("#f5d78e", "#c9950c"),
    "target": ("#f2a39c", "#c0392b"),
}
NEW = "#2b6cb0"
W, H = 192.0, 126.0  # drawing units, 1 unit = 10 px

CH, L2PAD, L2HDR, GAP = 12.4, 1.6, 3.2, 1.4
L2H = L2PAD + L2HDR + CH + L2PAD


def chip(ax, x, y, w, title, sub, phase, new=False, fs=12.5):
    fill, edge = PHASE[phase]
    ax.add_patch(FancyBboxPatch((x, H - y - CH), w, CH, boxstyle="round,pad=0,rounding_size=1.2",
                                fc=fill, ec=NEW if new else edge, lw=2.2 if new else 1.6,
                                ls=(0, (5, 2.5)) if new else "-"))
    fit = min(fs, fs * (w - 2.4) / (0.98 * len(title)))  # ~0.98 units per bold char at 12.5 pt
    ax.text(x + w / 2, H - y - CH * 0.27, title, ha="center", va="center", fontsize=fit,
            fontweight="bold", color="#222")
    lines = textwrap.wrap(sub, width=max(12, int((w - 2.0) / 0.74)))[:2]
    for i, line in enumerate(lines):
        ax.text(x + w / 2, H - y - CH * (0.56 + 0.22 * i), line, ha="center", va="center",
                fontsize=10, color="#555")


def l2(ax, x, y, w, num, title, verb, chips, fs=12.5):
    ax.add_patch(FancyBboxPatch((x, H - y - L2H), w, L2H, boxstyle="round,pad=0,rounding_size=1.2",
                                fc="white", ec="#b5b5b5", lw=1.2))
    ax.text(x + 1.6, H - y - 1.9, f"{num}  {title}", ha="left", va="center", fontsize=12.5,
            fontweight="bold", color="#555")
    ax.text(x + w - 1.6, H - y - 1.9, verb, ha="right", va="center", fontsize=10, color="#777",
            style="italic")
    n = len(chips)
    cw = (w - 2 * L2PAD - GAP * (n - 1)) / n
    for i, c in enumerate(chips):
        chip(ax, x + L2PAD + i * (cw + GAP), y + L2PAD + L2HDR, cw, *c, fs=fs)


def main(out: Path) -> None:
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    ax.text(W / 2, H - 3.2, "Capability map v1.2 — Knowledge management, phased MVP → transitional → target",
            ha="center", va="center", fontsize=19, fontweight="bold", color="#222")

    m, pad = 2.2, 2.2
    y0 = 8.4
    inner = W - 2 * m - 2 * pad
    rows = 4
    h1 = pad + 5.4 + rows * L2H + (rows - 1) * 1.6 + pad
    ax.add_patch(FancyBboxPatch((m, H - y0 - h1), W - 2 * m, h1, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="white", ec="#444", lw=2.0))
    ax.text(m + 2.6, H - y0 - 3.2, "Knowledge management", ha="left", va="center", fontsize=16,
            fontweight="bold", color="#222")
    ax.text(W - m - 2.6, H - y0 - 3.2,
            "L2 groups partition by the verb applied to knowledge, in lifecycle order · APQC PCF 13.x · ISO 30401",
            ha="right", va="center", fontsize=10.5, color="#777", style="italic")

    x0 = m + pad
    ry = y0 + pad + 5.4

    # Row 1: Organise (2) + Produce (4) on a 6-column grid
    unit = (inner - 1.6) / 6
    w_org, w_prod = unit * 2, unit * 4
    l2(ax, x0, ry, w_org, "1", "Organise", "define meaning and identity", [
        ("Vocabulary management", "1.1 · meaning: ontology · concept schemes · alignment · stewarded", "mvp", True),
        ("Cataloguing & identity", "1.2 · one identifier per artifact · pointer to the system of record", "mvp", True)])
    l2(ax, x0 + w_org + 1.6, ry, w_prod, "2", "Produce", "create managed artifacts", [
        ("Authoring & templating", "2.1 · draft synthesis against type templates", "mvp"),
        ("Classification & tagging", "2.2 · type suggested · owner and label resolved · concepts linked", "mvp"),
        ("Version & baseline", "2.3 · baseline stamped on approval", "mvp"),
        ("Traceability capture", "2.4 · work-item association ladder · reference edges · provenance", "mvp")])

    # Row 2: Govern (6)
    ry += L2H + 1.6
    l2(ax, x0, ry, inner, "3", "Govern", "decide what is trusted and who may see it", [
        ("Ownership & stewardship", "3.1 · owner map · steward role", "mvp"),
        ("QA & review", "3.2 · one-touch owner gate · timer escalation", "mvp"),
        ("Dup detection & merge", "3.3 · overlap check · steward adjudication", "transitional"),
        ("Access control", "3.4 · label pass-through · consumer parity", "mvp"),
        ("Audit trail", "3.5 · synthesis, approval, propagation logged", "mvp"),
        ("Retention & disposition", "3.6 · records policy · disposition", "target")])

    # Row 3: Discover (3), full width
    ry += L2H + 1.6
    l2(ax, x0, ry, inner, "4", "Discover", "find and reuse what exists", [
        ("Semantic search", "4.1 · hybrid + vector retrieval", "mvp"),
        ("Recommendation & reuse", "4.2 · suggest before create", "transitional"),
        ("Expertise location", "4.3 · who knows what, from catalog metadata", "target")])

    # Row 4: Propagate (5), full width
    ry += L2H + 1.6
    l2(ax, x0, ry, inner, "5", "Propagate", "keep published knowledge current", [
        ("Change event capture", "5.1 · source-system notifications · allow-listed", "mvp"),
        ("Impact analysis", "5.2 · traversal over trusted edges only", "transitional"),
        ("Subscription & notification", "5.3 · follow · digests", "transitional"),
        ("Sync & re-publication", "5.4 · projections and index rebuilt", "transitional"),
        ("Catalog reconciliation", "5.5 · catalog vs source drift", "transitional")])

    # Principles footer — constraints, not capabilities
    py = y0 + h1 + 2.4
    ph = 15.4
    ax.add_patch(FancyBboxPatch((m, H - py - ph), W - 2 * m, ph, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="#fafafa", ec="#999", lw=1.4, ls=(0, (2, 2))))
    ax.text(m + 2.6, H - py - 2.6, "Constraining principles  (apply to every cell — constraints, not capabilities)",
            ha="left", va="center", fontsize=13, fontweight="bold", color="#444")
    principles = [
        "Metadata-only fabric — no document content in any fabric store; enforced as a CI fitness function",
        "The source decides access, at read time — labels pass through; the fabric is never a policy engine",
        "People and agents are peers — same interfaces, same label trimming, same principal identity, same audit",
        "Edges are captured, never guessed — impact analysis is served only over constructed, extracted or confirmed edges",
    ]
    for i, t in enumerate(principles):
        ax.text(m + 3.2, H - py - 5.6 - 2.6 * i, "•  " + t, ha="left", va="center", fontsize=11, color="#444")

    # Legend
    ly = py + ph + 2.6
    items = [("mvp", "MVP — ADR thin slice · new items only", False),
             ("transitional", "+ Transitional — trace graph · dedup · currency loop", False),
             ("target", "+ Target — corpus-scale effects", False),
             ("mvp", "new in v1.2 — knowledge organisation", True)]
    lx = 8
    for p, label, new in items:
        fill, edge = PHASE[p]
        ax.add_patch(FancyBboxPatch((lx, H - ly - 3.2), 3.4, 2.6, boxstyle="round,pad=0,rounding_size=0.6",
                                    fc=fill, ec=NEW if new else edge, lw=2.0 if new else 1.6,
                                    ls=(0, (4, 2)) if new else "-"))
        ax.text(lx + 4.6, H - ly - 1.9, label, ha="left", va="center", fontsize=12.5, color="#222")
        lx += 4.6 + 0.72 * len(label) + 8

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=100, facecolor="white")
    print(out, f"{int(W*10)}x{int(H*10)}")


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/capability-map-v1.2.png")
    main(dest)
