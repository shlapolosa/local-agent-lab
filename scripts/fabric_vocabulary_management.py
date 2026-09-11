"""Vocabulary Management (L4 1.1) — decomposition to L6 and the provider bake-off.

  vocabulary-management-v1.0a-decomposition.png  L4 → L5 → L6, each L6 tagged with the standard it comes from
  vocabulary-management-v1.0b-bakeoff.png        L6 rows × providers, ratings from docs/fabric/vocabulary-management.md

Standard used: ISO 25964-1 (thesauri: concepts, terms, equivalence, hierarchical and associative relationships,
facet analysis, multilingual equivalence, presentation, managing construction and maintenance, software
guidelines, data model — clause 15) and ISO 25964-2 (interoperability: mapping types, structural models,
other KOS types). Ontology management is outside ISO 25964's scope; it follows W3C OWL/RDFS/SHACL and the
EKG/MM "Ontologies" capability. Lifecycle detail follows ANSI/NISO Z39.19 (maintenance) and Hedden 2019.

    python scripts/fabric_vocabulary_management.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

# ---------------------------------------------------------------- decomposition
L5 = [  # (id, name, gloss, standard, [(L6 id, L6 name, source)])
    ("1.1.1", "Concept Scheme Management", "define what things mean and how they relate", "ISO 25964-1 · SKOS", [
        ("1.1.1.1", "Concept & Label Management", "ISO 25964-1 concepts & terms · SKOS prefLabel/altLabel"),
        ("1.1.1.2", "Equivalence Management", "ISO 25964-1 equivalence, compound equivalence"),
        ("1.1.1.3", "Hierarchy Management", "ISO 25964-1 generic · whole-part · instance; polyhierarchy"),
        ("1.1.1.4", "Associative Relationship Mgmt", "ISO 25964-1 associative; custom relations"),
        ("1.1.1.5", "Facet & Array Management", "ISO 25964-1 facet analysis · arrays · node labels"),
        ("1.1.1.6", "Multilingual Equivalence Mgmt", "ISO 25964-1 cross-language equivalence degrees")]),
    ("1.1.2", "Ontology Management", "define the classes, properties and rules the graph obeys", "OWL · RDFS · SHACL · EKG/MM", [
        ("1.1.2.1", "Class & Property Definition", "RDFS / OWL · EKG/MM Ontologies"),
        ("1.1.2.2", "Constraint & Shape Definition", "W3C SHACL"),
        ("1.1.2.3", "Upper Vocabulary Reuse", "DCAT · PROV-O · DCTerms · schema.org"),
        ("1.1.2.4", "Inference Rule Definition", "OWL · SPARQL CONSTRUCT · SHACL rules")]),
    ("1.1.3", "Vocabulary Alignment", "relate one vocabulary to another without merging them", "ISO 25964-2", [
        ("1.1.3.1", "Mapping Management", "ISO 25964-2 exact · inexact · partial · hierarchical · associative"),
        ("1.1.3.2", "Cross-KOS Interoperability", "ISO 25964-2 classification schemes · taxonomies · authorities · ontologies"),
        ("1.1.3.3", "Mapping Structure Management", "ISO 25964-2 direct-linked vs hub model"),
        ("1.1.3.4", "Mapping Verification", "ISO 25964-2 selective mapping · human confirmation")]),
    ("1.1.4", "Concept Lifecycle Management", "grow and govern the vocabulary over time", "ISO 25964-1 mgmt · Z39.19 · Hedden 2019", [
        ("1.1.4.1", "Candidate Term Intake", "Z39.19 candidate terms · corpus term extraction (Hedden)"),
        ("1.1.4.2", "Editorial Workflow", "ISO 25964-1 construction & maintenance · roles, permissions"),
        ("1.1.4.3", "Versioning & Deprecation", "Z39.19 maintenance · status, replaced-by, history"),
        ("1.1.4.4", "Quality Assurance", "ISO/Z39.19 logic: unique labels, reciprocals, no cycles"),
        ("1.1.4.5", "Publication & Access", "ISO 25964-1 data model (cl. 15), exchange formats, protocols · APIs")]),
]
L6IDS = [l6[0] for g in L5 for l6 in g[4]]

# ---------------------------------------------------------------- bake-off ratings (2 full · 1 partial · 0 none)
def R(s):
    s = s.replace(" ", ""); assert len(s) == 19, len(s)
    return dict(zip(L6IDS, (int(c) for c in s)))

#                                                 1.1.1 (6)  1.1.2 (4)  1.1.3 (4)  1.1.4 (5)
PROVIDERS = {  # name: (status, in-tenant deployment, SharePoint/M365 integration, ratings)
    "SharePoint\nterm store\n+ SP Premium": ("estate",   "S", "native",  R("212102 0000 0000 10101")),
    "Microsoft Purview\nglossary":          ("estate",   "S", "partial", R("111110 0000 0000 01101")),
    "Azure AI Search\nsynonym maps":        ("estate",   "S", "n/a",     R("010000 0000 0000 00000")),
    "PoolParty\n(Semantic Web Co.)":        ("candidate","✓ server/hosted", "✓ SPO app + sync", R("222222 2121 2111 22222")),
    "Progress\nSemaphore":                  ("candidate","verify: SaaS/on-prem", "✓ SPO app + labels", R("222212 2111 1111 22222")),
    "TopBraid EDG\n(TopQuadrant)":          ("candidate","✓ Azure Mktplace", "✗ APIs only", R("222212 2222 2211 12221")),
    "Synaptica\nGraphite":                  ("candidate","✓ hosted/on-prem", "✓ SP connector", R("222212 1010 2111 12212")),
    "Mondeca ITM":                          ("candidate","✓ on-prem/hosted", "✓ term-store sync", R("222212 2111 1111 12212")),
    "Data Harmony\n(Access Innovations)":   ("candidate","✓ server/hosted", "✓ API connector", R("222211 0000 0000 21121")),
    "VocBench 3\n(open source)":            ("open",     "✓ self-hosted", "✗ SKOS export", R("222222 2121 2112 02221")),
    "Protégé\n(open source)":               ("open",     "✓ desktop", "✗", R("101001 2122 1000 01111")),
    "Lab semantic-mcp\n(POC substitute)":   ("poc",      "local", "✗ MCP+SPARQL", R("212000 2102 1010 00011")),
}
STATUS = {"estate": ("#e8f3ea", "#2f855a", "estate as shipped"), "candidate": ("#ffffff", "#2b6cb0", "buy-lite candidate"),
          "open": ("#eef2fb", "#2b6cb0", "open source"), "poc": ("#fff8e6", "#c9950c", "POC substitute (built)")}
CELL = {2: ("#9fd3a8", "●"), 1: ("#f5d78e", "◐"), 0: ("#f0f0f0", "○")}


def box(ax, H, x, y, w, h, fc, ec, lw=1.4, ls="-", r=1.0):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def fit(fs, w, text, k=0.9):
    return min(fs, fs * (w - 2.0) / (k * max(1, len(text))))


def decomposition(out: Path) -> None:
    W, H = 192.0, 80.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "Vocabulary Management (L4 1.1) — functional decomposition to L6, anchored in ISO 25964", ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    ax.text(W / 2, H - 6.4, "Pure capability · each L6 carries the standard it comes from · ontology management is outside ISO 25964 and follows W3C OWL / SHACL and EKG/MM", ha="center", va="center", fontsize=10.5, color="#777", style="italic")
    m = 2.2
    y0 = 9.4
    # L4 box
    box(ax, H, m, y0, W - 2 * m, H - y0 - 2.2, "white", "#444", 2.0, r=1.6)
    ax.text(m + 2.6, H - y0 - 3.0, "1.1  Vocabulary Management", ha="left", va="center", fontsize=16, fontweight="bold", color="#222")
    ax.text(m + 2.6, H - y0 - 6.2, "L4 · the ability to define, relate, align and govern the meaning the organisation's knowledge is described with — concept schemes for subjects, an ontology for structure", ha="left", va="center", fontsize=10.5, color="#555")
    ax.text(W - m - 2.6, H - y0 - 3.0, "MVP · buy-lite candidate (options view) · gap in Annex D", ha="right", va="center", fontsize=10.5, color="#c9950c", style="italic")
    # L5 columns
    n = len(L5); gap = 1.8; pad = 2.4
    cw = (W - 2 * m - 2 * pad - gap * (n - 1)) / n
    top = y0 + 9.0
    maxk = max(len(g[4]) for g in L5)
    L6H, L6G = 7.2, 1.0
    gh = 3.2 + 3.0 + 2.6 + maxk * (L6H + L6G) + 1.2
    for i, (gid, gname, gloss, std, l6s) in enumerate(L5):
        x = m + pad + i * (cw + gap)
        box(ax, H, x, top, cw, gh, "#f7f7f7", "#888", 1.4, r=1.2)
        ax.text(x + 1.6, H - top - 2.2, f"{gid}  {gname}", ha="left", va="center", fontsize=fit(12.5, cw, f"{gid}  {gname}", 0.95), fontweight="bold", color="#222")
        ax.text(x + 1.6, H - top - 4.9, "L5 · " + gloss, ha="left", va="center", fontsize=fit(9.6, cw, "L5 · " + gloss, 0.66), color="#555", style="italic")
        ax.text(x + 1.6, H - top - 7.3, std, ha="left", va="center", fontsize=fit(9.2, cw, std, 0.66), color="#2b6cb0", fontweight="bold")
        for k, (lid, lname, src) in enumerate(l6s):
            y = top + 9.2 + k * (L6H + L6G)
            box(ax, H, x + 1.4, y, cw - 2.8, L6H, "white", "#8c8c8c", 1.2, r=0.9)
            ax.text(x + cw / 2, H - y - 2.3, lname, ha="center", va="center", fontsize=fit(11, cw - 2.8, lname, 0.92), fontweight="bold", color="#222")
            ax.text(x + cw / 2, H - y - 4.4, "L6 · " + lid, ha="center", va="center", fontsize=8.6, color="#777")
            ax.text(x + cw / 2, H - y - 6.1, src, ha="center", va="center", fontsize=fit(8.6, cw - 2.8, src, 0.62), color="#2b6cb0")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


def bakeoff(out: Path) -> None:
    W = 192.0
    LABW, HDRH, RH, GRH = 48.0, 14.0, 3.55, 3.0
    m = 2.2
    names = list(PROVIDERS)
    ncol = len(names)
    cw = (W - 2 * m - LABW) / ncol
    body = len(L6IDS) * RH + len(L5) * GRH + GRH + 2 * RH
    H = 9.4 + HDRH + body + 2.4 + 15.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, "Vocabulary Management bake-off v1.0 — providers against the L6 decomposition (September 2026)", ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    ax.text(W / 2, H - 6.4, "Rows = L6 of vocabulary-management-v1.0a · ratings from product documentation and Hedden 2019, not a live evaluation · see docs/fabric/vocabulary-management.md", ha="center", va="center", fontsize=10.5, color="#777", style="italic")
    y = 9.4
    for j, name in enumerate(names):
        status, dep, sp, rat = PROVIDERS[name]
        fill, edge, lbl = STATUS[status]
        x = m + LABW + j * cw
        box(ax, H, x + 0.35, y, cw - 0.7, HDRH, fill, edge, 1.2, r=0.8)
        for k, ln in enumerate(name.split("\n")):
            ax.text(x + cw / 2, H - y - 2.2 - 2.1 * k, ln, ha="center", va="center", fontsize=fit(9.6, cw, ln, 0.88), fontweight="bold", color="#222")
        ax.text(x + cw / 2, H - y - HDRH + 1.5, lbl, ha="center", va="center", fontsize=fit(7.8, cw, lbl, 0.7), color=edge, style="italic")
    y += HDRH
    row_i = 0
    for (gid, gname, gloss, std, l6s) in L5:
        ax.add_patch(Rectangle((m, H - y - GRH), W - 2 * m, GRH, fc="#e9e9e9", ec="none"))
        ax.text(m + 1.2, H - y - GRH / 2, f"{gid}  {gname}   ·   {std}", ha="left", va="center", fontsize=10, fontweight="bold", color="#444")
        y += GRH
        for (lid, lname, src) in l6s:
            ax.add_patch(Rectangle((m, H - y - RH), W - 2 * m, RH, fc="#fafafa" if row_i % 2 else "white", ec="none"))
            ax.text(m + 1.2, H - y - RH / 2, f"{lid}  {lname}", ha="left", va="center", fontsize=10, color="#222")
            for j, name in enumerate(names):
                v = PROVIDERS[name][3][lid]; fc, sym = CELL[v]
                x = m + LABW + j * cw
                box(ax, H, x + 0.5, y + 0.35, cw - 1.0, RH - 0.7, fc, "#bbb", 0.5, r=0.5)
                ax.text(x + cw / 2, H - y - RH / 2 - 0.05, sym, ha="center", va="center", fontsize=10.5, color="#333")
            y += RH; row_i += 1
    # constraints
    ax.add_patch(Rectangle((m, H - y - GRH), W - 2 * m, GRH, fc="#e9e9e9", ec="none"))
    ax.text(m + 1.2, H - y - GRH / 2, "Fabric constraints (text, not rated)", ha="left", va="center", fontsize=10, fontweight="bold", color="#444")
    y += GRH
    for label, idx in (("In-tenant / in-region deployment", 1), ("SharePoint / M365 integration", 2)):
        ax.add_patch(Rectangle((m, H - y - RH), W - 2 * m, RH, fc="white", ec="none"))
        ax.text(m + 1.2, H - y - RH / 2, label, ha="left", va="center", fontsize=10, color="#222")
        for j, name in enumerate(names):
            t = PROVIDERS[name][idx]
            x = m + LABW + j * cw
            ax.text(x + cw / 2, H - y - RH / 2, t, ha="center", va="center", fontsize=fit(8.6, cw, t, 0.7), color="#c0392b" if t.startswith("✗") else ("#c9950c" if t.startswith("verify") else "#1f5f33"))
        y += RH
    y += 2.4
    box(ax, H, m, y, W - 2 * m, 15.0, "#fafafa", "#999", 1.2, (0, (2, 2)), r=1.6)
    lx = m + 2.4
    for v, lbl in ((2, "● covers as shipped"), (1, "◐ partial"), (0, "○ none")):
        fc, sym = CELL[v]
        box(ax, H, lx, y + 1.6, 3.2, 2.4, fc, "#bbb", 0.6, r=0.5)
        ax.text(lx + 4.2, H - y - 2.8, lbl, ha="left", va="center", fontsize=10, color="#222")
        lx += 4.2 + 0.7 * len(lbl) + 5
    notes = [
        "Estate columns cover 1.1.1 partially and none of 1.1.2–1.1.3: the term store is a taxonomy, not a thesaurus (no associative relations, mapping or workflow) — it stays the SharePoint-side projection target for any winner.",
        "Specialists (PoolParty, Semaphore, EDG, Synaptica, Mondeca) cover 1.1.1 and 1.1.4 fully; they differ on 1.1.2 (EDG: native SHACL, rules), 1.1.3 (EDG, PoolParty) and SharePoint integration (EDG has no connector).",
        "VocBench 3 matches the specialists on the standard itself (SKOS/OWL, workflow, alignment, integrity checks) at zero licence cost, with no SharePoint connector and no term extraction — the open-source baseline to beat.",
        "The lab's semantic-mcp is a POC substitute proving the SKOS + SPARQL + alignment pattern locally; it is not a product, and its ○ cells are the pro-code that would otherwise be written.",
    ]
    for i, t in enumerate(notes):
        ax.text(m + 2.4, H - y - 5.6 - 2.2 * i, "•  " + t, ha="left", va="center", fontsize=min(9.4, 9.4 * (W - 2 * m - 6) / (0.6 * len(t))), color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    decomposition(d / "vocabulary-management-v1.0a-decomposition.png")
    bakeoff(d / "vocabulary-management-v1.0b-bakeoff.png")
