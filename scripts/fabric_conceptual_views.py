"""Documentation Fabric conceptual views v1.0 (free layout — not bound to the initiative doc's figures).

  conceptual-platform-v1.0.png   the three-sided metadata product platform; the semantic layer is its product
  provenance-ladder-v1.0.png     note 005: rungs as trust-ordered strata, assertion types as columns,
                                 promotion gates as arrows, port read-policies as brackets

    python scripts/fabric_conceptual_views.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

UPL = ("#fde8e6", "#c0392b")      # fabric-owned
CON = ("#e9e9e9", "#777777")      # consumed / estate
PRD = ("#cfe0f7", "#2b6cb0")      # products (the semantic layer)
CUR = ("#fbe7b3", "#c9950c")      # curators
ONT = ("#e6dcf5", "#6b46c1")      # ontology


def box(ax, H, x, y, w, h, fc, ec, lw=1.4, ls="-", r=1.0):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, text, k=0.66):
    return min(fs, fs * (w - 1.6) / (k * max(1, len(text))))


def txt(ax, H, x, y, s, fs=9, **kw):
    kw.setdefault("ha", "left"); kw.setdefault("va", "center"); kw.setdefault("color", "#222")
    ax.text(x, H - y, s, fontsize=fs, **kw)


def arrow(ax, H, x0, y0, x1, y1, color="#444", ls="-", lw=1.1):
    ax.annotate("", xy=(x1, H - y1), xytext=(x0, H - y0), arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, ls=ls, mutation_scale=10))


# ============================================================ platform view
def platform(out: Path) -> None:
    W, H = 200.0, 156.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    txt(ax, H, W / 2, 3.0, "Documentation Fabric — a three-sided metadata product platform whose product is the semantic layer", 17, ha="center", fontweight="bold")
    txt(ax, H, W / 2, 6.6, "sides are ROLES, not populations — the same person produces, curates and consumes · red = fabric-owned · blue = the products · amber = curators · grey = consumed from the estate", 9.5, ha="center", color="#777", style="italic")

    L, R = 24.0, 24.0           # side columns
    X0, X1 = 2.2 + L + 1.6, W - 2.2 - R - 1.6
    MW = X1 - X0

    # ---- side columns
    box(ax, H, 2.2, 9.5, L, 137.0, "#f4f4f4", "#777", 1.4, r=1.4)
    txt(ax, H, 2.2 + L / 2, 12.4, "Trust services", 11, ha="center", fontweight="bold")
    txt(ax, H, 2.2 + L / 2, 14.6, "cross-cutting · consumed", 7.4, ha="center", color="#666", style="italic")
    txt(ax, H, 2.2 + L / 2, 16.8, "frame every transaction, every side", 7.4, ha="center", color="#666", style="italic")
    for i, (t, s) in enumerate([("Identity & Access", "Entra · label pass-through · principal identity for agents"),
                                ("Audit", "Purview audit · every synthesis, approval, propagation"),
                                ("AI gateway", "every model call · cost attribution · guardrails"),
                                ("Observability & gate metrics", "NFR-6: precision per rung · gate load · staleness age"),
                                ("Fitness functions in CI", "metadata-only · no custom duplicate of estate · owner/label never model-originated"),
                                ("Federated governance", "principles as tests · quarterly estate review")]):
        y = 20.0 + i * 20.3
        box(ax, H, 3.6, y, L - 2.8, 18.0, "#ffffff", "#999", 1.0, r=0.9)
        txt(ax, H, 3.6 + (L - 2.8) / 2, y + 2.6, t, fit(9.4, L - 2.8, t, 0.78), ha="center", fontweight="bold")
        import textwrap
        for j, ln in enumerate(textwrap.wrap(s, 26)[:4]):
            txt(ax, H, 3.6 + (L - 2.8) / 2, y + 6.4 + 2.6 * j, ln, 7.4, ha="center", color="#444")

    box(ax, H, X1 + 1.6, 9.5, R, 137.0, CUR[0], CUR[1], 1.6, r=1.4)
    txt(ax, H, X1 + 1.6 + R / 2, 12.4, "Curators", 11, ha="center", fontweight="bold")
    txt(ax, H, X1 + 1.6 + R / 2, 14.6, "the third side · owners & stewards", 7.4, ha="center", color="#7a5a00", style="italic")
    txt(ax, H, X1 + 1.6 + R / 2, 16.8, "they DISPOSE; the platform proposes", 7.4, ha="center", color="#7a5a00", style="italic")
    for i, (t, s) in enumerate([("Confirm association", "one-tap card · S → H on a delivery edge"),
                                ("Adjudicate duplicate", "steward · merge / keep / supersede"),
                                ("Review & approve", "owner · promotes type, concept links, lifecycle state"),
                                ("Curate vocabulary", "steward · candidate → accepted → deprecated"),
                                ("Work the orphan queue", "steward · associate or mark non-delivery"),
                                ("Dispose correction", "owner · Target · in the source's own review")]):
        y = 20.0 + i * 17.3
        box(ax, H, X1 + 3.0, y, R - 2.8, 15.0, "#ffffff", CUR[1], 1.0, r=0.9)
        txt(ax, H, X1 + 3.0 + (R - 2.8) / 2, y + 2.6, t, fit(9.2, R - 2.8, t, 0.78), ha="center", fontweight="bold")
        import textwrap
        for j, ln in enumerate(textwrap.wrap(s, 26)[:3]):
            txt(ax, H, X1 + 3.0 + (R - 2.8) / 2, y + 6.2 + 2.6 * j, ln, 7.4, ha="center", color="#444")
    txt(ax, H, X1 + 1.6 + R / 2, 128.0, "channel: Teams cards · steward console", 7.4, ha="center", color="#7a5a00", style="italic")
    txt(ax, H, X1 + 1.6 + R / 2, 131.0, "service level: gate load · escalation time", 7.4, ha="center", color="#7a5a00", style="italic")
    txt(ax, H, X1 + 1.6 + R / 2, 140.0, "no rung crossing without a gate;", 7.4, ha="center", color="#7a5a00", style="italic")
    txt(ax, H, X1 + 1.6 + R / 2, 143.0, "no gate without a rung crossing (note 005)", 7.4, ha="center", color="#7a5a00", style="italic")

    # ---- band helper
    def band(y, h, title, fc, ec, note=None):
        box(ax, H, X0, y, MW, h, fc, ec, 1.6, r=1.4)
        txt(ax, H, X0 + 2.0, y + 2.6, title, 11, fontweight="bold")
        if note:
            txt(ax, H, X1 - 2.0, y + 2.6, note, 8.0, ha="right", color="#666", style="italic")

    # 1 consumers
    y = 9.5; h = 20.0
    band(y, h, "CONSUMERS — people and agents acting for a principal", "#e7f3ec", "#2f855a", "what they can do = the competency questions, served per product · plus follow / subscribe · recommendations")
    cw = (MW - 4 * 2.0) / 3
    for i, (t, s) in enumerate([("WHO", "People: owners, architects, BAs, developers, ops · Agents: conversational, agentic solutions, coding agents — same principal identity, same trimming, same audit (NFR-8)"),
                                ("WHAT", "CQ features per product (catalog · graph · vocabulary · events) · composite CQs via the facade · follow & digests · reuse suggestions · expertise"),
                                ("CHANNEL", "the facade's output ports: Copilot & search · Teams · MCP door for agents — all label-trimmed at read time; the grade of every answer is returned")]):
        x = X0 + 2.0 + i * (cw + 2.0)
        box(ax, H, x, y + 5.4, cw, h - 7.0, "#ffffff", "#2f855a", 1.0, r=0.9)
        txt(ax, H, x + 1.4, y + 7.6, t, 8.6, fontweight="bold", color="#1f5f33")
        import textwrap
        for j, ln in enumerate(textwrap.wrap(s, int(cw / 0.62))[:4]):
            txt(ax, H, x + 1.4, y + 10.2 + 2.3 * j, ln, 7.6, color="#333")
    arrow(ax, H, X0 + MW / 2, y + h, X0 + MW / 2, y + h + 2.0)

    # 2 facade
    y = 31.5; h = 11.5
    band(y, h, "KNOWLEDGE LAYER FACADE — the aggregate product (note 004): owner = fabric team · composes the four, writes to none", PRD[0], PRD[1], "service level = weakest constituent, per answer")
    txt(ax, H, X0 + 2.0, y + 6.6, "output ports: search & Q&A · relationship traversal · subscriptions & digests · composite CQs (08 15 16 19 20 24 26 27) · reads every rung, shows the grade", 8.4, color="#333")
    txt(ax, H, X0 + 2.0, y + 9.4, "Knowledge Discovery (L3 group 4) lives HERE, not in platform services — it is retrieval over the products: Knowledge Retrieval · Recommendation · Expertise Identification", 8.0, color="#2b6cb0", style="italic")
    arrow(ax, H, X0 + MW / 2, y + h, X0 + MW / 2, y + h + 2.0)

    # 3 products (= the semantic layer)
    y = 45.0; h = 30.0
    band(y, h, "THE PRODUCTS = THE SEMANTIC LAYER — four metadata products, one shared ontology (note 004)", PRD[0], PRD[1], "metadata only: pointers, edges, concepts, events — never content")
    pw = (MW - 5 * 2.0) / 4
    prods = [("Knowledge Catalog", "owner: fabric · per-artifact owner from the owner map", ["pointers · lifecycle state · owner · label · baseline", "ports: catalog tools · SPARQL", "SLO: metadata-only fitness · currency"], True),
             ("Traceability Graph", "owner: fabric · stewards confirm edges", ["delivery · reference · subject edges, with provenance", "ports: traversal tools · SPARQL over chosen graphs", "SLO: edge precision (NFR-7) · impact over C·X·H only"], True),
             ("Vocabulary", "owner: the steward", ["concept schemes · ontology · alignments", "ports: SKOS export · term-store sync · MCP", "SLO: concept lifecycle · alignments confirmed"], True),
             ("Change Events", "owner: platform", ["inbound stream (ArtifactChanged) · finished stream", "ports: subscriptions", "SLO: durable · at-least-once · idempotent per pointer"], False)]
    import textwrap
    for i, (t, own, lines, strata) in enumerate(prods):
        x = X0 + 2.0 + i * (pw + 2.0)
        box(ax, H, x, y + 5.4, pw, h - 7.2, "#ffffff", PRD[1], 1.2, r=0.9)
        txt(ax, H, x + pw / 2, y + 7.8, t, 10.5, ha="center", fontweight="bold")
        txt(ax, H, x + pw / 2, y + 10.4, own, fit(7.4, pw, own, 0.62), ha="center", color="#2b6cb0", style="italic")
        yy = y + 12.8
        for ln in lines:
            for l2 in textwrap.wrap(ln, int(pw / 0.62))[:2]:
                txt(ax, H, x + 1.2, yy, "· " + l2, 7.4, color="#333"); yy += 2.2
        # provenance strata
        sy = y + h - 7.6
        if strata:
            names = [("S", "#f5d78e"), ("X", "#cfe0f7"), ("C", "#9fd3a8"), ("H", "#9fd3a8"), ("D", "#e6dcf5")]
            sw = (pw - 2.4) / len(names)
            for k, (n, c) in enumerate(names):
                ax.add_patch(Rectangle((x + 1.2 + k * sw, H - sy - 3.2), sw, 3.2, fc=c, ec="#999", lw=0.5))
                txt(ax, H, x + 1.2 + k * sw + sw / 2, sy + 1.6, n, 7.6, ha="center", fontweight="bold", color="#333")
            txt(ax, H, x + pw / 2, sy + 4.9, "provenance strata = named graphs (note 005)", 6.8, ha="center", color="#666", style="italic")
        else:
            ax.add_patch(Rectangle((x + 1.2, H - sy - 3.2), pw - 2.4, 3.2, fc="#e9e9e9", ec="#999", lw=0.5))
            txt(ax, H, x + pw / 2, sy + 1.6, "O — observed only; never in the graph", 7.2, ha="center", color="#333")
    # ontology bar
    oy = y + h + 1.2
    box(ax, H, X0, oy, MW, 6.4, ONT[0], ONT[1], 1.4, r=1.0)
    txt(ax, H, X0 + MW / 2, oy + 2.2, "ONTOLOGY — the shared language both outer sides must speak: the pointer scheme · the event contract · the concept schemes · the class/property model (SHACL in CI)", 8.8, ha="center", fontweight="bold", color="#4c2d8f")
    txt(ax, H, X0 + MW / 2, oy + 4.7, "adapters translate sources INTO it · the facade translates it into answers · nothing else crosses the boundary", 7.8, ha="center", color="#4c2d8f", style="italic")

    # 4 platform services
    y = 84.0; h = 24.5
    band(y, h, "PLATFORM SERVICES — the knowledge-management capabilities that BUILD and KEEP the products (map 1.6b)", UPL[0], UPL[1], "delivery mode per note 002 · phased adapters per phased-realisation.md")
    sw = (MW - 5 * 2.0) / 4
    svcs = [("1 Knowledge Organisation", "→ Vocabulary · Catalog identity", ["Vocabulary Management", "Catalog Management"]),
            ("2 Knowledge Production", "→ Catalog records · Graph edges", ["Content Synthesis · Knowledge Classification", "Version Management · Traceability Management"]),
            ("3 Knowledge Governance", "→ trust state transitions, via the curators", ["Ownership & Stewardship · Knowledge Review", "Duplicate Management"]),
            ("5 Knowledge Currency", "→ Change Events · keeps Catalog & Graph current", ["Change Detection · Impact Analysis · Subscription", "Republication · Reconciliation · Remediation"])]
    for i, (t, to, lines) in enumerate(svcs):
        x = X0 + 2.0 + i * (sw + 2.0)
        box(ax, H, x, y + 5.4, sw, h - 7.0, "#ffffff", UPL[1], 1.2, r=0.9)
        txt(ax, H, x + sw / 2, y + 7.8, t, fit(10, sw, t, 0.8), ha="center", fontweight="bold")
        txt(ax, H, x + sw / 2, y + 10.4, to, fit(7.6, sw, to, 0.62), ha="center", color="#c0392b", style="italic")
        for j, ln in enumerate(lines):
            txt(ax, H, x + sw / 2, y + 13.2 + 2.4 * j, ln, fit(7.4, sw, ln, 0.62), ha="center", color="#333")
        arrow(ax, H, x + sw / 2, y + 5.4, x + sw / 2, y - 1.2 - 6.4 + 6.4 - 0.2, color=UPL[1])
    # estate tags consumed at specific points
    for i, tag in enumerate(["SharePoint custody & versions (Production)", "Purview retention (products, Target)", "Teams message delivery (curators, consumers)", "ADO wiki write (Republication)"]):
        x = X0 + 2.0 + i * (sw + 2.0)
        box(ax, H, x, y + h - 1.4 - 3.2, sw, 3.2, CON[0], CON[1], 0.9, r=0.6)
        txt(ax, H, x + sw / 2, y + h - 1.4 - 1.6, "consumed: " + tag, fit(7.0, sw, "consumed: " + tag, 0.6), ha="center", color="#444")

    # 5 ports & adapters
    y = 111.0; h = 17.5
    band(y, h, "PRODUCER-SIDE PORTS AND ADAPTERS (note 003) — the fabric knows contracts, not sources", "#fff8e6", "#c9950c", "one adapter per source · own identity · least privilege · holds the credentials · loop-guard tag")
    pw2 = (MW - 3 * 2.0) / 2
    for i, (t, s) in enumerate([("PORT 1 · inbound events", "ArtifactChanged {pointer · source kind · actor · timestamp · tag} on a durable pub/sub — idempotent per pointer; a new event replaces a pending draft"),
                                ("PORT 2 · content by reference", "read-by-pointer · write-draft-by-pointer, as governed tools on the gateway — bytes never pass through the caller; the source decides access at read time")]):
        x = X0 + 2.0 + i * (pw2 + 2.0)
        box(ax, H, x, y + 5.2, pw2, 6.4, "#ffffff", "#c9950c", 1.0, r=0.8)
        txt(ax, H, x + 1.4, y + 7.0, t, 8.6, fontweight="bold", color="#7a5a00")
        for j, ln in enumerate(textwrap.wrap(s, int(pw2 / 0.6))[:2]):
            txt(ax, H, x + 1.4, y + 9.2 + 2.0 * j, ln, 7.2, color="#333")
    ads = ["SharePoint adapter", "ADO adapter", "EA repository adapter", "Teams / Outlook adapter", "Design-board adapter", "+ next source = one adapter"]
    aw = (MW - 4.0 - (len(ads) - 1) * 1.4) / len(ads)
    for i, a in enumerate(ads):
        x = X0 + 2.0 + i * (aw + 1.4)
        box(ax, H, x, y + 12.6, aw, 3.6, UPL[0] if i < 5 else "#ffffff", UPL[1], 1.0, (0, (3, 2)) if i == 5 else "-", r=0.6)
        txt(ax, H, x + aw / 2, y + 14.4, a, fit(7.6, aw, a, 0.64), ha="center", fontweight="bold" if i < 5 else "normal", color="#222")
    arrow(ax, H, X0 + MW / 2, y, X0 + MW / 2, y - 2.0)
    arrow(ax, H, X0 + MW / 2, y + h + 2.0, X0 + MW / 2, y + h)

    # 6 producers
    y = 130.5; h = 16.0
    band(y, h, "PRODUCERS — delivery teams, and agents that file proposals", CON[0], CON[1], "content STAYS in custody (principle 2) — the fabric holds pointers")
    for i, (t, s) in enumerate([("WHO", "BA · EA · developers · ops — every discipline is a work item (§5.3) · remediation agents filing corrections (Target)"),
                                ("WHAT", "artifacts, decisions, drawings, meetings and their raw material — produced in the course of delivery, keyed at creation where the operating model applies"),
                                ("CHANNEL", "the systems of record: SharePoint · Azure DevOps · EA repository · Teams / Outlook · design boards — reached only through the adapters above")]):
        x = X0 + 2.0 + i * (cw + 2.0)
        box(ax, H, x, y + 5.2, cw, h - 6.8, "#ffffff", "#777", 1.0, r=0.9)
        txt(ax, H, x + 1.4, y + 7.2, t, 8.6, fontweight="bold", color="#444")
        for j, ln in enumerate(textwrap.wrap(s, int(cw / 0.62))[:3]):
            txt(ax, H, x + 1.4, y + 9.6 + 2.2 * j, ln, 7.4, color="#333")

    txt(ax, H, W / 2, 150.5, "Read top-down for consumption, bottom-up for production; the curators act on the products band and the governance services; the trust services frame every transaction. Semantic layer = the products band + the ontology bar; platform = everything else.", 8.6, ha="center", color="#555", style="italic")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


# ============================================================ ladder view
def ladder(out: Path) -> None:
    W, H = 200.0, 120.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    txt(ax, H, W / 2, 3.0, "The provenance ladder (note 005) — how every assertion earns its place in the graph", 17, ha="center", fontweight="bold")
    txt(ax, H, W / 2, 6.6, "rungs are trust-ordered strata = named graphs · columns are assertion types · ● where a type may ENTER · arrows are promotions, each one a curator gate · brackets are what each port reads", 9.5, ha="center", color="#777", style="italic")

    LAB = 30.0; RB = 40.0
    X0 = 2.2 + LAB; X1 = W - 2.2 - RB
    cols = [("Identity (IRI)", None), ("Owner · sensitivity", None), ("Delivery edge", None), ("Reference edge", None),
            ("Document type", None), ("Concept link", None), ("Concept (vocabulary)", None), ("Back-book edge", None), ("Correction proposal", None)]
    cw = (X1 - X0) / len(cols)
    strata = [  # top → bottom (trust order): name, letter, fill, description, trusted for impact
        ("Derived", "D", "#e6dcf5", "inferred from trusted assertions by a stated rule · recomputed, never captured", "yes, at the weakest input's grade"),
        ("Confirmed", "H", "#9fd3a8", "a person accepted a suggestion or an extraction", "yes"),
        ("Constructed", "C", "#9fd3a8", "deterministic by construction: a lookup, a link at creation", "yes"),
        ("Extracted", "X", "#cfe0f7", "deterministic parse of an explicit reference · has a known error class", "yes"),
        ("Suggested", "S", "#f5d78e", "probabilistic · carries confidence and method", "NEVER"),
        ("Observed", "O", "#e9e9e9", "a source event or signal · lands in Change Events, not in the graph", "no"),
    ]
    SY = 16.0; SH = 14.0
    ys = {}
    for i, (n, l, c, d, tr) in enumerate(strata):
        y = SY + i * SH
        ys[l] = y
        ax.add_patch(Rectangle((X0, H - y - SH), X1 - X0, SH, fc=c, ec="#999", lw=0.6, alpha=0.55))
        box(ax, H, 2.2, y + 0.8, LAB - 1.2, SH - 1.6, c, "#888", 1.0, r=0.8)
        txt(ax, H, 2.2 + 1.4, y + 3.4, f"{l}  {n}", 10.5, fontweight="bold")
        import textwrap
        for j, ln in enumerate(textwrap.wrap(d, 36)[:3]):
            txt(ax, H, 2.2 + 1.4, y + 6.4 + 2.2 * j, ln, 7.2, color="#333")
        txt(ax, H, 2.2 + 1.4, y + SH - 1.9, "impact: " + tr, 7.2, color="#c0392b" if tr.startswith("NEVER") else "#1f5f33", fontweight="bold")
    # column headers
    for i, (name, _) in enumerate(cols):
        x = X0 + i * cw
        ax.plot([x, x], [H - SY, H - (SY + 6 * SH)], color="#bbb", lw=0.6)
        txt(ax, H, x + cw / 2, SY - 2.6, name, fit(8.6, cw, name, 0.72), ha="center", fontweight="bold")
    ax.plot([X1, X1], [H - SY, H - (SY + 6 * SH)], color="#bbb", lw=0.6)

    def entry(col, letter, label=None):
        x = X0 + col * cw + cw / 2; y = ys[letter] + SH / 2
        ax.plot([x], [H - y], marker="o", ms=9, color="#222")
        if label:
            txt(ax, H, x, y + 3.2, label, fit(6.8, cw, label, 0.6), ha="center", color="#333")

    def promote(col, frm, to, gate, dx=0.0):
        x = X0 + col * cw + cw / 2 + dx
        y0 = ys[frm] + SH / 2 - 2.2; y1 = ys[to] + SH / 2 + 2.2
        arrow(ax, H, x, y0, x, y1, color="#c9950c", lw=1.4)
        txt(ax, H, x + 1.2, (y0 + y1) / 2, gate, fit(6.6, cw - 2, gate, 0.6), color="#7a5a00", style="italic",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))

    def forbidden(col, letter, why, dx=0.0):
        x = X0 + col * cw + cw / 2 + dx; y = ys[letter] + SH / 2
        txt(ax, H, x, y, "✕", 12, ha="center", color="#c0392b", fontweight="bold")
        txt(ax, H, x, y + 3.4, why, fit(6.6, cw, why, 0.6), ha="center", color="#c0392b")

    # identity
    entry(0, "C", "minted at creation"); forbidden(0, "S", "NFR-3: never suggested")
    # owner/sensitivity
    entry(1, "C", "owner map · inherited label"); forbidden(1, "S", "NFR-3: never model-guessed")
    # delivery edge
    entry(2, "C", "link at creation (rung 1)"); entry(2, "X", "id in text (rung 2)"); entry(2, "S", "signals (rung 3)"); promote(2, "S", "H", "one-tap card (rung 4)")
    # reference edge
    entry(3, "X", "links · embeds"); entry(3, "S", "similarity"); promote(3, "S", "H", "approval / card")
    # document type
    entry(4, "S", "model-suggested"); promote(4, "S", "H", "owner approval")
    # concept link
    entry(5, "X", "label match to pref/alt"); entry(5, "S", "nearest neighbour · model"); promote(5, "S", "H", "approval or steward")
    # concept
    entry(6, "C", "seeded scheme"); entry(6, "S", "candidate (intake)"); promote(6, "S", "H", "steward accepts"); txt(ax, H, X0 + 6 * cw + cw / 2, ys["H"] + SH / 2 - 3.6, "deprecate = retract (supersede)", 6.4, ha="center", color="#555", style="italic")
    # back-book
    entry(7, "X", "harvested explicit refs"); forbidden(7, "C", "NFR-7: no link at creation", dx=-cw / 4); promote(7, "X", "H", "card / steward", dx=cw / 4)
    # correction proposal
    entry(8, "S", "remediation agent"); promote(8, "S", "H", "owner disposal (Target)")
    # observed row note
    txt(ax, H, X0 + (X1 - X0) / 2, ys["O"] + SH / 2, "ArtifactChanged {pointer · source kind · actor · timestamp · tag} — the Change Events product; the only rung with no assertion in the graph", 8.0, ha="center", color="#444", style="italic")
    # derived row note
    txt(ax, H, X0 + (X1 - X0) / 2, ys["D"] + SH / 2, "narrower-concept closure · impact chains · expertise scores — recomputed after any promotion or retraction beneath; grade = min(inputs)", 8.0, ha="center", color="#4c2d8f", style="italic")

    # right brackets: port read policies
    bx = X1 + 2.0
    def bracket(top_letter, bot_letter, label, col):
        y0 = ys[top_letter] + 0.8; y1 = ys[bot_letter] + SH - 0.8
        ax.plot([bx, bx + 1.5, bx + 1.5, bx], [H - y0, H - y0, H - y1, H - y1], color=col, lw=1.6)
        for j, ln in enumerate(textwrap.wrap(label, 34)[:4]):
            txt(ax, H, bx + 3.0, (y0 + y1) / 2 - 3.0 + 2.4 * j, ln, 7.6, color=col)
    import textwrap
    bracket("D", "X", "IMPACT ANALYSIS reads D · H · C · X — never S (NFR-7). A wrong edge makes impact confidently wrong.", "#1f5f33")
    bracket("S", "S", "CURATOR QUEUES read S above threshold: the card, the orphan queue, the candidate-concept queue, the proposal inbox.", "#7a5a00")
    bracket("O", "O", "CHANGE DETECTION reads O: filter (allow-list) · attribute (loop guard) · then enter the pipeline.", "#555")
    txt(ax, H, bx, SY - 4.4, "DISCOVERY reads ALL rungs and returns", 7.8, fontweight="bold", color="#2b6cb0")
    txt(ax, H, bx, SY - 2.0, "the grade with every answer", 7.8, fontweight="bold", color="#2b6cb0")

    # rules footer
    fy = SY + 6 * SH + 2.4
    box(ax, H, 2.2, fy, W - 4.4, 13.5, "#fafafa", "#999", 1.2, (0, (2, 2)), r=1.4)
    rules = ["Promotion is a transaction and every promotion is a curator gate on the operating process — no rung crossing without a gate, no gate without a rung crossing.",
             "Retraction is supersession (PROV-O invalidation), never deletion — the audit chain (CQ-22) stays whole; Derived is recomputed after any change beneath it.",
             "Gate B's auto-association ratio is the share of edges entering at C or X versus needing H; NFR-6 precision is measured per rung. The ladder is the instrumentation.",
             "Rung = named graph: a SPARQL query over a chosen set of graphs is, literally, a trust policy. The lab's per-provenance store already implements this."]
    for i, r in enumerate(rules):
        txt(ax, H, 4.0, fy + 2.8 + 2.7 * i, "•  " + r, 8.4, color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


# ============================================================ executive ladder (Zeng-style spectrum)
def ladder_exec(out: Path) -> None:
    from matplotlib.patches import Ellipse
    W, H = 200.0, 137.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    txt(ax, H, W / 2, 3.2, "How knowledge earns trust in the fabric — the executive view", 17, ha="center", fontweight="bold")
    txt(ax, H, W / 2, 7.0, "Facts are looked up. AI only suggests. People confirm. And only looked-up, found or confirmed facts may decide what a change breaks.", 10.5, ha="center", color="#444", style="italic")

    # axes
    AX0, AX1, AY0, AY1 = 30.0, 188.0, 84.0, 12.0   # x range; y top-down (AY0 bottom, AY1 top)
    ax.annotate("", xy=(AX1, H - AY0), xytext=(AX0, H - AY0), arrowprops=dict(arrowstyle="-|>", color="#222", lw=2.2, mutation_scale=16))
    ax.annotate("", xy=(AX0, H - AY1), xytext=(AX0, H - AY0), arrowprops=dict(arrowstyle="-|>", color="#222", lw=2.2, mutation_scale=16))
    txt(ax, H, AX0 - 2.0, AY1 - 1.5, "trust", 11, ha="right", fontweight="bold")
    txt(ax, H, AX1 + 1.0, AY0 + 3.6, "how it got into the graph", 11, ha="right", fontweight="bold")
    for lbl, y in (("we act on it", 20.0), ("we show it, labelled", 46.0), ("we ask first", 66.0), ("not yet a fact", 80.0)):
        txt(ax, H, AX0 - 2.0, y, lbl, 8.6, ha="right", color="#333")
        ax.plot([AX0 - 1.0, AX0], [H - y, H - y], color="#222", lw=1.2)
    # diagonal
    ax.annotate("", xy=(AX1 - 24, H - 20.5), xytext=(AX0 + 2, H - (AY0 - 2)), arrowprops=dict(arrowstyle="-|>", color="#222", lw=1.3, ls=(0, (4, 3)), mutation_scale=12), zorder=0)

    blobs = [  # (name, subtitle, x, y, fill, edge, w, h)
        ("Raw signals", "an event: something changed,\nby someone, somewhere", 46, 76, "#e9e9e9", "#777", 26, 12),
        ("AI suggestions", "similar to · looks like a ·\nprobably about …", 72, 64, "#f5d78e", "#c9950c", 26, 12),
        ("Found in the content", "a work-item id in the text ·\nan embedded diagram · a link", 98, 50, "#cfe0f7", "#2b6cb0", 28, 12.5),
        ("Linked at creation", "the work item it was filed under ·\nthe owner on record · the label", 124, 38, "#9fd3a8", "#2f855a", 28, 12.5),
        ("Confirmed by a person", "one tap on a card · an approval ·\na steward's decision", 150, 26, "#9fd3a8", "#2f855a", 28, 12.5),
        ("Computed from the above", "what depends on what ·\nwho knows what", 176, 16, "#e6dcf5", "#6b46c1", 26, 12),
    ]
    heads = [("Signals:", 34, 66, "#2f6f6f"), ("Guesses:", 60, 52, "#2f6f6f"), ("Facts, looked up or found:", 92, 31, "#2f6f6f"), ("Judgements and inferences:", 140, 11.5, "#2f6f6f")]
    for t, x, y, c in heads:
        txt(ax, H, x, y, t, 13, color=c)
    cols_x = []
    for (n, sub, x, y, fc, ec, w, h) in blobs:
        ax.add_patch(Ellipse((x, H - y), w, h, fc=fc, ec=ec, lw=1.4, zorder=2))
        txt(ax, H, x, y - 2.4, n, 10.5, ha="center", fontweight="bold")
        for j, ln in enumerate(sub.split("\\n")):
            txt(ax, H, x, y + 0.6 + 2.2 * j, ln, 7.4, ha="center", color="#333")
        ax.plot([x, x], [H - (y + h / 2), H - AY0 + 0.6], color="#444", lw=0.9, ls=(0, (4, 2, 1, 2)))
        ax.annotate("", xy=(x, H - (AY0 + 4.0)), xytext=(x, H - AY0), arrowprops=dict(arrowstyle="-|>", color="#444", lw=0.9, mutation_scale=9))
        cols_x.append(x)

    # table
    TY = 90.0; LABW = 26.0
    rows = [
        ("Shown in search and answers", ["–", "xx  (labelled 'suggested')", "xxx", "xxxx", "xxxxx", "xxx  (labelled 'computed')"]),
        ("Used to decide what a change breaks", ["–", "never", "xxxx", "xxxxx", "xxxxx", "xxx"]),
        ("Sent to a person to confirm", ["–", "xxxxx", "x  (spot checks)", "–", "–", "–"]),
        ("Counts toward the go / no-go gates", ["–", "x", "xxx", "xxxx", "xxxxx", "–"]),
        ("How it can be wrong", ["not a fact yet", "often — which is why we ask", "rarely: a known error class", "almost never", "only if the person was", "as wrong as its weakest input"]),
    ]
    RH = 8.0
    x_left = AX0 - LABW; x_right = AX1
    ax.add_patch(Rectangle((x_left, H - (TY + RH * len(rows))), x_right - x_left, RH * len(rows), fc="white", ec="#222", lw=1.6))
    bounds = [x_left + LABW] + [(cols_x[i] + cols_x[i + 1]) / 2 for i in range(len(cols_x) - 1)] + [x_right]
    for b in bounds[:-1]:
        ax.plot([b, b], [H - TY, H - (TY + RH * len(rows))], color="#222", lw=0.8)
    txt(ax, H, x_left - 2.5, TY + RH * len(rows) / 2, "what we let it do", 9.5, ha="center", rotation=90, color="#333")
    for i, (lbl, cells) in enumerate(rows):
        y = TY + i * RH
        if i:
            ax.plot([x_left, x_right], [H - y, H - y], color="#222", lw=0.8)
        txt(ax, H, x_left + 1.2, y + RH / 2, lbl, 8.8)
        for j, c in enumerate(cells):
            cx = (bounds[j] + bounds[j + 1]) / 2
            cw = bounds[j + 1] - bounds[j]
            fs = 9.6 if c.replace("x", "") in ("", "–") else fit(7.6, cw, c, 0.62)
            txt(ax, H, cx, y + RH / 2, c, fs, ha="center", color="#222" if c != "never" else "#c0392b", fontweight="bold" if c == "never" else "normal")
    txt(ax, H, x_left, TY + RH * len(rows) + 3.0, "Detail for implementers: provenance-ladder-v1.0.png and note 005 (the six rungs O · S · X · C · H · D map one-to-one onto the six blobs above).", 8.2, color="#666", style="italic")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    platform(d / "conceptual-platform-v1.0.png")
    ladder(d / "provenance-ladder-v1.0.png")
    ladder_exec(d / "provenance-ladder-v1.0-exec.png")
