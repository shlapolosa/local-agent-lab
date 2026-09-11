"""Documentation Fabric options view v1.0 (replaces Figure 4) — providers against the KM L4 capabilities.

  options-view-v1.0a-incumbents.png       columns = named incumbents (Sept 2026 scan)
  options-view-v1.0b-provider-classes.png columns = provider classes, rating = best member in the class
Rows = L4 capabilities of capability-map-v1.6b (18 owned + 3 consumed). Ratings from
docs/fabric/market-scan-2026-09.md. 2 = covers as shipped, 1 = partial / own store only, 0 = none.

    python scripts/fabric_options_view.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

ROWS = [  # (group, id, name)
    ("1 Knowledge Organisation", "1.1", "Vocabulary Management"), ("1 Knowledge Organisation", "1.2", "Catalog Management"),
    ("2 Knowledge Production", "2.1", "Content Synthesis"), ("2 Knowledge Production", "2.2", "Knowledge Classification"),
    ("2 Knowledge Production", "2.3", "Version Management"), ("2 Knowledge Production", "2.4", "Traceability Management"),
    ("3 Knowledge Governance", "3.1", "Ownership & Stewardship"), ("3 Knowledge Governance", "3.2", "Knowledge Review"),
    ("3 Knowledge Governance", "3.3", "Duplicate Management"),
    ("4 Knowledge Discovery", "4.1", "Knowledge Retrieval"), ("4 Knowledge Discovery", "4.2", "Knowledge Recommendation"),
    ("4 Knowledge Discovery", "4.3", "Expertise Identification"),
    ("5 Knowledge Currency", "5.1", "Change Detection"), ("5 Knowledge Currency", "5.2", "Change Impact Analysis"),
    ("5 Knowledge Currency", "5.3", "Subscription Management"), ("5 Knowledge Currency", "5.4", "Republication"),
    ("5 Knowledge Currency", "5.5", "Catalog Reconciliation"), ("5 Knowledge Currency", "5.6", "Remediation Management"),
    ("Consumed from siblings", "AM", "Access Management"), ("Consumed from siblings", "AU", "Audit Management"),
    ("Consumed from siblings", "RR", "Records Retention"),
]
IDS = [r[1] for r in ROWS]

def R(s):  # 21 ratings as one string, in ROWS order
    s = s.replace(" ", "")
    assert len(s) == 21, len(s)
    return dict(zip(IDS, (int(c) for c in s)))

#                        1.1 1.2 | 2.1 2.2 2.3 2.4 | 3.1 3.2 3.3 | 4.1 4.2 4.3 | 5.1 5.2 5.3 5.4 5.5 5.6 | AM AU RR
PRODUCTS = {  # name: (status, ratings)
    "Microsoft estate\nas shipped":      ("baseline",  R("11 2121 111 212 101110 222")),
    "Glean":                             ("residency", R("11 1101 101 222 101021 210")),
    "Atlassian Rovo\n+ Teamwork Graph":  ("estate",    R("11 1122 110 211 212122 210")),
    "Google Gemini\nEnterprise":         ("verify",    R("11 1100 000 211 101021 210")),
    "Guru":                              ("federation",R("01 1110 221 211 101100 111")),
    "ServiceNow KM":                     ("federation",R("01 1120 221 211 101100 211")),
    "PoolParty\n(taxonomy platforms)":   ("buylite",   R("21 0200 110 100 000000 110")),
    "Swimm":                             ("pattern",   R("00 2011 110 100 221222 110")),
    "Coveo":                             ("verify",    R("01 0100 001 221 100020 210")),
    "Sinequa":                           ("candidate", R("11 0100 001 212 100020 210")),
    "Meeting-AI SaaS\n(Sembly-class)":   ("residency", R("00 2100 000 100 000000 000")),
    "Obsidian":                          ("excluded",  R("01 1011 000 100 100000 000")),
    "ADO alone":                         ("baseline",  R("01 0011 010 100 201000 210")),
    "Composed target\n(Annex D design)":  ("target",    R("22 2222 222 222 222222 222")),
    "Reuse-first\ncomposition":         ("target2",   R("22 2222 222 222 222222 222")),
}
CLASSES = {  # class: (status, members)
    "Platform-native\nestate (Microsoft)":      ("baseline",  ["Microsoft estate\nas shipped"]),
    "Enterprise AI search\n(Glean · Coveo · Sinequa)": ("mixed", ["Glean", "Coveo", "Sinequa"]),
    "Work-graph suite\n(Atlassian)":            ("estate",    ["Atlassian Rovo\n+ Teamwork Graph"]),
    "Agent platform\n(Gemini Enterprise)":      ("verify",    ["Google Gemini\nEnterprise"]),
    "Curated KB suites\n(Guru · ServiceNow ·\nBloomfire · Document360)": ("federation", ["Guru", "ServiceNow KM"]),
    "Taxonomy / ontology\n(PoolParty · Semaphore ·\nEDG · Synaptica)":   ("buylite",   ["PoolParty\n(taxonomy platforms)"]),
    "Docs-as-code\n(Swimm)":                    ("pattern",   ["Swimm"]),
    "Meeting-AI SaaS\n(Sembly-class)":          ("residency", ["Meeting-AI SaaS\n(Sembly-class)"]),
    "Personal knowledge\ntools (Obsidian)":     ("excluded",  ["Obsidian"]),
    "ADO alone":                                ("baseline",  ["ADO alone"]),
    "Composed target\n(Annex D design)":         ("target",    ["Composed target\n(Annex D design)"]),
    "Reuse-first\ncomposition":                 ("target2",   ["Reuse-first\ncomposition"]),
}
STATUS = {  # status: (header fill, header edge, label)
    "baseline":  ("#f2f2f2", "#777", "estate baseline"),
    "candidate": ("#ffffff", "#2f855a", "candidate"),
    "buylite":   ("#e8f3ea", "#2f855a", "buy-lite candidate"),
    "verify":    ("#fff8e6", "#c9950c", "verify residency"),
    "mixed":     ("#fff8e6", "#c9950c", "mixed — see 1.0a"),
    "pattern":   ("#eef2fb", "#2b6cb0", "pattern proof"),
    "residency": ("#fde8e6", "#c0392b", "excluded — residency"),
    "federation":("#fde8e6", "#c0392b", "excluded — federation"),
    "estate":    ("#fde8e6", "#c0392b", "excluded — Jira/Confluence SoR"),
    "excluded":  ("#fde8e6", "#c0392b", "excluded — no trimming"),
    "target":    ("#f3d27a", "#b8860b", "target — as designed"),
    "target2":   ("#fbe7b3", "#b8860b", "target — reuse-first"),
}
CELL = {2: ("#9fd3a8", "●"), 1: ("#f5d78e", "◐"), 0: ("#f0f0f0", "○")}
GOLD_EDGE = "#b8860b"
MODE = {  # delivery mode of the composed target per L4 (capability-map-v1.6d): fill, letter, is_build
    "S": ("#9fd3a8", "S", False),   # standard — estate as shipped
    "L": ("#fbe7b3", "L", True),    # low code — Power Platform / Copilot Studio
    "P": ("#cfe0f7", "P", True),    # pro code — built
    "G": ("#fde8e6", "G", True),    # gap — bake-off (no component in Annex D)
    "B": ("#e6dcf5", "B", False),   # buy-lite — a product covers the row; procurement, not build
}
COMPOSED_MODE = {"1.1": "G", "1.2": "P", "2.1": "P", "2.2": "P", "2.3": "P", "2.4": "P",
                 "3.1": "L", "3.2": "L", "3.3": "P", "4.1": "P", "4.2": "L", "4.3": "P",
                 "5.1": "P", "5.2": "P", "5.3": "L", "5.4": "P", "5.5": "P", "5.6": "P",
                 "AM": "S", "AU": "S", "RR": "S"}
# Reuse-first rule (note 002): S if the estate ships it; B if a non-excluded product covers it; L only for
# end-user surfaces and event triggering; P for anything touching a line-of-business system or on the data path.
REUSE_MODE = {"1.1": "B", "1.2": "P", "2.1": "P", "2.2": "S", "2.3": "S", "2.4": "P",
              "3.1": "L", "3.2": "L", "3.3": "P", "4.1": "S", "4.2": "L", "4.3": "S",
              "5.1": "L", "5.2": "P", "5.3": "L", "5.4": "P", "5.5": "P", "5.6": "P",
              "AM": "S", "AU": "S", "RR": "S"}
TARGETS = {"target": COMPOSED_MODE, "target2": REUSE_MODE}


def render(out: Path, cols: dict, title: str, subtitle: str, classes: bool) -> None:
    W = 192.0
    LABW, HDRH, RH, GRH = 44.0, 15.5 if classes else 12.5, 3.55, 3.0
    m = 2.2
    ncol = len(cols)
    cw = (W - 2 * m - LABW) / ncol
    groups = []
    for g, _, _ in ROWS:
        if g not in groups:
            groups.append(g)
    body = len(ROWS) * RH + len(groups) * GRH
    H = 9.4 + HDRH + body + 3.0 + 19.6
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, H - 3.0, title, ha="center", va="center", fontsize=18, fontweight="bold", color="#222")
    ax.text(W / 2, H - 6.6, subtitle, ha="center", va="center", fontsize=10.5, color="#777", style="italic")

    # headers
    y = 9.4
    names = list(cols)
    for j, name in enumerate(names):
        status, rat = cols[name]
        fill, edge, lbl = STATUS[status]
        x = m + LABW + j * cw
        gold = status in TARGETS
        ax.add_patch(FancyBboxPatch((x + 0.35, H - y - HDRH), cw - 0.7, HDRH, boxstyle="round,pad=0,rounding_size=0.8",
                                    fc=fill, ec=edge, lw=2.2 if gold else 1.2))
        lines = name.split("\n")
        fs = 9.6 if classes else 9.8
        for k, ln in enumerate(lines):
            ax.text(x + cw / 2, H - y - 2.3 - 2.15 * k, ln, ha="center", va="center", fontsize=min(fs, fs * (cw - 1.4) / (0.88 * max(1, len(ln)))),
                    fontweight="bold", color="#222")
        # status label at the bottom of the header
        ax.text(x + cw / 2, H - y - HDRH + 1.5, lbl, ha="center", va="center", fontsize=min(7.8, 7.8 * (cw - 1.0) / (0.70 * len(lbl))),
                color=edge, style="italic")
    y += HDRH

    # rows
    row_i = 0
    for g in groups:
        ax.add_patch(Rectangle((m, H - y - GRH), W - 2 * m, GRH, fc="#e9e9e9", ec="none"))
        ax.text(m + 1.2, H - y - GRH / 2, g, ha="left", va="center", fontsize=10, fontweight="bold", color="#444")
        y += GRH
        for (gg, rid, rname) in ROWS:
            if gg != g:
                continue
            band = "#fafafa" if row_i % 2 else "white"
            ax.add_patch(Rectangle((m, H - y - RH), W - 2 * m, RH, fc=band, ec="none"))
            ax.text(m + 1.2, H - y - RH / 2, f"{rid}  {rname}", ha="left", va="center", fontsize=10, color="#222")
            for j, name in enumerate(names):
                status, rat = cols[name]
                v = rat[rid]
                x = m + LABW + j * cw
                if status in TARGETS:
                    fc, letter, build = MODE[TARGETS[status][rid]]
                    ax.add_patch(FancyBboxPatch((x + 0.5, H - y - RH + 0.35), cw - 1.0, RH - 0.7, boxstyle="round,pad=0,rounding_size=0.5",
                                                fc=fc, ec=GOLD_EDGE if build else ("#6b46c1" if letter == "B" else "#2f855a"), lw=2.0 if build else 0.8))
                    ax.text(x + cw / 2, H - y - RH / 2 - 0.05, letter, ha="center", va="center", fontsize=9.5, fontweight="bold",
                            color="#5a4300" if build else ("#4c2d8f" if letter == "B" else "#1f5f33"))
                else:
                    fc, sym = CELL[v]
                    ax.add_patch(FancyBboxPatch((x + 0.5, H - y - RH + 0.35), cw - 1.0, RH - 0.7, boxstyle="round,pad=0,rounding_size=0.5",
                                                fc=fc, ec="#bbb", lw=0.5))
                    ax.text(x + cw / 2, H - y - RH / 2 - 0.05, sym, ha="center", va="center", fontsize=10.5, color="#333")
            y += RH
            row_i += 1

    # legend + notes
    y += 3.0
    ax.add_patch(FancyBboxPatch((m, H - y - 19.6), W - 2 * m, 19.6, boxstyle="round,pad=0,rounding_size=1.6",
                                fc="#fafafa", ec="#999", lw=1.2, ls=(0, (2, 2))))
    lx = m + 2.4
    for v, lbl in ((2, "● covers as shipped"), (1, "◐ partial — a slice, or only inside its own store"), (0, "○ none")):
        fc, sym = CELL[v]
        ax.add_patch(FancyBboxPatch((lx, H - y - 3.6), 3.2, 2.4, boxstyle="round,pad=0,rounding_size=0.5", fc=fc, ec="#bbb", lw=0.6))
        ax.text(lx + 4.2, H - y - 2.4, lbl, ha="left", va="center", fontsize=10, color="#222")
        lx += 4.2 + 0.66 * len(lbl) + 3
    lx += 2
    for key, lbl in (("S", "S estate as shipped"), ("B", "B buy-lite product"), ("L", "L low code"), ("P", "P pro code"), ("G", "G gap → bake-off")):
        fc, letter, build = MODE[key]
        ax.add_patch(FancyBboxPatch((lx, H - y - 3.6), 3.2, 2.4, boxstyle="round,pad=0,rounding_size=0.5", fc=fc,
                                    ec=GOLD_EDGE if build else ("#6b46c1" if key == "B" else "#2f855a"), lw=1.8 if build else 0.8))
        ax.text(lx + 4.2, H - y - 2.4, lbl, ha="left", va="center", fontsize=10, color="#222")
        lx += 4.2 + 0.7 * len(lbl) + 4
    notes = [
        "Target columns: the letter is the DELIVERY MODE, not a coverage rating — by construction both targets cover every row. Gold edge = build scope.",
        "'As designed' = Annex D / capability-map-v1.6d. 'Reuse-first' (note 002) = S if the estate ships it · B if a non-excluded product covers it · L only for end-user surfaces and event triggers · P for anything touching a line-of-business system or on the data path.",
        "Reuse-first outcome: 7 S · 1 B · 5 L · 8 P. Differences from the design are the bake-off list — 2.2, 2.3, 4.1, 4.3 shipped by the estate; 1.1 a buy-lite — plus 5.1 as a trigger flow rather than a receiver.",
        "Header colour = verdict against the fabric's own constraints: red = structurally excluded (residency: hosted off-tenant · federation: content moves into the product's store · "
        "estate: requires other systems of record) — a red column is compared for pattern evidence, not sourcing.",
        "Ratings are from product documentation and 2026 launch coverage (docs/fabric/market-scan-2026-09.md), not a live evaluation. Rows are the L4 capabilities of capability-map-v1.6b; "
        "L5 detail is in the scan.",
        "Two verdicts changed against the v1.0 Figure 4: Change Impact Analysis is no longer zero in every column (Swimm, one domain); Work IQ moves the estate from ○ to ● on Expertise Identification.",
        ("Class rating = best member in the class; see 1.0a for the per-product split." if classes else
         "Atlassian's ● on Traceability and Remediation is on Jira/Confluence objects; it is the reference SHAPE for the composed build, not a candidate on an ADO/SharePoint estate."),
    ]
    for i, t in enumerate(notes):
        ax.text(m + 2.4, H - y - 5.6 - 2.05 * i, "•  " + t, ha="left", va="center", fontsize=min(9.4, 9.4 * (W - 2 * m - 6) / (0.56 * len(t))), color="#444")
    fig.savefig(out, dpi=100, facecolor="white"); print(out, f"{int(W*10)}x{int(H*10)}")


def rollup(members):
    return {rid: max(PRODUCTS[mname][1][rid] for mname in members) for rid in IDS}


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    d.mkdir(parents=True, exist_ok=True)
    render(d / "options-view-v1.0a-incumbents.png", PRODUCTS,
           "Options view v1.0a — incumbents against the Knowledge Management capabilities (September 2026)",
           "Replaces Figure 4 · rows = L4 capabilities of capability-map-v1.6b · columns = named products · header = verdict against fabric constraints",
           classes=False)
    render(d / "options-view-v1.0b-provider-classes.png", {c: (s, rollup(mem)) for c, (s, mem) in CLASSES.items()},
           "Options view v1.0b — provider classes against the Knowledge Management capabilities (September 2026)",
           "Replaces Figure 4 · rows = L4 capabilities of capability-map-v1.6b · columns = provider classes (best member) · header = verdict against fabric constraints",
           classes=True)
