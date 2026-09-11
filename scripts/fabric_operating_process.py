"""Documentation Fabric operating process v1.0 (replaces Figure 6) — BPMN on the original three lanes,
activities named by L4 capability with their L5 steps inside.

Colour = relationship (red = uplift, grey = consumed from the estate); border = phase
(solid MVP · dashed Transitional · dotted Target); ◉ = human touchpoint; diamond = gateway.
Connectors are explicit orthogonal waypoints.

    python scripts/fabric_operating_process.py [out.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle

W, H = 248.0, 130.0
UP = ("#fde8e6", "#c0392b")     # uplift
CO = ("#ececec", "#777777")     # consumed
LS = {"mvp": "-", "transitional": (0, (5, 2.5)), "target": (0, (1.5, 2.2))}
CX = [12 + 22 * i for i in range(11)]  # column centres
LANES = [("Owner & steward", 8.0, 40.0, "#f4f1ea"), ("Fabric pipeline (system)", 40.0, 94.0, "#eeeaf7"), ("Consumers", 94.0, 118.0, "#e7f3ec")]
NW, NH_P, NH_S, NH_C = 19.0, 11.0, 13.0, 10.5
YP, YS_A, YS_B, YC = 15.0, 46.0, 66.5, 98.5   # top edges of node rows


def Y(y):  # top-down y to axes y
    return H - y


def node(ax, cx, ytop, w, h, title, idline, l5s, rel, phase, consumes=None, human=False):
    fill, edge = UP if rel == "uplift" else CO
    ax.add_patch(FancyBboxPatch((cx - w / 2, Y(ytop + h)), w, h, boxstyle="round,pad=0,rounding_size=1.0",
                                fc=fill, ec=edge, lw=1.6, ls=LS[phase]))
    tw = w - (5.0 if human else 1.5)
    ax.text(cx + (1.2 if human else 0), Y(ytop + 2.0), title, ha="center", va="center", fontsize=min(10.5, 10.5 * tw / (0.9 * len(title))), fontweight="bold", color="#222")
    ax.text(cx, Y(ytop + 4.0), idline, ha="center", va="center", fontsize=min(7.6, 7.6 * (w - 1.6) / (0.72 * len(idline))), color=edge, fontweight="bold")
    if human:
        ax.text(cx - w / 2 + 1.6, Y(ytop + 1.9), "◉", ha="center", va="center", fontsize=9.5, color=edge)
    y = ytop + 5.9
    for s in l5s:
        ax.text(cx, Y(y), s, ha="center", va="center", fontsize=min(8.0, 8.0 * (w - 1.2) / (0.62 * len(s))), color="#333")
        y += 1.85
    if consumes:
        ax.text(cx, Y(ytop + h - 1.2), consumes, ha="center", va="center", fontsize=min(7.4, 7.4 * (w - 1.2) / (0.6 * len(consumes))), color="#666", style="italic")


def gateway(ax, cx, cy, label):
    d = 3.2
    ax.add_patch(Polygon([(cx, Y(cy - d)), (cx + d, Y(cy)), (cx, Y(cy + d)), (cx - d, Y(cy))], closed=True, fc="#fbe7b3", ec="#c9950c", lw=1.4))
    ax.text(cx, Y(cy + d + 1.6), label, ha="center", va="center", fontsize=7.6, color="#5a4300", style="italic")


def event(ax, cx, cy, kind):
    col = {"start": "#2f855a", "end": "#c0392b", "timer": "#c9950c"}[kind]
    ax.add_patch(Circle((cx, Y(cy)), 1.7, fc="white", ec=col, lw=2.2 if kind != "end" else 3.0))
    if kind == "timer":
        ax.text(cx, Y(cy), "◷", ha="center", va="center", fontsize=8, color=col)


def route(ax, pts, phase="mvp", label=None, lpos=None, color="#444"):
    xs = [p[0] for p in pts]; ys = [Y(p[1]) for p in pts]
    ax.plot(xs[:-1] + [xs[-1]], ys[:-1] + [ys[-1]], color=color, lw=1.1, ls=LS[phase], solid_capstyle="round")
    ax.annotate("", xy=(xs[-1], ys[-1]), xytext=(xs[-2], ys[-2]), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.1, mutation_scale=10, ls=LS[phase]))
    if label:
        lx, ly = lpos if lpos else ((xs[0] + xs[1]) / 2, (pts[0][1] + pts[1][1]) / 2 - 1.2)
        ax.text(lx, Y(ly), label, ha="center", va="center", fontsize=7.2, color="#555", style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))


def main(out: Path) -> None:
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.text(W / 2, Y(3.0), "Operating process v1.0 — one standing pipeline, activities as L4 capabilities with their L5 steps (replaces Figure 6)",
            ha="center", va="center", fontsize=17, fontweight="bold", color="#222")

    # lanes
    for name, y0, y1, fc in LANES:
        ax.add_patch(Rectangle((1.5, Y(y1)), W - 3.0, y1 - y0, fc=fc, ec="#999", lw=1.0))
        ax.add_patch(Rectangle((1.5, Y(y1)), 3.2, y1 - y0, fc="#dcdcdc", ec="#999", lw=1.0))
        ax.text(3.1, Y((y0 + y1) / 2), name, ha="center", va="center", fontsize=9.5, fontweight="bold", color="#333", rotation=90)

    # ---------------- lane 1: owner & steward
    event(ax, CX[0], 11.2, "start")
    node(ax, CX[0], YP, NW, NH_P, "Work in source systems", "consumed · systems of record", ["SharePoint · ADO · EA repository", "Teams · Outlook · design boards"], "consumed", "mvp")
    node(ax, CX[1], YP, NW, NH_P, "Dispose correction", "5.6 Remediation · Target", ["accept / reject the filed proposal", "in the system's own review idiom"], "uplift", "target", human=True)
    node(ax, CX[2], YP, NW, NH_P, "Curate vocabulary", "1.1 Concept Lifecycle", ["Candidate Term Intake", "Editorial Workflow · Deprecation"], "uplift", "mvp", human=True)
    node(ax, CX[4], YP, NW, NH_P, "Work orphan queue", "2.4 Orphan Management", ["associate · mark non-delivery", "honest orphans over guessed edges"], "uplift", "mvp", human=True)
    node(ax, CX[5], YP, NW, NH_P, "Confirm association", "2.4 Association Confirmation", ["one-tap card · tag once", "Message Delivery (Teams) consumed"], "uplift", "mvp", human=True)
    node(ax, CX[9], YP, NW, NH_P, "Adjudicate duplicate", "3.3 Merge Adjudication", ["merge · keep both · supersede"], "uplift", "transitional", human=True)
    node(ax, CX[10], YP, NW, NH_P, "Review & approve", "3.2 Knowledge Review · owner", ["Approval · Rework Handling", "Review Escalation (timer → manager)"], "uplift", "mvp", human=True)

    # ---------------- lane 2 row A
    node(ax, CX[0], YS_A, NW, NH_S, "Change Detection", "5.1 · MVP", ["Event Capture", "Event Filtering (allow-list)", "Change Attribution → loop guard"], "uplift", "mvp", consumes="Graph notifications · ADO hooks")
    node(ax, CX[2], YS_A, NW, NH_S, "Catalog Management", "1.2 · MVP", ["Artifact Identification (IRI)", "Location Reference (pointer)", "Lifecycle State := pending"], "uplift", "mvp", consumes="no content — metadata only")
    node(ax, CX[3], YS_A, NW, NH_S, "Knowledge Classification", "2.2 · MVP", ["Type Classification (AI-suggested)", "Owner · Sensitivity Resolution", "Concept Linking"], "uplift", "mvp", consumes="owner map · Purview label (looked up)")
    node(ax, CX[4], YS_A, NW, NH_S, "Traceability Management", "2.4 · MVP", ["Delivery Association (rungs 1–3)", "Reference Extraction", "edges carry provenance"], "uplift", "mvp", consumes="ADO links · Work IQ signals (rung 3)")
    gateway(ax, CX[5], YS_A + NH_S / 2, "edge ≥ threshold?")
    node(ax, CX[6], YS_A, NW, NH_S, "Change Impact Analysis", "5.2 · Transitional · MVP passes through", ["Impact Chain Determination", "Affected Artifact Identification", "Impact Scope Bounding"], "uplift", "transitional", consumes="trusted edges only (C · X · H)")
    node(ax, CX[7], YS_A, NW, NH_S, "Content Synthesis", "2.1 · MVP", ["Template Management", "Draft Generation", "Draft Regeneration (on change)"], "uplift", "mvp", consumes="writes draft → SharePoint (consumed)")
    node(ax, CX[8], YS_A, NW, NH_S, "Duplicate Management", "3.3 · Transitional · MVP routes no", ["Overlap Detection", "(embeddings vs published corpus)"], "uplift", "transitional")
    gateway(ax, CX[9], YS_A + NH_S / 2, "overlap?")

    # ---------------- lane 2 row B
    node(ax, CX[1], YS_B, NW, NH_S, "Remediation Management", "5.6 · Target · button-first late Trans.", ["Correction Drafting", "Correction Proposal Filing", "Mechanical Correction (whitelist)"], "uplift", "target", consumes="draft-mode writeback via Graph / ADO")
    event(ax, CX[2] + 3.0, YS_B + NH_S / 2, "timer")
    node(ax, CX[3] + 2.0, YS_B, NW, NH_S, "Catalog Reconciliation", "5.5 · Transitional · periodic sweep", ["Drift Detection (catalog vs source)", "Drift Resolution"], "uplift", "transitional", consumes="Graph delta queries")
    node(ax, CX[6], YS_B, NW, NH_S, "Subscription Management", "5.3 · Transitional", ["Following", "Notification (affected owners)", "Digest Compilation"], "uplift", "transitional")
    node(ax, CX[8], YS_B, NW, NH_S, "Republication", "5.4 · MVP wiki · Trans. rebuild", ["Projection Regeneration (ADO wiki)", "Index Regeneration"], "uplift", "mvp", consumes="ADO wiki write (consumed)")
    node(ax, CX[10], YS_B, NW, NH_S, "Version Management", "2.3 · MVP", ["Baseline Management", "Version Confirmation", "Lifecycle State := published"], "uplift", "mvp", consumes="SharePoint version (consumed)")
    ax.text(CX[10] + NW / 2, Y(YS_B + NH_S + 1.6), "Audit Management (consumed · Purview): every step above is recorded", ha="right", va="center", fontsize=7.6, color="#666", style="italic")

    # ---------------- lane 3
    ax.add_patch(Rectangle((6.0, Y(97.0)), W - 8.0, 2.4, fc="#dcdcdc", ec="#777", lw=0.8))
    ax.text(W / 2, Y(95.8), "Access Management (consumed · Entra + Purview labels) — the source decides at read time; identical trimming, principal identity and audit for people and agents (NFR-8)", ha="center", va="center", fontsize=8.0, color="#333")
    event(ax, CX[0], YC + NH_C / 2, "end")
    node(ax, CX[6], YC, NW, NH_C, "Tracker digest", "consumed · Message Delivery", ["periodic watched-set digest", "no email"], "consumed", "transitional")
    node(ax, CX[7], YC, NW, NH_C, "Expertise Identification", "4.3 · Target", ["Authorship Analysis", "Ownership Analysis"], "uplift", "target")
    node(ax, CX[8], YC, NW, NH_C, "Knowledge Retrieval", "4.1 · MVP", ["Knowledge Search", "Relationship Navigation"], "uplift", "mvp", consumes="Copilot · Claude · MCP door (consumed)")
    node(ax, CX[9], YC, NW, NH_C, "Knowledge Recommendation", "4.2 · Transitional", ["Reuse Suggestion", "Related Artifact Retrieval"], "uplift", "transitional")
    node(ax, CX[10], YC, NW, NH_C, "Records Retention", "consumed · Purview · Target", ["retention policy · disposition", "on the published corpus"], "consumed", "target")

    # ---------------- connectors (orthogonal waypoints; y in top-down units)
    yA = YS_A + NH_S / 2; yB = YS_B + NH_S / 2; yPb = YP + NH_P; yL1 = 31.0; yMid = 62.0; yMid2 = 63.8
    route(ax, [(CX[0], 12.9), (CX[0], YP)])                                            # start → work
    route(ax, [(CX[0], yPb), (CX[0], YS_A)], label="change event", lpos=(CX[0] + 7.5, 40.5))
    route(ax, [(CX[0] + NW / 2, yA), (CX[2] - NW / 2, yA)])                              # S1 → S2
    route(ax, [(CX[2] + NW / 2, yA), (CX[3] - NW / 2, yA)])                              # S2 → S3
    route(ax, [(CX[3] + NW / 2, yA), (CX[4] - NW / 2, yA)])                              # S3 → S4
    route(ax, [(CX[4] + NW / 2, yA), (CX[5] - 3.2, yA)])                                 # S4 → G1
    route(ax, [(CX[5] + 3.2, yA), (CX[6] - NW / 2, yA)], label="yes", lpos=(CX[5] + 6.5, yA - 1.4))
    route(ax, [(CX[5], yA - 3.2), (CX[5], yPb)], label="no → ask", lpos=(CX[5] + 4.6, 38.0))          # G1 → P2
    route(ax, [(CX[5], yPb), (CX[5], yL1), (CX[6] - 4.0, yL1), (CX[6] - 4.0, YS_A)], label="confirmed", lpos=(CX[5] + 8.5, yL1 - 1.2))  # P2 → S5
    route(ax, [(CX[5] - NW / 2, YP + NH_P / 2), (CX[4] + NW / 2, YP + NH_P / 2)], label="no answer", lpos=(CX[4] + 11, YP - 1.4))  # P2 → P6
    route(ax, [(CX[4], YS_A), (CX[4], yPb)], phase="mvp", label="rung 2 yields nothing", lpos=(CX[4] - 8.5, 40.5))  # S4 → P6
    route(ax, [(CX[2], yPb), (CX[2], yL1), (CX[3], yL1), (CX[3], YS_A)], label="concept schemes", lpos=(CX[2] + 11, yL1 - 1.2))  # P5 → S3
    route(ax, [(CX[6] + NW / 2, yA), (CX[7] - NW / 2, yA)])                              # S5 → S6
    route(ax, [(CX[7] + NW / 2, yA), (CX[8] - NW / 2, yA)])                              # S6 → S7
    route(ax, [(CX[8] + NW / 2, yA), (CX[9] - 3.2, yA)])                                 # S7 → G2
    route(ax, [(CX[9], yA - 3.2), (CX[9], yPb)], phase="transitional", label="yes", lpos=(CX[9] + 3.0, 42.5))  # G2 → P3
    route(ax, [(CX[9] + 3.2, yA), (CX[10], yA), (CX[10], yPb)], label="no → card", lpos=(CX[10] + 6.5, 42.5))  # G2 → P4
    route(ax, [(CX[9] + NW / 2, YP + NH_P / 2), (CX[10] - NW / 2, YP + NH_P / 2)], phase="transitional")  # P3 → P4
    route(ax, [(CX[10], yPb), (CX[10], YS_B)], label="approve", lpos=(CX[10] + 6.0, 44.0))  # P4 → S9 (passes empty c10 row A)
    route(ax, [(CX[10] - NW / 2, YP + 2.0), (CX[7] + 6.0, YP + 2.0) if False else (CX[10] - NW / 2 - 1.0, YP + 2.0), (CX[10] - NW / 2 - 1.0, 9.6), (CX[7], 9.6), (CX[7], YP - 0.2)] if False else
          [(CX[10] - 2.0, yPb), (CX[10] - 2.0, yL1 + 3.0), (CX[7] + 3.0, yL1 + 3.0), (CX[7] + 3.0, YS_A)], phase="mvp", label="rework → re-synthesise", lpos=(CX[8] + 11, yL1 + 1.8))
    route(ax, [(CX[10] - NW / 2, yB), (CX[8] + NW / 2, yB)], label="published", lpos=(CX[9], yB - 1.4))  # S9 → S10
    route(ax, [(CX[8] - NW / 2, yB), (CX[6] + NW / 2, yB)])                              # S10 → S11
    route(ax, [(CX[6], YS_A + NH_S), (CX[6], YS_B)], phase="transitional", label="affected owners", lpos=(CX[6] + 9.0, yMid))  # S5 → S11
    route(ax, [(CX[6] - 5.0, YS_A + NH_S), (CX[6] - 5.0, yMid - 1.5), (CX[1], yMid - 1.5), (CX[1], YS_B)], phase="target", label="draft the fix (button-first)", lpos=(CX[3] + 8, yMid - 2.8))  # S5 → S13
    route(ax, [(CX[1], YS_B), (CX[1], yPb)], phase="target", label="proposal filed", lpos=(CX[1] + 7.0, 42.0))  # S13 → P7 (passes empty c1 row A)
    route(ax, [(CX[2] + 4.7, yB), (CX[3] + 2.0 - NW / 2, yB)], phase="transitional")     # timer → S12
    route(ax, [(CX[3] + 2.0, YS_B), (CX[3] + 2.0, yMid2), (CX[2] + 2.0, yMid2), (CX[2] + 2.0, YS_A + NH_S)], phase="transitional", label="drift → catalog", lpos=(CX[3] + 6.0, yMid2 + 1.4))  # S12 → S2
    route(ax, [(CX[8], YS_B + NH_S), (CX[8], YC)], label="index", lpos=(CX[8] + 4.0, 92.0))   # S10 → C1
    route(ax, [(CX[6], YS_B + NH_S), (CX[6], YC)], phase="transitional", label="digests", lpos=(CX[6] + 5.0, 92.0))  # S11 → C4
    route(ax, [(CX[10], YS_B + NH_S), (CX[10], YC)], phase="target")                      # S9 → retention
    route(ax, [(CX[8] - NW / 2, YC + NH_C / 2), (CX[7] + NW / 2, YC + NH_C / 2)], phase="target")   # C1 ↔ C3 (expertise from catalog)
    route(ax, [(CX[8], YC + NH_C), (CX[8], 112.0), (CX[0], 112.0), (CX[0], YC + NH_C / 2 + 1.7)])   # C1 → end
    # loop guard annotation
    ax.text(6.0, Y(YS_A + NH_S + 2.0), "loop guard: fabric-originated writes are tagged", ha="left", va="center", fontsize=7.2, color="#c0392b", style="italic")
    ax.text(6.0, Y(YS_A + NH_S + 3.9), "and dropped here — they never re-trigger the pipeline", ha="left", va="center", fontsize=7.2, color="#c0392b", style="italic")

    # legend
    ly = 121.0
    lx = 6.0
    for fill, edge, lbl in (UP + ("UPLIFT — fabric-owned capability (L4 · L5 inside)",), CO + ("CONSUMED — estate capability, used as shipped",)):
        ax.add_patch(FancyBboxPatch((lx, Y(ly + 2.6)), 3.4, 2.6, boxstyle="round,pad=0,rounding_size=0.5", fc=fill, ec=edge, lw=1.4))
        ax.text(lx + 4.4, Y(ly + 1.3), lbl, ha="left", va="center", fontsize=9.2, color="#222"); lx += 4.4 + 0.66 * len(lbl) + 6
    for ph, lbl in (("mvp", "solid = MVP"), ("transitional", "dashed = Transitional"), ("target", "dotted = Target")):
        ax.plot([lx, lx + 5.5], [Y(ly + 1.3)] * 2, color="#444", lw=1.4, ls=LS[ph])
        ax.text(lx + 6.6, Y(ly + 1.3), lbl, ha="left", va="center", fontsize=9.2, color="#222"); lx += 6.6 + 0.66 * len(lbl) + 6
    ax.text(lx + 2, Y(ly + 1.3), "◉ human touchpoint   ◇ gateway   ◷ timer   ○ start / ● end", ha="left", va="center", fontsize=9.2, color="#222")
    ax.text(6.0, Y(ly + 5.4), "Two human touchpoints by design (owner review, steward adjudication) plus the one-tap association card; agents and pipeline propose, owners and stewards dispose. Same lanes as Figure 6 v1.0; activities are now L4 capabilities of capability-map-v1.6b.",
            ha="left", va="center", fontsize=8.6, color="#555", style="italic")
    fig.savefig(out, dpi=100, facecolor="white"); print(out, f"{int(W*10)}x{int(H*10)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/operating-process-v1.0.png"))
