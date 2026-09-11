"""Documentation Fabric capability map v1.4 — two views.

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
    "channel": ("#e6dcf5", "#6b46c1", "CHANNEL — surface the initiative delivers through"),
}
NEW = "#2b6cb0"
GHOST = "#9a9a9a"


def box(ax, H, x, y, w, h, fc, ec, lw=1.6, ls="-", r=1.2):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, text, k=0.98):
    return min(fs, fs * (w - 2.4) / (k * len(text)))


# ------------------------------------------------------------------ view (a): enterprise overlay
def overlay(out: Path) -> None:
    W, H = 192.0, 110.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "Initiative overlay v1.4a — capabilities the Documentation Fabric touches, by relationship",
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
            ("Message Delivery", "channel", "Teams adaptive cards, digests, tracker bot", "FR-6, FR-8 · one-touch owner gate · timer escalation"),
        ]),
        ("Technology & AI Management †", [
            ("AI Platform & Agent Management †", "channel", "AI Hub Gateway, CAFÉ intake, agent landscape (MCP door)", "NFR-1, FR-9, Annex C/D · G06 + G09 guardrails"),
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
    box(ax, H, m, y, W - 2 * m, 12.4, "#fafafa", "#999", 1.4, ls=(0, (2, 2)), r=1.6)
    lx = m + 2.6
    for rel in ("uplift", "consume", "change", "channel"):
        fc, ec, label = REL[rel]
        box(ax, H, lx, y + 2.0, 3.4, 2.6, fc, ec, 1.6, r=0.6)
        ax.text(lx + 4.6, H - y - 3.3, label, ha="left", va="center", fontsize=10.5, color="#222")
        lx += 4.6 + 0.8 * len(label) + 7
    ax.text(m + 2.6, H - y - 7.4, "Reading rule — a CONSUME cell is a place the initiative must not build (quarterly estate review retires any custom duplicate); "
            "a CHANGE cell is an adoption action on the Gate A checklist; UPLIFT is the only build scope.",
            ha="left", va="center", fontsize=10.5, color="#444")
    ax.text(m + 2.6, H - y - 10.2, "Moved out of KM since v1.3: Records Retention → Records Management · Access Management → Identity & Access Management · "
            "Audit Management → Governance, Risk & Compliance. KM keeps only what is knowledge-specific.",
            ha="left", va="center", fontsize=10.5, color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


# ------------------------------------------------------------------ view (b): KM drill-down
def drilldown(out: Path) -> None:
    W, H = 192.0, 166.0
    CH, L2PAD, L2HDR, GAP = 18.6, 1.6, 3.2, 1.4
    GH = L2PAD + L2HDR + CH + L2PAD
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    def chip(x, y, w, title, num, subs, phase, new=False):
        fill, edge = PHASE[phase]
        box(ax, H, x, y, w, CH, fill, NEW if new else edge, 2.2 if new else 1.6, (0, (5, 2.5)) if new else "-")
        ax.text(x + w / 2, H - y - 2.6, title, ha="center", va="center", fontsize=fit(12.5, w, title), fontweight="bold", color="#222")
        ax.text(x + w / 2, H - y - 5.0, num, ha="center", va="center", fontsize=9, color="#777")
        ax.plot([x + 2.0, x + w - 2.0], [H - y - 6.3] * 2, color=edge, lw=0.6, alpha=0.6)
        for i, s in enumerate(subs):
            ax.text(x + 2.2, H - y - 8.2 - 2.45 * i, "· " + s, ha="left", va="center", fontsize=9.6, color="#444")

    def ghost(x, y, w, title, owner, subs):
        box(ax, H, x, y, w, CH, "white", GHOST, 1.4, (0, (3, 2)))
        ax.text(x + w / 2, H - y - 2.6, title, ha="center", va="center", fontsize=fit(12.5, w, title), fontweight="bold", color=GHOST)
        ax.text(x + w / 2, H - y - 5.0, "consumed from", ha="center", va="center", fontsize=9, color=GHOST, style="italic")
        ax.text(x + w / 2, H - y - 7.6, owner, ha="center", va="center", fontsize=fit(10.5, w, owner, 0.8), fontweight="bold", color="#2f855a")
        ax.plot([x + 2.0, x + w - 2.0], [H - y - 9.2] * 2, color=GHOST, lw=0.6, alpha=0.6)
        for i, s in enumerate(subs):
            ax.text(x + 2.2, H - y - 11.0 - 2.45 * i, "· " + s, ha="left", va="center", fontsize=9.6, color="#777")

    def group(x, y, w, num, title, gloss, chips):
        box(ax, H, x, y, w, GH, "white", "#b5b5b5", 1.2)
        ax.text(x + 1.6, H - y - 1.9, f"{num}  {title}", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
        ax.text(x + w - 1.6, H - y - 1.9, f"L3 · {gloss}", ha="right", va="center", fontsize=10, color="#777", style="italic")
        n = len(chips)
        cw = (w - 2 * L2PAD - GAP * (n - 1)) / n
        for i, c in enumerate(chips):
            cx, cy = x + L2PAD + i * (cw + GAP), y + L2PAD + L2HDR
            if c[0] == "ghost":
                ghost(cx, cy, cw, *c[1:])
            else:
                chip(cx, cy, cw, *c)

    ax.text(W / 2, H - 3.0, "Capability map v1.4b — Knowledge Management (L2) to L5 · estate dependencies shown, not owned",
            ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    m, pad = 2.2, 2.2
    y = 6.6
    box(ax, H, m, y, W - 2 * m, 8.4, "#f7f7f7", "#999", 1.4, (0, (3, 2)), 1.6)
    ax.text(m + 2.6, H - y - 2.4, "L1 · Information Management  (enterprise context — see v1.4a for every capability the initiative touches)",
            ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
    sx = m + 2.6
    for s in ["Data Management", "Document & Content Management", "Records Management", "Knowledge Management  ◀ this map"]:
        this = s.startswith("Knowledge"); ww = 0.86 * len(s) + 3.6
        box(ax, H, sx, y + 4.4, ww, 3.0, "white" if this else "#efefef", "#444" if this else "#bbb", 1.6 if this else 1.0, r=0.8)
        ax.text(sx + ww / 2, H - y - 5.9, s, ha="center", va="center", fontsize=10.5, fontweight="bold" if this else "normal", color="#222" if this else "#888")
        sx += ww + 2.0

    y0 = y + 8.4 + 2.0
    inner = W - 2 * m - 2 * pad
    h1 = pad + 5.4 + 4 * GH + 3 * 1.6 + pad
    box(ax, H, m, y0, W - 2 * m, h1, "white", "#444", 2.0, r=1.6)
    ax.text(m + 2.6, H - y0 - 3.2, "L2 · Knowledge Management", ha="left", va="center", fontsize=16, fontweight="bold", color="#222")
    ax.text(W - m - 2.6, H - y0 - 3.2, "L3 groups follow ISO 30401 §4.4 · noun phrases per BIZBOK · chip = L4 · lines = L5 · dashed grey = consumed, not owned",
            ha="right", va="center", fontsize=10.5, color="#777", style="italic")
    x0 = m + pad; ry = y0 + pad + 5.4
    unit = (inner - 1.6) / 6
    group(x0, ry, unit * 2, "1", "Knowledge Organisation", "define meaning and identity", [
        ("Vocabulary Management", "1.1 · MVP", ["Ontology Management", "Concept Scheme Management", "Vocabulary Alignment", "Concept Lifecycle (propose · deprecate)"], "mvp"),
        ("Catalog Management", "1.2 · MVP", ["Artifact Identification (one IRI)", "Pointer Management (never content)", "Lifecycle State Management"], "mvp")])
    group(x0 + unit * 2 + 1.6, ry, unit * 4, "2", "Knowledge Production", "create managed artifacts", [
        ("Content Synthesis", "2.1 · MVP", ["Template Management", "Draft Generation", "Re-draft on Source Change"], "mvp"),
        ("Knowledge Classification", "2.2 · MVP", ["Type Classification", "Owner Resolution", "Sensitivity Resolution", "Concept Linking"], "mvp"),
        ("Version Management", "2.3 · MVP", ["Baseline Management", "Source Version Confirmation"], "mvp"),
        ("Traceability Management", "2.4 · MVP", ["Delivery Association (ladder)", "Reference Extraction", "Association Confirmation", "Orphan Management"], "mvp")])
    ry += GH + 1.6
    group(x0, ry, inner, "3", "Knowledge Governance", "decide what is trusted", [
        ("Ownership & Stewardship", "3.1 · MVP", ["Owner Assignment", "Steward Assignment", "Steward Queue Management"], "mvp"),
        ("Knowledge Review", "3.2 · MVP", ["Owner Approval", "Rework", "Escalation"], "mvp"),
        ("Duplicate Management", "3.3 · Transitional", ["Overlap Detection", "Merge Adjudication"], "transitional"),
        ("ghost", "Access Management", "Identity & Access Management", ["Label Pass-through", "Principal Scoping (parity)"]),
        ("ghost", "Audit Management", "Governance, Risk & Compliance", ["Event Logging", "Audit Query"]),
        ("ghost", "Records Retention", "Records Management", ["Retention Policy Application", "Disposition"])])
    ry += GH + 1.6
    group(x0, ry, inner, "4", "Knowledge Discovery", "find and reuse what exists", [
        ("Knowledge Retrieval", "4.1 · MVP", ["Semantic Search", "Catalog & Graph Traversal", "Agent Tool Access (MCP)"], "mvp"),
        ("Knowledge Recommendation", "4.2 · Transitional", ["Reuse Suggestion", "Related-artifact Joins"], "transitional"),
        ("Expertise Identification", "4.3 · Target", ["Authorship Analysis", "Ownership Analysis"], "target")])
    ry += GH + 1.6
    group(x0, ry, inner, "5", "Knowledge Currency", "keep published knowledge current", [
        ("Change Detection", "5.1 · MVP", ["Event Capture", "Event Filtering (allow-list)", "Loop Guard"], "mvp"),
        ("Change Impact Analysis", "5.2 · Transitional", ["Trusted-edge Traversal", "Affected-set Determination", "Depth Bounding"], "transitional"),
        ("Subscription Management", "5.3 · Transitional", ["Follow", "Notification", "Digest"], "transitional"),
        ("Republication", "5.4 · Transitional", ["Projection Rebuild", "Index Refresh"], "transitional"),
        ("Catalog Reconciliation", "5.5 · Transitional", ["Drift Detection", "Drift Resolution"], "transitional"),
        ("Remediation Management", "5.6 · Target", ["Fix Drafting", "Native-review Filing", "Whitelisted Auto-apply"], "target")])

    py = y0 + h1 + 2.0; ph = 15.0
    box(ax, H, m, py, W - 2 * m, ph, "#fafafa", "#999", 1.4, (0, (2, 2)), 1.6)
    ax.text(m + 2.6, H - py - 2.4, "Constraining principles  (apply to every cell — constraints, not capabilities)", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#444")
    for i, t in enumerate([
        "Metadata-only fabric — no document content in any fabric store; enforced as a CI fitness function",
        "The source decides access, at read time — labels pass through; the fabric is never a policy engine",
        "People and agents are peers — same interfaces, label trimming, principal identity and audit",
        "Edges are captured, never guessed — impact analysis is served only over constructed, extracted or confirmed edges"]):
        ax.text(m + 3.2, H - py - 5.0 - 2.35 * i, "•  " + t, ha="left", va="center", fontsize=10.5, color="#444")
    ly = py + ph + 2.4; lx = 8
    for p, label in [("mvp", "MVP — ADR thin slice · new items only"), ("transitional", "+ Transitional — trace graph · dedup · currency loop"), ("target", "+ Target — corpus-scale effects")]:
        fill, edge = PHASE[p]
        box(ax, H, lx, ly, 3.4, 2.6, fill, edge, 1.6, r=0.6)
        ax.text(lx + 4.6, H - ly - 1.9, label, ha="left", va="center", fontsize=12, color="#222")
        lx += 4.6 + 0.8 * len(label) + 8
    box(ax, H, lx, ly, 3.4, 2.6, "white", GHOST, 1.4, (0, (3, 2)), r=0.6)
    ax.text(lx + 4.6, H - ly - 1.9, "consumed from a sibling capability — not in scope", ha="left", va="center", fontsize=12, color="#222")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    overlay(d / "capability-map-v1.4a-enterprise-overlay.png")
    drilldown(d / "capability-map-v1.4b-km-drilldown.png")
