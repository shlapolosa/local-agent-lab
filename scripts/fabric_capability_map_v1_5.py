"""Documentation Fabric capability map v1.5a — initiative overlay with THREE relationships.

v1.5 change: "channel" was a role, not a relationship; Message Delivery and AI Platform & Agent Management are
estate capabilities the initiative uses without building or changing them, so they are CONSUME. The KM
drill-down is unchanged from v1.4b.

Superseded description follows.

  (a) capability-map-v1.4a-enterprise-overlay.png
      BIZBOK-style initiative overlay on an enterprise-level slice: every capability the initiative
      touches, coloured by RELATIONSHIP (uplift · consume · operating-model change · channel). L1 names
      are BIZBOK generic placeholders — replace with DOH's enterprise map names.
  (b) capability-map-v1.4b-km-drilldown.png
      Knowledge Management (L2) to L5, as v1.3, with Records Retention, Access Management and Audit
      Management moved OUT to their owning capabilities and shown as dependencies.

    python scripts/fabric_capability_map_v1_4.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PHASE = {"mvp": ("#ececec", "#8c8c8c"), "transitional": ("#f5d78e", "#c9950c"), "target": ("#f2a39c", "#c0392b")}
REL = {  # relationship -> (fill, edge, label)
    "uplift": ("#cfe0f7", "#2b6cb0", "UPLIFT — built by the initiative"),
    "consume": ("#d7ecd9", "#2f855a", "CONSUME — estate capability, never built (principle 10)"),
    "change": ("#f5d78e", "#c9950c", "OPERATING-MODEL CHANGE — adoption action, Gate A"),
}
NEW = "#2b6cb0"
GHOST = "#9a9a9a"


def box(ax, H, x, y, w, h, fc, ec, lw=1.6, ls="-", r=1.2):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, text, k=0.98):
    return min(fs, fs * (w - 2.4) / (k * len(text)))


# ------------------------------------------------------------------ view (a): enterprise overlay
def overlay(out: Path) -> None:
    W, H = 192.0, 113.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "Initiative overlay v1.5a — capabilities the Documentation Fabric touches: uplifted, consumed, changed",
            ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    ax.text(W / 2, H - 6.6, "BIZBOK initiative-to-capability cross-mapping · names are BIZBOK generic capabilities where one exists; † = not a BIZBOK generic "
            "(DAMA / ISO 27001 / CAFÉ idiom) · anchor every L1/L2 to DOH's enterprise map before governance review",
            ha="center", va="center", fontsize=11, color="#777", style="italic")

    # L1 groups: (title, [(L2 name, relationship, evidence line 1, evidence line 2)])
    L1S = [
        ("Information Management", [
            ("Knowledge Management", "uplift", "The build core — see v1.4b for the L3–L5 drill-down", "FR-1…FR-12 · catalog, graph, synthesis, gate, currency"),
            ("Document & Content Management", "consume", "Drafts, versions, templates live in SharePoint", "FR-4, FR-7 · principle 2: content stays where it lives"),
            ("Records Management", "consume", "Retention & disposition are Purview's", "NFR-4 · target-phase disposition automation"),
            ("Metadata & Reference Data Mgmt †", "consume", "Owner map and type templates are SharePoint lists", "FR-3, NFR-3 · owner/label resolved deterministically"),
        ]),
        ("Strategy Management", [
            ("Decision Management", "change", "ADRs become a managed artifact class — the MVP slice", "§1, §5.6 · decision log from day zero (ADR-001…)"),
            ("Architecture Management †", "change", "EA repository linked to work items; drawings enter it", "§2.2 · governed island today · rung-1/2 yield spike"),
        ]),
        ("Work Management", [
            ("Work Item Management", "change", "Drive delivery on ADO: all disciplines, attach-at-creation", "§5.3 operating decision · §5.9 · hygiene audit before Gate B"),
        ]),
        ("Human Resource Management", [
            ("Competency Management", "change", "Steward: a new role · owner: a new duty", "§5.8 (5) · steward RACI is an inception deliverable"),
        ]),
        ("Policy Management", [
            ("Identity & Access Management †", "consume", "Entra identity, Purview labels, DLP — pass-through only", "NFR-3, NFR-4, NFR-8 · the fabric is never a policy engine"),
        ]),
        ("Governance, Risk & Compliance †", [
            ("Audit Management", "consume", "Purview audit is authoritative; the fabric emits events", "NFR-4 · full trail of synthesis, approval, propagation"),
        ]),
        ("Message Management", [
            ("Message Delivery", "consume", "Teams delivers the cards, digests and bot messages", "FR-6, FR-8 · the gate is a Teams surface, not a fabric one"),
        ]),
        ("Technology & AI Management †", [
            ("AI Platform & Agent Management †", "consume", "AI Hub Gateway governs every model call; agents enter via CAFÉ intake", "NFR-1, FR-9, Annex C/D · G06 + G09 guardrails inherited"),
        ]),
    ]

    m, pad, gap = 2.2, 2.0, 2.4
    CW, CH = 44.0, 15.6  # chip size
    # place L1 boxes in a flowing grid: Information Mgmt spans full width; the rest 4 per row
    y = 10.4
    def l1box(x, y, w, title, chips, ncols):
        rows = -(-len(chips) // ncols)
        h = pad + 4.6 + rows * CH + (rows - 1) * 1.6 + pad
        box(ax, H, x, y, w, h, "white", "#444", 1.8, r=1.6)
        ax.text(x + 2.2, H - y - 2.8, f"L1 · {title}", ha="left", va="center", fontsize=13, fontweight="bold", color="#222")
        cw = (w - 2 * pad - gap * (ncols - 1)) / ncols
        for i, (name, rel, e1, e2) in enumerate(chips):
            cx = x + pad + (i % ncols) * (cw + gap)
            cy = y + pad + 4.6 + (i // ncols) * (CH + 1.6)
            fc, ec, _ = REL[rel]
            box(ax, H, cx, cy, cw, CH, fc, ec, 2.0 if rel == "uplift" else 1.6)
            ax.text(cx + cw / 2, H - cy - 2.9, name, ha="center", va="center", fontsize=fit(12.5, cw, name), fontweight="bold", color="#222")
            ax.text(cx + cw / 2, H - cy - 5.6, "L2 · " + rel.upper(), ha="center", va="center", fontsize=9, color=ec, fontweight="bold")
            ax.plot([cx + 2, cx + cw - 2], [H - cy - 7.0] * 2, color=ec, lw=0.6, alpha=0.6)
            ax.text(cx + cw / 2, H - cy - 9.3, e1, ha="center", va="center", fontsize=fit(10, cw, e1, 0.74), color="#333")
            ax.text(cx + cw / 2, H - cy - 12.4, e2, ha="center", va="center", fontsize=fit(9.5, cw, e2, 0.72), color="#666")
        return h

    h = l1box(m, y, W - 2 * m, *L1S[0], ncols=4)
    y += h + gap
    rest = L1S[1:]
    # row 2: Strategy (2 chips) + Work (1) + Human capital (1)  -> widths 2:1:1
    unit = (W - 2 * m - 2 * gap) / 4
    x = m
    for (title, chips), span in zip(rest[:3], (2, 1, 1)):
        w = unit * span + gap * (span - 1)
        h = l1box(x, y, w, title, chips, ncols=span)
        x += w + gap
    y += h + gap
    x = m
    for (title, chips) in rest[3:]:
        h = l1box(x, y, unit, title, chips, ncols=1)
        x += unit + gap
    y += h + gap

    # legend + reading rule
    box(ax, H, m, y, W - 2 * m, 15.0, "#fafafa", "#999", 1.4, ls=(0, (2, 2)), r=1.6)
    lx = m + 2.6
    for rel in ("uplift", "consume", "change"):
        fc, ec, label = REL[rel]
        box(ax, H, lx, y + 2.0, 3.4, 2.6, fc, ec, 1.6, r=0.6)
        ax.text(lx + 4.6, H - y - 3.3, label, ha="left", va="center", fontsize=10.5, color="#222")
        lx += 4.6 + 0.8 * len(label) + 7
    lines = [
        "Reading rule — UPLIFT is the only build scope · CONSUME is used as the estate ships it and never rebuilt (quarterly estate review) · "
        "CHANGE is an operating-model decision on the Gate A checklist.",
        "Teams and the AI gateway are surfaces the initiative uses, so they are CONSUME — a channel is a role, not a fourth relationship.",
        "KM drill-down (L3–L5) is unchanged from v1.4b. Since v1.3: Records Retention → Records Management · Access Management → Identity & Access · "
        "Audit Management → Governance, Risk & Compliance.",
    ]
    for i, t in enumerate(lines):
        ax.text(m + 2.6, H - y - 7.2 - 2.5 * i, t, ha="left", va="center", fontsize=10.5, color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)




if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    overlay(d / "capability-map-v1.5a-enterprise-overlay.png")
