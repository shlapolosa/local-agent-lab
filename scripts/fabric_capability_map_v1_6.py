"""Documentation Fabric maps v1.6 — capability and technology landscape kept apart.

  1.6a  enterprise overlay, PURE capability: name · relationship · capability definition · requirement refs.
  1.6b  Knowledge Management drill-down, PURE capability: L3 groups → L4 boxes → L5 boxes. No products,
        no mechanisms, no components. Consumed sibling capabilities shown dashed.
  1.6c  technology landscape, enterprise: the same L1/L2 grid, each cell = what REALISES it today or in
        the target design (Annex D / Figure 8), coloured by delivery mode.
  1.6d  technology landscape, KM drill-down: the same L3/L4 grid, each L4 = the components that realise it,
        coloured by delivery mode; a GAP is a capability with no component in Annex D.
Names: BIZBOK generics where one exists († = not a BIZBOK generic).

    python scripts/fabric_capability_map_v1_6.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PHASE = {"mvp": ("#ececec", "#8c8c8c"), "transitional": ("#f5d78e", "#c9950c"), "target": ("#f2a39c", "#c0392b")}
REL = {"uplift": ("#cfe0f7", "#2b6cb0", "UPLIFT — built by the initiative"),
       "consume": ("#d7ecd9", "#2f855a", "CONSUME — estate capability, never built (principle 10)"),
       "change": ("#f5d78e", "#c9950c", "OPERATING-MODEL CHANGE — adoption action, Gate A")}
MODE = {"standard": ("#d7ecd9", "#2f855a", "STANDARD — estate platform, configured"),
        "lowcode": ("#f5d78e", "#c9950c", "LOW CODE — Power Platform / Copilot Studio"),
        "procode": ("#cfe0f7", "#2b6cb0", "PRO CODE — built, tested, CI/CD"),
        "org": ("#eeeeee", "#8c8c8c", "ORGANISATIONAL — no system"),
        "gap": ("#fde8e6", "#c0392b", "GAP — no component in Annex D; bake-off")}
GHOST = "#9a9a9a"


def box(ax, H, x, y, w, h, fc, ec, lw=1.6, ls="-", r=1.2):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, text, k=0.98):
    return min(fs, fs * (w - 2.4) / (k * max(1, len(text))))


def wrap(text, w, k=0.72):
    import textwrap
    return textwrap.wrap(text, width=max(10, int((w - 2.0) / k)))


# ======================================================================= DATA
# ---- enterprise (a + c) : L1 -> [(L2 name, relationship, capability definition, requirement refs)]
L1S = [
    ("Information Management", [
        ("Knowledge Management", "uplift", "Organise, produce, govern, discover and keep current the organisation's knowledge", "FR-1…FR-12 · the build core · drill-down in 1.6b"),
        ("Document & Content Management", "consume", "Author, store, version and publish documents", "FR-4, FR-7 · principle 2: content stays where it lives"),
        ("Records Management", "consume", "Retain and dispose of records according to policy", "NFR-4 · disposition automation at Target"),
        ("Metadata & Reference Data Mgmt †", "consume", "Maintain authoritative reference data: owners, document types", "FR-3, NFR-3 · owner and label are looked up, never guessed"),
    ]),
    ("Strategy Management", [
        ("Decision Management", "change", "Record, trace and revisit decisions", "§1, §5.6 · decision records are the MVP artifact class"),
        ("Architecture Management †", "change", "Maintain the architecture repository and its models", "§2.2 · repository linked to work items; drawings enter it"),
    ]),
    ("Work Management", [
        ("Work Item Management", "change", "Define, assign and track units of delivery work across all disciplines", "§5.3 operating decision · §5.9 · attach-at-creation rule"),
    ]),
    ("Human Resource Management", [
        ("Competency Management", "change", "Define roles and duties and develop the people who hold them", "§5.8 (5) · steward is a new role, owner a new duty"),
    ]),
    ("Policy Management", [
        ("Identity & Access Management †", "consume", "Identify principals and decide what each may access", "NFR-3, NFR-4, NFR-8 · the fabric never decides access"),
    ]),
    ("Governance, Risk & Compliance †", [
        ("Audit Management", "consume", "Record and examine who did what, when, to which artifact", "NFR-4 · synthesis, approval, propagation all logged"),
    ]),
    ("Message Management", [
        ("Message Delivery", "consume", "Deliver messages to people and collect their responses", "FR-6, FR-8 · one-touch owner gate, digests"),
    ]),
    ("Technology Management", [
        ("AI Agent Management †", "consume", "Admit, govern and operate automated agents", "NFR-1, FR-9, Annex C · guardrails inherited"),
    ]),
]
# technology realisation per L2 (1.6c): mode, components, source
TECH_L2 = {
    "Knowledge Management": ("procode", ["Composed build (Annex D, §5.5)", "Functions · Cosmos DB · AI Search", "Service Bus · Claude via AI Hub Gateway", "detail in 1.6d"], "Annex D · Fig. 8"),
    "Document & Content Management": ("standard", ["SharePoint Online (docs, drafts, versions)", "SharePoint Premium classifiers (pilot)"], "D.1, D.2"),
    "Records Management": ("standard", ["Microsoft Purview retention & disposition"], "D.2"),
    "Metadata & Reference Data Mgmt †": ("standard", ["SharePoint lists: owner map, type templates"], "D.2"),
    "Decision Management": ("standard", ["ADR documents in SharePoint, keyed to ADO", "decision log = ADR-001…"], "§5.8"),
    "Architecture Management †": ("standard", ["EA repository (ADOIT / Archi)", "Visio · draw.io (link-only today)"], "§2.2, Fig. 5"),
    "Work Item Management": ("standard", ["Azure DevOps Boards (work items, hooks, wiki)"], "Fig. 4, §5.3"),
    "Competency Management": ("org", ["Steward RACI, owner duty — no system", "baselines in Power BI (metrics)"], "§5.8 (5)"),
    "Identity & Access Management †": ("standard", ["Entra ID · Purview sensitivity labels · DLP"], "NFR-4, Fig. 8"),
    "Audit Management": ("standard", ["Purview audit · fabric event log (Service Bus)"], "D.2"),
    "Message Delivery": ("lowcode", ["Teams adaptive cards · Power Automate flows", "tracker bot · pro-code Teams bot as fallback"], "D.2, §5.7"),
    "AI Agent Management †": ("standard", ["AI Hub Gateway (APIM) in the AI Landing Zone", "CAFÉ intake · MCP facade over search API"], "Annex C, D.2"),
}

# ---- KM drill-down (b + d): (num, title, gloss, [(L4 name, phase, [L5...], consumed_from | None)])
GROUPS = [
    ("1", "Knowledge Organisation", "define meaning and identity", [
        ("Vocabulary Management", "mvp", ["Ontology Management", "Concept Scheme Management", "Vocabulary Alignment", "Concept Lifecycle Management"], None),
        ("Catalog Management", "mvp", ["Artifact Identification", "Location Reference Management", "Lifecycle State Management"], None)]),
    ("2", "Knowledge Production", "create managed artifacts", [
        ("Content Synthesis", "mvp", ["Template Management", "Draft Generation", "Draft Regeneration"], None),
        ("Knowledge Classification", "mvp", ["Type Classification", "Owner Resolution", "Sensitivity Resolution", "Concept Linking"], None),
        ("Version Management", "mvp", ["Baseline Management", "Version Confirmation"], None),
        ("Traceability Management", "mvp", ["Delivery Association", "Reference Extraction", "Association Confirmation", "Orphan Management"], None)]),
    ("3", "Knowledge Governance", "decide what is trusted", [
        ("Ownership & Stewardship", "mvp", ["Owner Assignment", "Steward Assignment", "Steward Work Queue Management"], None),
        ("Knowledge Review", "mvp", ["Approval", "Rework Handling", "Review Escalation"], None),
        ("Duplicate Management", "transitional", ["Overlap Detection", "Merge Adjudication"], None),
        ("Access Management", "mvp", ["Sensitivity Label Inheritance", "Principal Scoping"], "Identity & Access Management"),
        ("Audit Management", "mvp", ["Event Recording", "Audit Query"], "Governance, Risk & Compliance"),
        ("Records Retention", "target", ["Retention Policy Application", "Disposition"], "Records Management")]),
    ("4", "Knowledge Discovery", "find and reuse what exists", [
        ("Knowledge Retrieval", "mvp", ["Knowledge Search", "Relationship Navigation"], None),
        ("Knowledge Recommendation", "transitional", ["Reuse Suggestion", "Related Artifact Retrieval"], None),
        ("Expertise Identification", "target", ["Authorship Analysis", "Ownership Analysis"], None)]),
    ("5", "Knowledge Currency", "keep published knowledge current", [
        ("Change Detection", "mvp", ["Event Capture", "Event Filtering", "Change Attribution"], None),
        ("Change Impact Analysis", "transitional", ["Impact Chain Determination", "Affected Artifact Identification", "Impact Scope Bounding"], None),
        ("Subscription Management", "transitional", ["Following", "Notification", "Digest Compilation"], None),
        ("Republication", "transitional", ["Projection Regeneration", "Index Regeneration"], None),
        ("Catalog Reconciliation", "transitional", ["Drift Detection", "Drift Resolution"], None),
        ("Remediation Management", "target", ["Correction Drafting", "Correction Proposal Filing", "Mechanical Correction Application"], None)]),
]
# technology realisation per L4 (1.6d): mode, components, Annex D / figure ref
TECH_L4 = {
    "Vocabulary Management": ("gap", ["No component in Annex D", "Candidates: SharePoint term store (Managed Metadata), AI Search synonym maps, custom SKOS / ontology store"], "bake-off"),
    "Catalog Management": ("procode", ["Catalog of ADO-keyed pointers: Cosmos DB", "Identifier minting in the pipeline Functions"], "D.2"),
    "Content Synthesis": ("procode", ["Synthesis service: Functions + Claude via AI Hub Gateway (AI component, G09)", "Type templates: SharePoint lists"], "D.1"),
    "Knowledge Classification": ("procode", ["Classification assist: Functions + LLM (AI)", "SharePoint Premium classifiers (buy-lite pilot)", "Owner map: SharePoint list · label: Purview, inherited"], "D.1, D.2"),
    "Version Management": ("procode", ["Baseline & sync orchestration: Functions", "The SharePoint version is the confirmed version"], "D.2"),
    "Traceability Management": ("procode", ["Traceability graph: Cosmos DB (store confirmed by prototype ADR)", "Reference extraction in the receivers", "One-tap capture card: Teams"], "D.2, §5.7"),
    "Ownership & Stewardship": ("lowcode", ["Owner map: SharePoint list", "Governance console: Power Apps (steward home)"], "D.2"),
    "Knowledge Review": ("lowcode", ["Review & escalation flows: Power Automate", "Owner review cards: Teams adaptive cards", "Fallback: pro-code Teams bot, same card"], "D.2, §5.7"),
    "Duplicate Management": ("procode", ["Dup detection: Functions + AI Search vector query (AI)", "Adjudication in the governance console"], "D.1"),
    "Access Management": ("standard", ["Entra ID · Purview sensitivity labels (pass-through)"], "consumed"),
    "Audit Management": ("standard", ["Purview audit · fabric event log on Service Bus"], "consumed"),
    "Records Retention": ("standard", ["Purview retention & disposition"], "consumed"),
    "Knowledge Retrieval": ("procode", ["Search & discovery API fronting AI Search (hybrid + vector) with catalog joins", "Agent door: MCP server · M365 Copilot · permission-aware Claude"], "D.1, D.2"),
    "Knowledge Recommendation": ("lowcode", ["Discovery agent: Copilot Studio / declarative agent over the search API and catalog traversal"], "D.1"),
    "Expertise Identification": ("procode", ["Expertise query service (thin) over catalog metadata", "Work IQ is the estate-watch candidate"], "D.2, §4.2"),
    "Change Detection": ("procode", ["Webhook receivers: Functions (allow-list, normalise)", "Graph change notifications · ADO service hooks", "Service Bus topics"], "D.2"),
    "Change Impact Analysis": ("procode", ["Impact analysis service: deterministic graph traversal on the ADO key, no model"], "D.2"),
    "Subscription Management": ("lowcode", ["Subscription store: Service Bus (pro-code)", "Tracker bot, follow + digests: Power Automate / Teams"], "D.2"),
    "Republication": ("procode", ["Baseline & sync: Functions", "ADO wiki projections (generated) · AI Search index"], "D.2"),
    "Catalog Reconciliation": ("procode", ["Reconciliation sweep: Functions + Monitor, catalog vs source drift"], "D.2"),
    "Remediation Management": ("procode", ["Remediation agent: orchestration reusing synthesis", "Writeback adapters: Graph / ADO APIs, draft mode"], "D.1, D.2"),
}


# ======================================================================= ENTERPRISE (a, c)
def enterprise(out: Path, tech: bool) -> None:
    W, H = 192.0, 116.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    if tech:
        ax.text(W / 2, H - 3.0, "Technology landscape v1.6c — what realises each capability the initiative touches", ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
        ax.text(W / 2, H - 6.6, "Same grid as 1.6a · cell = realising platform or component, coloured by delivery mode (Annex D / Figure 8) · the KM cell is a composed build — see 1.6d", ha="center", va="center", fontsize=11, color="#777", style="italic")
    else:
        ax.text(W / 2, H - 3.0, "Capability overlay v1.6a — capabilities the Documentation Fabric touches: uplifted, consumed, changed", ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
        ax.text(W / 2, H - 6.6, "Pure capability view — no products, no components · BIZBOK generics where one exists († = not a BIZBOK generic) · anchor L1/L2 to DOH's enterprise map", ha="center", va="center", fontsize=11, color="#777", style="italic")

    m, pad, gap = 2.2, 2.0, 2.4
    CH = 16.4

    def cell(cx, cy, cw, name, rel, definition, refs):
        if tech:
            mode, comps, src = TECH_L2[name]
            fc, ec, _ = MODE[mode]
            box(ax, H, cx, cy, cw, CH, fc, ec, 1.6, (0, (3, 2)) if mode == "gap" else "-")
            ax.text(cx + cw / 2, H - cy - 2.9, name, ha="center", va="center", fontsize=fit(12.5, cw, name), fontweight="bold", color="#222")
            ax.text(cx + cw / 2, H - cy - 5.6, mode.upper().replace("LOWCODE", "LOW CODE").replace("PROCODE", "PRO CODE") + " · " + src, ha="center", va="center", fontsize=9, color=ec, fontweight="bold")
            ax.plot([cx + 2, cx + cw - 2], [H - cy - 7.0] * 2, color=ec, lw=0.6, alpha=0.6)
            for i, c in enumerate(comps[:4]):
                ax.text(cx + 2.0, H - cy - 9.0 - 2.2 * i, "· " + c, ha="left", va="center", fontsize=fit(9.6, cw, c, 0.66), color="#333")
        else:
            fc, ec, _ = REL[rel]
            box(ax, H, cx, cy, cw, CH, fc, ec, 2.0 if rel == "uplift" else 1.6)
            ax.text(cx + cw / 2, H - cy - 2.9, name, ha="center", va="center", fontsize=fit(12.5, cw, name), fontweight="bold", color="#222")
            ax.text(cx + cw / 2, H - cy - 5.6, "L2 · " + rel.upper(), ha="center", va="center", fontsize=9, color=ec, fontweight="bold")
            ax.plot([cx + 2, cx + cw - 2], [H - cy - 7.0] * 2, color=ec, lw=0.6, alpha=0.6)
            ls = wrap(definition, cw, 0.7)[:2]
            for i, l in enumerate(ls):
                ax.text(cx + cw / 2, H - cy - 9.2 - 2.3 * i, l, ha="center", va="center", fontsize=10, color="#333")
            ax.text(cx + cw / 2, H - cy - 14.4, refs, ha="center", va="center", fontsize=fit(9.2, cw, refs, 0.68), color="#666")

    def l1box(x, y, w, title, chips, ncols):
        rows = -(-len(chips) // ncols)
        h = pad + 4.6 + rows * CH + (rows - 1) * 1.6 + pad
        box(ax, H, x, y, w, h, "white", "#444", 1.8, r=1.6)
        ax.text(x + 2.2, H - y - 2.8, f"L1 · {title}", ha="left", va="center", fontsize=13, fontweight="bold", color="#222")
        cw = (w - 2 * pad - gap * (ncols - 1)) / ncols
        for i, (name, rel, d, r) in enumerate(chips):
            cell(x + pad + (i % ncols) * (cw + gap), y + pad + 4.6 + (i // ncols) * (CH + 1.6), cw, name, rel, d, r)
        return h

    y = 10.4
    h = l1box(m, y, W - 2 * m, *L1S[0], ncols=4); y += h + gap
    unit = (W - 2 * m - 2 * gap) / 4
    x = m
    for (title, chips), span in zip(L1S[1:4], (2, 1, 1)):
        w = unit * span + gap * (span - 1)
        h = l1box(x, y, w, title, chips, ncols=span); x += w + gap
    y += h + gap; x = m
    for (title, chips) in L1S[4:]:
        h = l1box(x, y, unit, title, chips, ncols=1); x += unit + gap
    y += h + gap

    box(ax, H, m, y, W - 2 * m, 12.6, "#fafafa", "#999", 1.4, ls=(0, (2, 2)), r=1.6)
    lx = m + 2.6
    legend = MODE if tech else REL
    for key, (fc, ec, label) in legend.items():
        box(ax, H, lx, y + 2.0, 3.4, 2.6, fc, ec, 1.6, (0, (3, 2)) if key == "gap" else "-", r=0.6)
        ax.text(lx + 4.6, H - y - 3.3, label, ha="left", va="center", fontsize=10, color="#222")
        lx += 4.6 + 0.74 * len(label) + 5
    if tech:
        ax.text(m + 2.6, H - y - 7.4, "Reading rule — a STANDARD or LOW CODE cell is estate; PRO CODE is the build; the bake-off question for the KM cell is whether one product covers the L4 set in 1.6d or a composition is required.", ha="left", va="center", fontsize=10.2, color="#444")
        ax.text(m + 2.6, H - y - 10.2, "Technology names appear ONLY on this view and on 1.6d. The capability views (1.6a, 1.6b) stay product-free so the bake-off can replace any cell here without touching them.", ha="left", va="center", fontsize=10.2, color="#444")
    else:
        ax.text(m + 2.6, H - y - 7.4, "Reading rule — UPLIFT is the only build scope · CONSUME is used as the estate ships it, never rebuilt (quarterly estate review) · CHANGE is an operating-model decision on the Gate A checklist.", ha="left", va="center", fontsize=10.2, color="#444")
        ax.text(m + 2.6, H - y - 10.2, "Each cell carries the capability DEFINITION (what the organisation can do) and the requirements that evidence it. Realisation is on 1.6c; the KM drill-down is 1.6b.", ha="left", va="center", fontsize=10.2, color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


# ======================================================================= KM DRILL-DOWN (b, d)
def drilldown(out: Path, tech: bool) -> None:
    W = 192.0
    m, pad, L2PAD, L2HDR, GAP = 2.2, 2.2, 1.6, 3.2, 1.4
    L4HDR, L5H, L5GAP = 7.0, 3.3, 0.7
    inner = W - 2 * m - 2 * pad

    LINE = 2.35

    def cw_for(row, g):  # chip width for group g in a row
        if len(row) == 2:
            unit = (inner - 1.6) / 6
            gw = unit * 2 if g is row[0] else unit * 4
        else:
            gw = inner
        n = len(g[3])
        return (gw - 2 * L2PAD - GAP * (n - 1)) / n

    def tech_lines(name, w):
        out = []
        for c in TECH_L4[name][1]:
            out += wrap(c, w - 2.4, 0.66)
        return out

    def l4h(row_groups):  # L4 box height for a row
        h = 0
        for g in row_groups:
            w = cw_for(row_groups, g)
            for (name, phase, l5s, owner) in g[3]:
                if tech:
                    h = max(h, L4HDR + len(tech_lines(name, w)) * LINE + 1.4)
                else:
                    h = max(h, L4HDR + len(l5s) * (L5H + L5GAP) + 1.0)
        return h

    rows = [[GROUPS[0], GROUPS[1]], [GROUPS[2]], [GROUPS[3]], [GROUPS[4]]]
    row_h = [l4h(r) for r in rows]
    GHs = [L2PAD + L2HDR + h + L2PAD for h in row_h]
    h1 = pad + 5.4 + sum(GHs) + (len(rows) - 1) * 1.6 + pad
    H = 6.6 + 8.4 + 2.0 + h1 + 2.0 + 15.0 + 2.4 + 5.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    def l4box(x, y, w, h, name, phase, l5s, owner):
        if tech:
            mode, comps, src = TECH_L4[name]
            fc, ec, _ = MODE[mode]
            box(ax, H, x, y, w, h, fc, ec, 1.6, (0, (4, 2)) if mode == "gap" else "-")
            ax.text(x + w / 2, H - y - 2.6, name, ha="center", va="center", fontsize=fit(12.5, w, name), fontweight="bold", color="#222")
            tag = mode.upper().replace("LOWCODE", "LOW CODE").replace("PROCODE", "PRO CODE") + " · " + src
            ax.text(x + w / 2, H - y - 5.0, tag, ha="center", va="center", fontsize=fit(9, w, tag, 0.62), color=ec, fontweight="bold")
            i = 0
            for c in comps:
                for j, line in enumerate(wrap(c, w - 2.4, 0.66)):
                    ax.text(x + 1.8, H - y - L4HDR - 1.0 - LINE * i, ("· " if j == 0 else "  ") + line, ha="left", va="center", fontsize=9.4, color="#333")
                    i += 1
            return
        ghost = owner is not None
        fill, edge = ("white", GHOST) if ghost else PHASE[phase]
        box(ax, H, x, y, w, h, fill, edge, 1.4 if ghost else 1.6, (0, (3, 2)) if ghost else "-")
        ax.text(x + w / 2, H - y - 2.6, name, ha="center", va="center", fontsize=fit(12.5, w, name), fontweight="bold", color=GHOST if ghost else "#222")
        sub = f"consumed from {owner}" if ghost else "L4 · " + {"mvp": "MVP", "transitional": "Transitional", "target": "Target"}[phase]
        ax.text(x + w / 2, H - y - 5.0, sub, ha="center", va="center", fontsize=fit(9, w, sub, 0.72), color="#2f855a" if ghost else "#777", style="italic" if ghost else "normal")
        for i, s in enumerate(l5s):
            by = y + L4HDR + i * (L5H + L5GAP)
            box(ax, H, x + 1.4, by, w - 2.8, L5H, "white", edge, 1.0, (0, (3, 2)) if ghost else "-", r=0.7)
            ax.text(x + w / 2, H - by - L5H / 2, s, ha="center", va="center", fontsize=fit(9.6, w - 2.8, s, 0.66), color=GHOST if ghost else "#333")

    def group(x, y, w, gh, l4height, num, title, gloss, l4s):
        box(ax, H, x, y, w, gh, "white", "#b5b5b5", 1.2)
        ax.text(x + 1.6, H - y - 1.9, f"{num}  {title}", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
        ax.text(x + w - 1.6, H - y - 1.9, f"L3 · {gloss}", ha="right", va="center", fontsize=10, color="#777", style="italic")
        n = len(l4s); cw = (w - 2 * L2PAD - GAP * (n - 1)) / n
        for i, c in enumerate(l4s):
            l4box(x + L2PAD + i * (cw + GAP), y + L2PAD + L2HDR, cw, l4height, *c)

    ttl = ("Technology landscape v1.6d — what realises each Knowledge Management capability (same grid as 1.6b)" if tech
           else "Capability map v1.6b — Knowledge Management (L2) to L5, pure capability · L5 as boxes")
    ax.text(W / 2, H - 3.0, ttl, ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    y = 6.6
    box(ax, H, m, y, W - 2 * m, 8.4, "#f7f7f7", "#999", 1.4, (0, (3, 2)), 1.6)
    ax.text(m + 2.6, H - y - 2.4, "L1 · Information Management  (enterprise context — 1.6a / 1.6c show every capability the initiative touches)", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#555")
    sx = m + 2.6
    for s in ["Data Management", "Document & Content Management", "Records Management", "Knowledge Management  ◀ this map"]:
        this = s.startswith("Knowledge"); ww = 0.86 * len(s) + 3.6
        box(ax, H, sx, y + 4.4, ww, 3.0, "white" if this else "#efefef", "#444" if this else "#bbb", 1.6 if this else 1.0, r=0.8)
        ax.text(sx + ww / 2, H - y - 5.9, s, ha="center", va="center", fontsize=10.5, fontweight="bold" if this else "normal", color="#222" if this else "#888")
        sx += ww + 2.0
    y0 = y + 8.4 + 2.0
    box(ax, H, m, y0, W - 2 * m, h1, "white", "#444", 2.0, r=1.6)
    ax.text(m + 2.6, H - y0 - 3.2, "L2 · Knowledge Management", ha="left", va="center", fontsize=16, fontweight="bold", color="#222")
    ax.text(W - m - 2.6, H - y0 - 3.2,
            "cell = realising components, coloured by delivery mode · dashed red = gap" if tech else
            "L3 groups per ISO 30401 §4.4 · BIZBOK noun phrases · box = L4 · nested box = L5 · dashed grey = consumed from a sibling capability",
            ha="right", va="center", fontsize=10.5, color="#777", style="italic")
    x0 = m + pad; ry = y0 + pad + 5.4
    for r, gh, lh in zip(rows, GHs, row_h):
        if len(r) == 2:
            unit = (inner - 1.6) / 6
            group(x0, ry, unit * 2, gh, lh, *r[0]); group(x0 + unit * 2 + 1.6, ry, unit * 4, gh, lh, *r[1])
        else:
            group(x0, ry, inner, gh, lh, *r[0])
        ry += gh + 1.6

    py = y0 + h1 + 2.0; ph = 15.0
    box(ax, H, m, py, W - 2 * m, ph, "#fafafa", "#999", 1.4, (0, (2, 2)), 1.6)
    if tech:
        ax.text(m + 2.6, H - py - 2.4, "Bake-off framing", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#444")
        for i, t in enumerate([
            "The uplift is the set of PRO CODE and GAP cells. The bake-off asks, per cell, whether a product covers it as shipped (moves to STANDARD), needs configuration on a platform (LOW CODE), or must be composed.",
            "Vocabulary Management has NO component in Annex D — the semantic layer's own vocabulary was never realised in the design; SharePoint term store, AI Search synonym maps and a custom ontology store are the candidates.",
            "Cells consumed from siblings (Access, Audit, Records Retention) are STANDARD by definition and are out of the bake-off.",
            "A component named here is a realisation choice, not a capability: replacing it changes this view only, never 1.6b."]):
            ax.text(m + 3.2, H - py - 5.0 - 2.35 * i, "•  " + t, ha="left", va="center", fontsize=fit(10.2, W - 2 * m - 6, t, 0.6), color="#444")
    else:
        ax.text(m + 2.6, H - py - 2.4, "Constraining principles  (apply to every cell — constraints, not capabilities)", ha="left", va="center", fontsize=12.5, fontweight="bold", color="#444")
        for i, t in enumerate([
            "Metadata-only fabric — no document content in any fabric store; enforced as a CI fitness function",
            "The source decides access, at read time — labels pass through; the fabric is never a policy engine",
            "People and agents are peers — same interfaces, label trimming, principal identity and audit",
            "Edges are captured, never guessed — impact analysis is served only over constructed, extracted or confirmed edges"]):
            ax.text(m + 3.2, H - py - 5.0 - 2.35 * i, "•  " + t, ha="left", va="center", fontsize=10.5, color="#444")
    ly = py + ph + 2.4; lx = 8
    legend = list(MODE.items()) if tech else [(k, (*PHASE[k], lbl)) for k, lbl in (("mvp", "MVP — ADR thin slice · new items only"), ("transitional", "+ Transitional — trace graph · dedup · currency loop"), ("target", "+ Target — corpus-scale effects"))]
    for key, (fc, ec, label) in legend:
        box(ax, H, lx, ly, 3.4, 2.6, fc, ec, 1.6, (0, (3, 2)) if key == "gap" else "-", r=0.6)
        ax.text(lx + 4.6, H - ly - 1.9, label, ha="left", va="center", fontsize=11, color="#222")
        lx += 4.6 + 0.74 * len(label) + 6
    if not tech:
        box(ax, H, lx, ly, 3.4, 2.6, "white", GHOST, 1.4, (0, (3, 2)), r=0.6)
        ax.text(lx + 4.6, H - ly - 1.9, "consumed from a sibling capability — not in scope", ha="left", va="center", fontsize=11, color="#222")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    enterprise(d / "capability-map-v1.6a-enterprise-capability.png", tech=False)
    drilldown(d / "capability-map-v1.6b-km-capability.png", tech=False)
    enterprise(d / "capability-map-v1.6c-enterprise-technology.png", tech=True)
    drilldown(d / "capability-map-v1.6d-km-technology.png", tech=True)
