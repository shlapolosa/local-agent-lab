"""POC physical architecture views — the lab as-is and the to-be with the fabric's additions.

  poc-physical-as-is-v1.0.png
  poc-physical-to-be-v1.0.png   additions in red, changed in amber, unchanged in grey/blue

    python scripts/fabric_poc_physical.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

NEW = ("#fde8e6", "#c0392b"); CHG = ("#fbe7b3", "#c9950c"); OLD = ("#eeeeee", "#777"); EXT = ("#e7f3ec", "#2f855a"); GW = ("#cfe0f7", "#2b6cb0"); STORE = ("#e6dcf5", "#6b46c1")


def box(ax, H, x, y, w, h, fc, ec, lw=1.2, ls="-", r=0.9):
    ax.add_patch(FancyBboxPatch((x, H - y - h), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls))


def t(ax, H, x, y, s, fs=8.2, **kw):
    kw.setdefault("ha", "center"); kw.setdefault("va", "center"); kw.setdefault("color", "#222")
    ax.text(x, H - y, s, fontsize=fs, **kw)


def fit(fs, w, s, k=0.66):
    return min(fs, fs * (w - 1.2) / (k * max(1, len(s))))


def node(ax, H, x, y, w, h, title, lines, col, ls="-"):
    fc, ec = col
    box(ax, H, x, y, w, h, fc, ec, 1.4 if col in (NEW, CHG) else 1.0, ls)
    t(ax, H, x + w / 2, y + 2.0, title, fit(9.2, w, title, 0.8), fontweight="bold")
    for i, ln in enumerate(lines):
        t(ax, H, x + w / 2, y + 4.2 + 2.0 * i, ln, fit(7.2, w, ln, 0.62), color="#333")


def zone(ax, H, x, y, w, h, title, fc="#fafafa", ec="#999"):
    box(ax, H, x, y, w, h, fc, ec, 1.4, r=1.4)
    t(ax, H, x + 2.0, y + 2.4, title, 10.5, ha="left", fontweight="bold", color="#333")


def arrow(ax, H, x0, y0, x1, y1, col="#444", ls="-"):
    ax.annotate("", xy=(x1, H - y1), xytext=(x0, H - y0), arrowprops=dict(arrowstyle="-|>", color=col, lw=1.0, ls=ls, mutation_scale=9))


def render(out: Path, tobe: bool) -> None:
    W, H = 200.0, 121.0
    fig = plt.figure(figsize=(W / 10, H / 10), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    t(ax, H, W / 2, 3.0, ("POC physical architecture — TO-BE: the lab plus the fabric (additions red, changed amber)" if tobe else
                          "POC physical architecture — AS-IS: the local agentic lab today"), 16, fontweight="bold")
    t(ax, H, W / 2, 6.4, "one Python image, role by command · every agent call and every tool call crosses the gateway · one trace per run · workloads hold no store credential", 9, color="#777", style="italic")

    # ---------------- external systems (top)
    zone(ax, H, 2, 9, 196, 17, "EXTERNAL — systems of record, identity, models (no lab code runs here)", "#f4f9f5", "#2f855a")
    ext = [("Microsoft 365 tenant", ["SharePoint · Teams · Outlook", "via Microsoft Graph"], EXT),
           ("Azure DevOps", ["work items · service hooks · wiki"], NEW if tobe else OLD),
           ("ADOIT (EA repository)", ["hosted CE · REST reads", "file import for writes"], EXT),
           ("Entra ID", ["one app registration per agent", "MSAL client credentials"], EXT),
           ("Model providers", ["Ollama Cloud · Anthropic", "reached only via the gateway"], EXT),
           ("Neon Postgres", ["LiteLLM keys/spend · artifacts", "reference corpus" + (" · fabric tables" if tobe else "")], STORE if not tobe else CHG),
           ("Speech provider", ["transcription behind speech-mcp"], EXT),
           ("GitHub + GHCR", ["CI builds the image · CD deploys", "sha-tagged, immutable"], EXT)]
    n = len(ext); w = (196 - 4 - 1.5 * (n - 1)) / n
    for i, (nm, ls_, col) in enumerate(ext):
        node(ax, H, 4 + i * (w + 1.5), 13.0, w, 11.0, nm, ls_, col, ls=(0, (4, 2)) if (tobe and nm == "Azure DevOps") else "-")

    # ---------------- substrate zone
    zone(ax, H, 2, 29, 196, 56, "SUBSTRATE — the shared plane (Railway services in the cloud tier; lab.sh processes locally)", "#f3f1fb", "#6b46c1")
    node(ax, H, 4, 34, 60, 13, "Gateway — LiteLLM :4000", ["virtual keys · teams · per-tool ACLs · spend", "custom_auth (Entra JWT) · PII guardrail · auto router", "MCP registry: every server below is registered here"], GW)
    node(ax, H, 66, 34, 40, 13, "Redis 7", ["workflow:requests · workflow:finished · approvals:*", "consumer groups · idempotency (SET NX)"] + (["fabric:events (ArtifactChanged)"] if tobe else []), CHG if tobe else OLD)
    node(ax, H, 108, 34, 42, 13, "Jaeger (OTel)", ["one trace per run: process → gateway → MCP", "audit trail; W3C traceparent everywhere"], OLD)
    node(ax, H, 152, 34, 44, 13, "Review app :8501 + channels", ["Submit · Runs · Review modes", "Teams adaptive cards · Telegram"] + (["+ association card · draft review"] if tobe else []), CHG if tobe else OLD)
    # MCP servers row
    mcps = [("adoit-mcp :9100", ["alias ea_mcp", "EA repository port"], OLD),
            ("semantic-mcp :9200", ["vocabularies · SKOS schemes", "SPARQL · named graphs"] + (["+ fabric ontology · rungs"] if tobe else []), CHG if tobe else OLD),
            ("storage-mcp :9300", ["read-only by art:// ref", "content by reference"], OLD),
            ("workflow-mcp :9400", ["<process>_submit/status/result", "approvals_* · /api REST"] + (["+ change_to_adr"] if tobe else []), CHG if tobe else OLD),
            ("graph-mcp :9500", ["alias collab_mcp", "Graph: drives, meetings, put"], OLD),
            ("speech-mcp :9600", ["alias speech_mcp"], OLD),
            ("reference-mcp :9700", ["governed corpus · pins", "vector search (nomic)"], OLD),
            ("decision / valuation", [":9800 · :9900", "CAFÉ derivations · cost"], OLD)]
    if tobe:
        mcps += [("fabric-mcp :10000", ["alias fabric_mcp", "catalog · graph · facade tools"], NEW),
                 ("ado-mcp :10100", ["alias work_mcp", "work items · hooks → events"], NEW)]
    n = len(mcps); w = (196 - 4 - 1.2 * (n - 1)) / n
    for i, (nm, ls_, col) in enumerate(mcps):
        node(ax, H, 4 + i * (w + 1.2), 50.0, w, 12.5, nm, ls_, col)
    t(ax, H, 100, 64.5, "every MCP server: Bearer MCP_SHARED_SECRET · traceparent extracted · registered in litellm-config.yaml mcp_servers · granted per team", 7.6, color="#4c2d8f", style="italic")
    # long-lived substrate consumers
    subs = [("continuations", ["approval → next process"], OLD), ("meeting-notifier", ["workflow:finished → webhook"], OLD), ("usecase-notifier", ["finished → chat"], OLD)]
    if tobe:
        subs += [("fabric-projector", ["published → Markdown → collab_put", "optional Obsidian vault"], NEW), ("fabric-reconciler", ["timer → drift → fabric:events"], NEW)]
    n = len(subs); w = (120 - 1.2 * (n - 1)) / n
    for i, (nm, ls_, col) in enumerate(subs):
        node(ax, H, 4 + i * (w + 1.2), 67.5, w, 10.0, nm, ls_, col)
    node(ax, H, 128, 67.5, 68, 10.0, "Upload store (S3 bucket / Postgres locally)", ["art://<id>/<name> refs · read only through storage-mcp", "workloads never hold its credential"], STORE)
    t(ax, H, 100, 79.6, "Railway: one image (ghcr, sha-<short>), role by start command · release = N pulls · substrate images / versions verify the pin", 7.6, color="#4c2d8f", style="italic")
    t(ax, H, 100, 82.4, "Locally: lab.sh up starts the same roles as processes (brew Redis, native Jaeger, MCP servers, gateway, review app, channels)", 7.6, color="#4c2d8f", style="italic")

    # ---------------- workloads zone
    zone(ax, H, 2, 88, 196, 24, "WORKLOADS — one long-lived host per process (Agent Framework workflow, governed_run) · MCP clients only · reach the substrate over the network", "#fff8f0", "#c0392b")
    wls = [("wf-visio", ["visio_to_archimate", "BA + Architect agents"], OLD),
           ("wf-meeting-transcript", ["meeting_to_transcript", "meeting-agent"], OLD),
           ("wf-meeting-minutes", ["transcript_to_minutes", "minutes-agent"], OLD),
           ("wf-usecase-*", ["screening · design", "investment · provisioning"], OLD)]
    if tobe:
        wls += [("wf-fabric", ["change_to_adr (ProcessSpec)", "classifier + synthesis agents", "consumer of fabric:events"], NEW)]
    n = len(wls); w = (196 - 4 - 1.5 * (n - 1)) / n
    for i, (nm, ls_, col) in enumerate(wls):
        node(ax, H, 4 + i * (w + 1.5), 93.0, w, 13.0, nm, ls_, col)
    t(ax, H, 100, 109.4, "identity per agent: MSAL JWT → gateway maps to its virtual key → spend per key · tools by the identity holding the grant · OTel service name per process", 7.6, color="#7a1f1f", style="italic")

    # ---------------- flows (kept in the gap between zones so they cross no box)
    arrow(ax, H, 92, 88.0, 92, 85.2, "#6b46c1", (0, (3, 2))); t(ax, H, 90.5, 86.6, "Redis streams (requests · events · approvals)", 7.0, ha="right", color="#6b46c1", style="italic")
    arrow(ax, H, 108, 88.0, 108, 85.2, "#c0392b"); t(ax, H, 109.5, 86.6, "every LLM and MCP call → gateway → server", 7.0, ha="left", color="#c0392b", style="italic")
    arrow(ax, H, 34, 29.0, 34, 24.0, "#2f855a"); t(ax, H, 36, 27.0, "Graph · ADO · ADOIT · models — the adapters hold the credentials", 7.0, ha="left", color="#2f855a", style="italic")

    # legend
    ly = 114.5; lx = 4
    for col, lbl in ((OLD, "unchanged"), (CHG, "changed for the POC"), (NEW, "new for the POC"), (EXT, "external system"), (STORE, "store"), (GW, "gateway")):
        box(ax, H, lx, ly, 3.2, 2.4, col[0], col[1], 1.0, r=0.5)
        t(ax, H, lx + 4.2, ly + 1.2, lbl, 8.2, ha="left"); lx += 4.2 + 0.62 * len(lbl) + 5
    fig.savefig(out, dpi=100, facecolor="white"); print(out)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric")
    render(d / "poc-physical-as-is-v1.0.png", tobe=False)
    render(d / "poc-physical-to-be-v1.0.png", tobe=True)
