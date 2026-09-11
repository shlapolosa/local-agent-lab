"""drawio_cafe.py — render CAFÉ M5 logical reference architectures (per CAFE_Framework v0.5).

Imports drawio_c4.C4Diagram as the layout/router engine. This module is the CAFÉ adapter:
maps an agent archetype (A1–A8) to the M5 zones + M4-catalogued components + canonical typed edges,
satisfying the interlock (closed component set; no M5 component absent from M4).

Usage:
    python3 drawio_cafe.py --archetype A2 --out ./cafe-ra-out/
    python3 drawio_cafe.py --all --out ./cafe-ra-out/
"""
from __future__ import annotations
import argparse, os, sys, json
from pathlib import Path

# Import the engine (drawio-c4). Search several locations so the skill works in three layouts:
#   1. Bundled in a package (drawio-c4 lives as a sibling of this file's parent folder)
#   2. Installed under ~/.claude/skills/ (drawio-c4 is a sibling skill)
#   3. Explicit Claude Code install path (legacy)
_SCRIPT_DIR = Path(__file__).resolve().parent
_ENGINE_CANDIDATES = [
    _SCRIPT_DIR,                                             # bundled copy (self-contained skill)
    _SCRIPT_DIR.parent / "drawio-c4",                        # package sibling: skills/drawio-c4/
    Path("/mnt/skills/user/drawio-c4"),                      # Claude.ai user skills dir
    Path("/mnt/skills/public/drawio-c4"),                    # Claude.ai public skills dir
    Path.home() / ".claude" / "skills" / "drawio-c4",        # Claude Code skills dir
]
_engine_dir = next((c for c in _ENGINE_CANDIDATES if (c / "drawio_c4.py").exists()), None)
if _engine_dir is None:
    raise ImportError(
        "drawio-c4 engine not found. Looked in:\n  "
        + "\n  ".join(str(c) for c in _ENGINE_CANDIDATES)
        + "\nInstall drawio-c4 alongside drawio-cafe (see INSTALL.md)."
    )
sys.path.insert(0, str(_engine_dir))
from drawio_c4 import C4Diagram  # type: ignore

# ----------------------------------------------------------------------
# CAFÉ palette (zones + edge types — CAFÉ-specific overlay on the engine)
# ----------------------------------------------------------------------
EDGE_STYLES = {
    "request":   "strokeColor=#1A1A1A;endArrow=block;strokeWidth=1.6;",
    "policy":    "strokeColor=#B89500;dashed=1;dashPattern=6 4;endArrow=block;",
    "knowledge": "strokeColor=#0B7E63;endArrow=block;strokeWidth=1.6;",
    "tool":      "strokeColor=#C4651F;endArrow=block;strokeWidth=1.6;",
    "data":      "strokeColor=#2D5B9E;endArrow=block;",
    "event":     "strokeColor=#777777;dashed=1;dashPattern=6 6;endArrow=open;",
    "identity":  "strokeColor=#7A4FB5;dashed=1;dashPattern=2 4;endArrow=open;",
    "observe":   "strokeColor=#4F8A37;dashed=1;dashPattern=2 4;endArrow=open;",
}
JUNCTION_COLORS = {k: s.split("strokeColor=")[1].split(";")[0] for k, s in EDGE_STYLES.items()}

# Zone definitions — one row per band, ordered top-to-bottom; mirrors M5_ZONES in the HTML.
# Dark palette matches the HTML (CAFE_Artifacts_Visualisation.html bg #0b0d12).
# Each: (zid, label, stroke, fill, comp_fill, security_text).
ZONES = [
    ("z_exp",  "Experience & Channels",              "#5A82C4", "#20304F", "#324674",
        "channels — users & system consumers"),
    ("z_edge", "Edge & AI Gateway",                  "#4AA0C4", "#16384A", "#245267",
        "🔒 G01 · G02 · G06 · G08 enforcement"),
    ("z_cog",  "Cognitive Plane",                    "#9A6FD0", "#2F1D47", "#3F2A5D",
        "🔒 G01 manifests · G07 handoffs · G08 budgets"),
    ("z_knw",  "Knowledge & Semantic",               "#3FAE8E", "#0E3B30", "#145843",
        "🔒 G06 grounding contract — permission-trimmed"),
    ("z_mod",  "Models",                             "#D09A4E", "#3F2A0C", "#5D3E15",
        "via APIM gateway — policy + metering"),
    ("z_too",  "Tools & Integration",                "#4FAAB8", "#093840", "#145560",
        "🔒 G02 scoped · G04 M4-catalogued · G09 HITL"),
    ("z_data", "Data Plane",                         "#5A82C4", "#20304F", "#324674",
        "systems of record — read + write"),
    ("z_ext",  "External Systems",                   "#9A7A5A", "#322820", "#463727",
        "always mediated by APIM + scoped credentials"),
]

# Cross-cutting rails — drawn as zones too, but conceptually "rails" alongside.
TOP_RAIL = ("z_ident", "Identity & Trust (cross-cutting)", "#C0526E", "#34141E", "#4D2030",
            "🔒 G03 Agent ID · G04 admission · G14 Agent 365 inventory")
BOTTOM_RAIL = ("z_obs", "Observability · Cost · Eval (cross-cutting)", "#6AAA60", "#1B321A", "#2A4A28",
               "🔒 G10 eval gates deploy · cost metering · SIEM correlate")
PLAT_ZONE = ("z_plat", "Platform Foundation", "#6A7488", "#23272F", "#353A45",
             "Azure landing zone · WAF AI pillars · networking")

# ----------------------------------------------------------------------
# CAFÉ components catalogue (matches M5_COMPS in CAFE_Artifacts_Visualisation.html)
# Each: (cid, zone, title, desc, archetypes-set)
# ----------------------------------------------------------------------
ALL = {"A1","A2","A3","A4","A5","A6","A7","A8"}

COMPS = [
    # ---- Experience ----
    ("c_copilot",   "z_exp",  "M365 Copilot",        "Teams · chat",                    {"A1","A7"}),
    ("c_web",       "z_exp",  "Web / Power Apps",    "portal · SPA",                    {"A2","A3","A5"}),
    ("c_mobile",    "z_exp",  "Mobile / Voice",      "apps · Voice Live",               {"A2","A3","A6"}),
    ("c_system",    "z_exp",  "System",              "REST · webhooks · A2A",           {"A2","A3","A4","A5","A6","A8"}),
    ("c_portal",    "z_exp",  "External portal",     "partner · customer",              {"A2","A3"}),
    # ---- Edge ----
    ("c_fdwaf",     "z_edge", "Front Door + WAF",    "edge · DDoS",                     {"A2","A3","A5"}),
    ("c_apim",      "z_edge", "APIM — AI Gateway",   "token limit · cache · safety",    ALL),
    ("c_chan",      "z_edge", "Channel adapters",    "Agents SDK · Bot · Event Grid",   {"A1","A2","A3","A6","A7","A8"}),
    ("c_mcpedge",   "z_edge", "MCP edge",            "registry · OAuth (G04)",          {"A2","A3","A4","A5","A6","A8"}),
    # ---- Cognitive ----
    ("c_dec",       "z_cog",  "Declarative agent",   "M365 Copilot",                    {"A1","A7"}),
    ("c_cps",       "z_cog",  "Copilot Studio engine","custom engine",                  {"A2","A3"}),
    ("c_foundry",   "z_cog",  "Foundry agents",      "prompt · workflow · hosted",      {"A2","A3","A4","A5","A6","A8"}),
    ("c_agf",       "z_cog",  "Agent Framework",     "orchestration · manifests (G01)", {"A2","A3","A4","A5","A6","A8"}),
    ("c_manifest",  "z_cog",  "Manifest & supply chain","DevOps · GitHub Actions (G01)",{"A2","A3","A4","A5","A6","A8"}),
    # ---- Knowledge ----
    ("c_fiq",       "z_knw",  "Foundry IQ",          "federated · real-time-pull",      {"A1","A2","A3","A5","A6","A8"}),
    ("c_wiq",       "z_knw",  "Work IQ",             "M365 context",                    {"A1","A2","A5"}),
    ("c_search",    "z_knw",  "Azure AI Search",     "vector · ranker",                 {"A1","A2","A3","A5","A6","A8"}),
    ("c_fab",       "z_knw",  "Fabric IQ",           "ontology · glossary",             {"A5"}),
    ("c_pglossary", "z_knw",  "Purview glossary",    "semantic layer",                  {"A1","A2","A5"}),
    ("c_ksrc",      "z_knw",  "Knowledge sources",   "SP · OneLake · Blob · Web · MCP", ALL),
    # ---- Models ----
    ("c_modcat",    "z_mod",  "Foundry model catalog","GPT · Claude · Llama",           ALL),
    ("c_modloc",    "z_mod",  "Local / fine-tuned",  "PTU · SLM",                       {"A2","A3","A5","A6"}),
    ("c_modrem",    "z_mod",  "Remote (via APIM)",   "Anthropic · OpenAI",              {"A2","A3","A4","A5"}),
    # ---- Tools ----
    ("c_mcp",       "z_too",  "MCP servers",         "Dataverse · GitHub (G02)",        {"A2","A3","A4","A5","A6"}),
    ("c_dvskill",   "z_too",  "Dataverse skills",    "business skills",                 {"A2","A3"}),
    ("c_pa",        "z_too",  "Power Automate",      "approvals (G09)",                 {"A2","A3","A6"}),
    ("c_intg",      "z_too",  "Integration",         "Service Bus · Event Hubs",        {"A2","A3","A6"}),
    # ---- Data ----
    ("c_dv",        "z_data", "Dataverse",           "operational",                     {"A2","A3","A6"}),
    ("c_sql",       "z_data", "Azure SQL",           "operational",                     {"A2","A3","A6"}),
    ("c_onelake",   "z_data", "OneLake",             "analytical",                      {"A1","A5"}),
    ("c_sp",        "z_data", "SharePoint",          "content",                         {"A1","A2","A5","A7"}),
    ("c_state",     "z_data", "Agent state",         "Cosmos · Redis",                  {"A4","A6"}),
    # ---- External ----
    ("c_erp",       "z_ext",  "ERP",                 "SAP · D365 F&O",                  {"A2","A3","A6"}),
    ("c_crm",       "z_ext",  "CRM",                 "D365 · Salesforce",               {"A2","A3","A6"}),
    ("c_itsm",      "z_ext",  "ITSM",                "ServiceNow",                      {"A2","A3","A6"}),
    ("c_saas",      "z_ext",  "SaaS / Web",          "partner APIs · Bing",             {"A2","A3","A5","A6"}),
    ("c_op",        "z_ext",  "On-prem gateway",     "ExpressRoute",                    {"A2","A3","A6"}),
    ("c_hris",      "z_ext",  "HRIS / Identity",     "Workday · SuccessFactors",        {"A2","A3","A6"}),
    ("c_a2a",       "z_ext",  "External agents (A2A)","partner agents",                 {"A4","A8"}),
    # ---- Identity rail (top) ----
    ("c_entra",     "z_ident","Microsoft Entra ID",  "users · workloads",               ALL),
    ("c_agentid",   "z_ident","Entra Agent ID",      "blueprints",                      {"A2","A3","A4","A6"}),
    ("c_ca",        "z_ident","Conditional Access",  "adaptive",                        ALL),
    ("c_kv",        "z_ident","Key Vault",           "secrets",                         ALL),
    ("c_purview",   "z_ident","Purview",             "catalog · DLP",                   ALL),
    ("c_citadel",   "z_ident","Citadel Hub",         "policy-as-code",                  ALL),
    ("c_a365",      "z_ident","Microsoft Agent 365", "control plane (G14)",             ALL),
    ("c_agt",       "z_ident","Agent Governance Toolkit","open-source",                 {"A2","A3","A4","A6"}),
    # ---- Observability rail (bottom) ----
    ("c_appin",     "z_obs",  "App Insights",        "traces",                          ALL),
    ("c_ftrace",    "z_obs",  "Foundry traces",      "agent runs",                      {"A2","A3","A4","A5","A6"}),
    ("c_eval",      "z_obs",  "Evaluations",         "gate deploy (G10)",               ALL),
    ("c_cost",      "z_obs",  "Cost Management",     "token metering",                  ALL),
    ("c_sent",      "z_obs",  "Microsoft Sentinel",  "SIEM / SOAR",                     ALL),
    ("c_def",       "z_obs",  "Defender for Cloud",  "posture",                         ALL),
    # ---- Platform foundation ----
    ("c_lz",        "z_plat", "Landing zone",        "CAF AI Ready",                    ALL),
    ("c_net",       "z_plat", "Networking",          "private endpoints · firewall",    ALL),
    ("c_comp",      "z_plat", "Compute hosts",       "Foundry · ACA · AKS",             ALL),
    ("c_waf",       "z_plat", "WAF AI pillars",      "5 pillars",                       ALL),
    ("c_aac",       "z_plat", "AAC baselines",       "Foundry Chat · Agentic",          ALL),
    ("c_w365",      "z_plat", "Windows 365 for Agents","sandboxed VM",                  {"A4","A5","A6"}),
]

# ----------------------------------------------------------------------
# Canonical CAFÉ edges (per RA topology in CAFE_Reference_Architecture.html + docx §M5)
# Each: (source, target, kind, [archetype-filter or None for all]).
# Edges drop automatically if either endpoint is filtered out for the archetype.
# ----------------------------------------------------------------------
EDGES = [
    # Request flow: experience → edge → cognitive → knowledge
    ("c_copilot", "c_apim",     "request", None),
    ("c_web",     "c_apim",     "request", None),
    ("c_mobile",  "c_apim",     "request", None),
    ("c_system",  "c_apim",     "request", None),
    ("c_portal",  "c_fdwaf",    "request", None),
    ("c_fdwaf",   "c_apim",     "request", None),
    ("c_apim",    "c_dec",      "request", None),
    ("c_apim",    "c_cps",      "request", None),
    ("c_apim",    "c_foundry",  "request", None),
    ("c_chan",    "c_foundry",  "request", None),
    # Cognitive ↔ Agent Framework orchestration
    ("c_foundry", "c_agf",      "request", None),
    ("c_manifest","c_foundry",  "policy",  None),   # G01 manifest gate
    # Cognitive → Knowledge (G06 grounding)
    ("c_foundry", "c_fiq",      "knowledge", None),
    ("c_dec",     "c_wiq",      "knowledge", None),
    ("c_cps",     "c_fiq",      "knowledge", None),
    ("c_fiq",     "c_search",   "knowledge", None),
    ("c_fiq",     "c_fab",      "knowledge", None),
    # Cognitive → Models (mediated by APIM)
    ("c_foundry", "c_modcat",   "request", None),
    ("c_apim",    "c_modrem",   "policy",  None),
    ("c_foundry", "c_modloc",   "request", None),
    # Cognitive → Tools (G02 scoped invocation)
    ("c_foundry", "c_mcp",      "tool", None),
    ("c_cps",     "c_dvskill",  "tool", None),
    ("c_foundry", "c_pa",       "tool", None),
    ("c_mcpedge", "c_mcp",      "policy", None),   # G04 admission
    # Tools → Data + Tools → External
    ("c_dvskill", "c_dv",       "data", None),
    ("c_mcp",     "c_dv",       "data", None),
    ("c_mcp",     "c_sql",      "data", None),
    ("c_pa",      "c_dv",       "data", None),
    ("c_intg",    "c_erp",      "event", None),
    ("c_intg",    "c_crm",      "event", None),
    ("c_intg",    "c_itsm",     "event", None),
    ("c_pa",      "c_saas",     "event", None),
    ("c_pa",      "c_op",       "event", None),
    ("c_pa",      "c_hris",     "event", None),
    # Knowledge → Data (indexed corpora)
    ("c_fiq",     "c_sp",       "knowledge", None),
    ("c_search",  "c_onelake",  "knowledge", None),
    # Knowledge sources & glossary (G06 grounding contract)
    ("c_fiq",     "c_ksrc",     "knowledge", None),
    ("c_fab",     "c_pglossary","knowledge", None),
    ("c_ksrc",    "c_sp",       "data", None),
    ("c_ksrc",    "c_onelake",  "data", None),
    # Agent ↔ State
    ("c_foundry", "c_state",    "data", None),
    # External agents (A2A)
    ("c_foundry", "c_a2a",      "event", None),
    # Identity rail → enforced zones (G03/G04/G14)
    ("c_entra",   "c_apim",     "identity", None),
    ("c_agentid", "c_foundry",  "identity", None),
    ("c_ca",      "c_apim",     "identity", None),
    ("c_purview", "c_fiq",      "identity", None),   # DLP on grounding
    ("c_citadel", "c_apim",     "identity", None),
    ("c_a365",    "c_agentid",  "identity", None),   # G14: governs the Agent ID
    ("c_a365",    "c_foundry",  "identity", None),   # G14: registers the runtime
    ("c_kv",      "c_foundry",  "identity", None),   # secrets
    # Observability rail ← every key zone
    ("c_apim",    "c_appin",    "observe", None),
    ("c_foundry", "c_ftrace",   "observe", None),
    ("c_foundry", "c_eval",     "observe", None),
    ("c_apim",    "c_cost",     "observe", None),
    ("c_foundry", "c_sent",     "observe", None),
    ("c_def",     "c_apim",     "observe", None),
    # Platform underpins compute
    ("c_comp",    "c_foundry",  "policy", None),
    ("c_lz",      "c_comp",     "policy", None),
    ("c_w365",    "c_foundry",  "policy", None),
]

LEGEND = [
    ("Request (sync)",   "strokeColor=#1A1A1A;endArrow=block;"),
    ("Knowledge (G06)",  "strokeColor=#0B7E63;endArrow=block;"),
    ("Tool (G02)",       "strokeColor=#C4651F;endArrow=block;"),
    ("Data",             "strokeColor=#2D5B9E;endArrow=block;"),
    ("Event / async",    "strokeColor=#777777;dashed=1;dashPattern=6 6;endArrow=open;"),
    ("Policy (APIM/G01)", "strokeColor=#B89500;dashed=1;dashPattern=6 4;endArrow=block;"),
    ("Identity",         "strokeColor=#7A4FB5;dashed=1;dashPattern=2 4;endArrow=open;"),
    ("Observability",    "strokeColor=#4F8A37;dashed=1;dashPattern=2 4;endArrow=open;"),
]

ARCHETYPE_NAMES = {
    "A1": "Assistive Q&A Agent",
    "A2": "Task Automation Agent",
    "A3": "Process Automation Agent",
    "A4": "Multi-Agent Coordinator",
    "A5": "Research / Analytic Agent",
    "A6": "Autonomous Operations Agent",
    "A7": "Conversational Front-End",
    "A8": "Embedded SDK Agent",
}

# ----------------------------------------------------------------------
def build_diagram(archetype: str) -> C4Diagram:
    """Build a C4Diagram for one CAFÉ archetype."""
    if archetype not in ARCHETYPE_NAMES:
        raise ValueError(f"unknown archetype {archetype}; choose one of {list(ARCHETYPE_NAMES)}")

    title = f"CAFÉ M5 Logical Reference Architecture — {archetype}: {ARCHETYPE_NAMES[archetype]}"
    d = C4Diagram(title, width=1820, edge_styles=EDGE_STYLES, junction_colors=JUNCTION_COLORS)

    # Identity rail at top, BDAT zones in middle, observability rail + platform at bottom
    zone_order = [TOP_RAIL] + ZONES + [BOTTOM_RAIL, PLAT_ZONE]
    for (zid, label, stroke, fill, comp_fill, _sec) in zone_order:
        d.zone(zid, label, stroke=stroke, fill=fill, height=110, comp_fill=comp_fill)

    # Security context per zone
    for (zid, _l, _s, _f, _cf, sec) in zone_order:
        if sec:
            d.security(zid, sec)

    # Components filtered by archetype membership
    kept = {cid for (cid, _z, _t, _d, archs) in COMPS if archetype in archs}
    for (cid, zone, title, desc, archs) in COMPS:
        if cid in kept:
            d.component(cid, zone, title, desc)

    # Edges — keep only if both endpoints survived archetype filter
    for (s, t, kind, arch_filter) in EDGES:
        if s in kept and t in kept:
            if arch_filter is None or archetype in arch_filter:
                d.edge(s, t, kind)

    # Trust boundary strip after the edge zone (identity gate to inner components)
    d.trust_boundary("PARTNER / EXTERNAL TRUST BOUNDARY · APIM-mediated",
                     after_zone="z_edge", fill="#FBE9A0", stroke="#C9A100")

    # Legend
    d.legend(LEGEND)
    # Attach the CAFÉ kind-by-pair map onto the diagram instance for the post-processor.
    d._cafe_kind_by_pair = {}
    for (s, t, kind, arch_filter) in EDGES:
        if s in kept and t in kept:
            if arch_filter is None or archetype in arch_filter:
                d._cafe_kind_by_pair[(s, t)] = kind
    return d


# ======================================================================
# Solution mode — architect supplies a spec; we render a CAFÉ-conformant
# diagram of their specific design (vs the canonical archetype RA above).
#
# Spec schema (JSON; see solutions/UAE_EarlyWarning.solution.json):
#   {
#     "title":              str,                    # diagram title
#     "use_case":           str (optional),         # ref to use-case doc
#     "base_archetype":     "A1".."A8",             # canonical RA to inherit from
#     "additional_archetypes": ["A5", ...] optional,# union additional archetypes
#     "include_comps":      [cid, ...] optional,    # narrow base composition to these only
#     "exclude_comps":      [cid, ...] optional,    # drop these from base composition
#     "custom_comps": [                             # solution-specific comps
#        {"cid": str, "zone": z_id, "title": str, "desc": str,
#         "kind": "boundary" | "m4-extension"}     # boundary = traditional architecture (§9.3)
#     ],
#     "edges": [                                    # solution-specific edges (added to canonical)
#        {"from": cid, "to": cid, "kind": EDGE_STYLES key, "label": str optional}
#     ],
#     "guardrails_enforced": ["G06", "G09", ...]    # cited in trust banner
#     "decision_points":    [str, ...] optional     # rendered as caption notes
#   }
#
# Interlock enforcement (§9.3):
#   * every comp in include/edges must be either (a) M4-catalogued (in COMPS) or
#     (b) declared in custom_comps with kind=boundary or m4-extension.
#   * m4-extension is logged with a warning prompting the architect to add to M4.
# ======================================================================
import json as _json
from pathlib import Path as _Path


def load_solution_spec(path: str) -> dict:
    """Load a JSON solution spec from disk."""
    text = _Path(path).read_text(encoding="utf-8")
    return _json.loads(text)


def validate_solution_spec(spec: dict) -> list:
    """Return a list of human-readable issues; empty list means clean.
    Hard rules (errors):
      * base_archetype must exist
      * every edge endpoint must be a known comp (canonical or custom)
    Soft rules (warnings):
      * custom_comp with kind=m4-extension prompts catalogue update
    """
    issues = []
    base = spec.get("base_archetype")
    if base and base not in ARCHETYPE_NAMES:
        issues.append(f"ERROR base_archetype {base!r} not in A1..A8")
    for a in spec.get("additional_archetypes", []):
        if a not in ARCHETYPE_NAMES:
            issues.append(f"ERROR additional_archetypes contains unknown {a!r}")
    canonical_cids = {c[0] for c in COMPS}
    custom_cids = {c["cid"] for c in spec.get("custom_comps", [])}
    known = canonical_cids | custom_cids
    for e in spec.get("edges", []):
        if e["from"] not in known:
            issues.append(f"ERROR edge source {e['from']!r} not in M4 catalogue or custom_comps")
        if e["to"] not in known:
            issues.append(f"ERROR edge target {e['to']!r} not in M4 catalogue or custom_comps")
    for cc in spec.get("custom_comps", []):
        kind = cc.get("kind")
        if kind not in ("boundary", "m4-extension"):
            issues.append(f"ERROR custom_comp {cc['cid']!r} kind must be 'boundary' or 'm4-extension', got {kind!r}")
        elif kind == "m4-extension":
            issues.append(f"WARN  custom_comp {cc['cid']!r} is an M4 extension — add a row to "
                          f"CAFE_Framework v0.5 M4 tables before publishing the RA (interlock §9.3).")
    return issues


def build_diagram_from_solution(spec: dict) -> C4Diagram:
    """Render an architect-supplied solution. Inherits from base_archetype (+ additional)
    composition, applies include/exclude filters, adds custom boundary comps + solution edges."""
    title = spec.get("title", "CAFÉ M5 Solution Reference Architecture")
    base = spec.get("base_archetype")
    if not base:
        raise ValueError("solution spec must declare base_archetype (A1..A8)")
    archetypes = [base] + list(spec.get("additional_archetypes", []))

    d = C4Diagram(title, width=1820, edge_styles=EDGE_STYLES, junction_colors=JUNCTION_COLORS)

    # Zones (same as archetype mode; the canonical band stack)
    zone_order = [TOP_RAIL] + ZONES + [BOTTOM_RAIL, PLAT_ZONE]
    for (zid, label, stroke, fill, comp_fill, _sec) in zone_order:
        d.zone(zid, label, stroke=stroke, fill=fill, height=110, comp_fill=comp_fill)
    for (zid, _l, _s, _f, _cf, sec) in zone_order:
        if sec:
            d.security(zid, sec)

    # Composition: union of canonical comps applicable to any selected archetype,
    # then narrow by include_comps (if non-empty), then drop exclude_comps.
    base_set = {cid for (cid, _z, _t, _d, archs) in COMPS if any(a in archs for a in archetypes)}
    inc = set(spec.get("include_comps", []))
    if inc:
        base_set &= inc
    base_set -= set(spec.get("exclude_comps", []))

    # Render canonical comps
    for (cid, zone, ctitle, desc, archs) in COMPS:
        if cid in base_set:
            d.component(cid, zone, ctitle, desc)

    # Render solution-specific custom comps (boundary or extension).
    # Boundary comps get a dashed border via fill override (post-processor adds dashed=1).
    custom_cids_marked = []  # list of {cid, title, kind} for post-processor styling
    for cc in spec.get("custom_comps", []):
        d.component(cc["cid"], cc["zone"], cc["title"], cc.get("desc", ""))
        custom_cids_marked.append({
            "cid":   cc["cid"],
            "title": cc["title"],
            "kind":  cc.get("kind", "boundary"),
        })

    # Canonical edges that survive the composition (both endpoints kept)
    all_kept = base_set | {cc["cid"] for cc in spec.get("custom_comps", [])}
    kind_by_pair = {}
    for (s, t, kind, arch_filter) in EDGES:
        if s in all_kept and t in all_kept:
            if arch_filter is None or any(a in arch_filter for a in archetypes):
                d.edge(s, t, kind)
                kind_by_pair[(s, t)] = kind

    # Solution-specific edges (override or supplement canonical)
    for e in spec.get("edges", []):
        d.edge(e["from"], e["to"], e["kind"])
        kind_by_pair[(e["from"], e["to"])] = e["kind"]

    # Trust boundary strip + legend
    d.trust_boundary("PARTNER / EXTERNAL TRUST BOUNDARY · APIM-mediated",
                     after_zone="z_edge", fill="#FBE9A0", stroke="#C9A100")
    d.legend(LEGEND)

    # Attach state for the post-processor
    d._cafe_kind_by_pair = kind_by_pair
    d._cafe_custom_cids  = custom_cids_marked
    d._cafe_solution_meta = {
        "guardrails_enforced": spec.get("guardrails_enforced", []),
        "decision_points":     spec.get("decision_points", []),
        "use_case":            spec.get("use_case", ""),
    }
    return d


# ----------------------------------------------------------------------
# Post-processor — engine stays generic; CAFÉ-specific styling applied here.
# ----------------------------------------------------------------------
def cafe_postprocess(drawio_xml: str, kind_by_pair: dict, dark: bool = True,
                     custom_cids_marked: list = None) -> str:
    """Rewrite engine output:
      • edge styles → CAFÉ palette by (source, target) lookup;
      • fontColor on every vertex set for dark theme readability.
    The engine renames our CIDs to internal IDs in banded mode, so we recover the mapping
    by matching each vertex's `value` prefix against the COMPS title catalogue.
    Operates on the mxGraph XML as text (engine output is well-formed and simple).
    """
    import re as _re
    light_text = "#E6E8EE" if dark else "#1A1A1A"

    def _edge_style_for(kind: str) -> str:
        base = EDGE_STYLES.get(kind, EDGE_STYLES["request"])
        if not base.startswith("edgeStyle="):
            base = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;" + base
        # Animate event + observe so async/observability flows are visually distinct in app.diagrams.net
        if kind in ("event", "observe") and "flowAnimation" not in base:
            base += "flowAnimation=1;"
        return base

    # ---- 1. Build engine_id → our_cid mapping by component-title match ----
    # The engine wraps each component title in <b>TITLE</b> inside the (HTML-escaped) value
    # attribute, so we decode the entities and pull the bold text out.
    # title_to_cid covers M4-catalogued comps + any solution custom comps we were told about.
    title_to_cid = {comp[2]: comp[0] for comp in COMPS}
    custom_kinds: dict = {}  # cid -> kind ("boundary" | "m4-extension")
    if custom_cids_marked:
        # custom_cids_marked may be either [(cid, kind), ...] or
        # [{"cid": ..., "title": ..., "kind": ...}, ...]. Support both.
        for item in custom_cids_marked:
            if isinstance(item, dict):
                title_to_cid[item["title"]] = item["cid"]
                custom_kinds[item["cid"]] = item.get("kind", "boundary")
            else:
                # (cid, kind) tuple — title not available; can't register in title_to_cid
                # (caller should pass dicts for solution mode)
                custom_kinds[item[0]] = item[1]
    engine_to_cid: dict = {}
    vert_pat = _re.compile(r'<mxCell\s+id="([^"]+)"\s+value="([^"]*)"[^>]*vertex="1"')
    bold_pat = _re.compile(r'<b>([^<]+)</b>')
    for m in vert_pat.finditer(drawio_xml):
        eid = m.group(1)
        val = (m.group(2) or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        bm = bold_pat.search(val)
        title = bm.group(1) if bm else None
        if title and title in title_to_cid:
            engine_to_cid[eid] = title_to_cid[title]

    # ---- 2. Rewrite edges: translate engine src/tgt → our cids → kind → CAFÉ style ----
    def _rewrite_edge(m: _re.Match) -> str:
        full = m.group(0)
        src_eid = m.group("src"); tgt_eid = m.group("tgt")
        scid = engine_to_cid.get(src_eid); tcid = engine_to_cid.get(tgt_eid)
        if scid is None or tcid is None:
            return full
        kind = kind_by_pair.get((scid, tcid))
        if kind is None:
            return full
        # Replace style="..." in the matched cell open-tag with the CAFÉ style.
        new_style = _edge_style_for(kind)
        return _re.sub(r'style="[^"]*"', f'style="{new_style}"', full, count=1)

    # Match any mxCell open tag with edge="1" containing source= and target= in any order.
    edge_pat = _re.compile(
        r'<mxCell\s+[^>]*edge="1"[^>]*>',
    )
    src_pat = _re.compile(r'source="(?P<src>[^"]+)"')
    tgt_pat = _re.compile(r'target="(?P<tgt>[^"]+)"')

    def _process_edge_tag(m: _re.Match) -> str:
        tag = m.group(0)
        ms = src_pat.search(tag); mt = tgt_pat.search(tag)
        if not ms or not mt:
            return tag
        # Re-dispatch through the named-group rewriter
        class _W:
            def __init__(self, s, t, full): self._s=s; self._t=t; self._f=full
            def group(self, k):
                if k=="src": return self._s
                if k=="tgt": return self._t
                if k==0: return self._f
                return None
        return _rewrite_edge(_W(ms.group("src"), mt.group("tgt"), tag))

    out = edge_pat.sub(_process_edge_tag, drawio_xml)

    # ---- 2b. Dash-border boundary/extension custom comps so they read as "not M4-catalogued" ----
    if custom_kinds:
        # engine_to_cid now includes custom comps (title was registered above);
        # invert it to get cid → engine_id.
        cid_to_engine = {v: k for k, v in engine_to_cid.items()}
        for ccid, kind in custom_kinds.items():
            eid = cid_to_engine.get(ccid)
            if not eid:
                continue
            # Patch only the vertex cell line for this engine id: add dashed=1
            def _mk_dash(line, eid=eid):
                if f'id="{eid}"' not in line or 'vertex="1"' not in line:
                    return line
                def _sub(m):
                    st = m.group(1)
                    if "dashed=" not in st:
                        st = st.rstrip(";") + ";dashed=1;dashPattern=4 4;"
                    return f'style="{st}"'
                return _re.sub(r'style="([^"]*)"', _sub, line)
            out = "\n".join(_mk_dash(ln) for ln in out.splitlines())

    # ---- 3. Set fontColor on every vertex style (skip if already set) ----
    if dark:
        def _vert_font(m: _re.Match) -> str:
            style = m.group(1)
            if "fontColor=" in style:
                return m.group(0)
            new_style = style.rstrip(";") + f";fontColor={light_text};"
            return f'style="{new_style}"'
        def _patch_vertex(line: str) -> str:
            if 'vertex="1"' in line:
                return _re.sub(r'style="([^"]*)"', _vert_font, line)
            return line
        out = "\n".join(_patch_vertex(ln) for ln in out.splitlines())

    return out


def main():
    p = argparse.ArgumentParser(description="Render CAFÉ M5 logical reference architecture per archetype or solution.")
    p.add_argument("--archetype", help="A1..A8 (archetype mode)")
    p.add_argument("--all", action="store_true", help="render all A1..A8 archetypes")
    p.add_argument("--solution", help="path to solution-spec JSON (solution mode)")
    p.add_argument("--out", default=".", help="output directory")
    p.add_argument("--name", help="output file basename (defaults to archetype id or solution title slug)")
    p.add_argument("--svg", action="store_true", default=True, help="also emit .svg preview (default on)")
    p.add_argument("--no-svg", dest="svg", action="store_false", help="skip .svg emission")
    args = p.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if not (args.all or args.archetype or args.solution):
        p.error("provide one of: --archetype <Ax>  |  --all  |  --solution <path>")

    def _render_and_save(d, basename: str, title: str, custom_cids=None):
        xml = d.render(layout="banded", outline_bands=True, animate_async=True, strict=False)
        xml = cafe_postprocess(xml, d._cafe_kind_by_pair, dark=True, custom_cids_marked=custom_cids)
        drawio_path = out / f"{basename}.drawio"
        drawio_path.write_text(xml, encoding="utf-8")
        print(f"  wrote {drawio_path}  ({len(xml)} bytes; violations={len(d.violations)})")
        if args.svg:
            from drawio_cafe_svg import drawio_to_svg
            svg = drawio_to_svg(xml, title=title, theme="dark")
            svg_path = out / f"{basename}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            print(f"  wrote {svg_path}  ({len(svg)} bytes)")

    # ---- Archetype mode ----
    if args.all or args.archetype:
        archs = list(ARCHETYPE_NAMES) if args.all else [args.archetype]
        for a in archs:
            d = build_diagram(a)
            _render_and_save(d, args.name or a, f"CAFÉ M5L — {a}: {ARCHETYPE_NAMES[a]}")

    # ---- Solution mode ----
    if args.solution:
        spec = load_solution_spec(args.solution)
        issues = validate_solution_spec(spec)
        for i in issues:
            print(f"  {i}")
        if any(s.startswith("ERROR") for s in issues):
            print("  Refusing to render — fix ERRORs above.")
            sys.exit(1)
        d = build_diagram_from_solution(spec)
        # Derive basename from spec filename if --name not provided
        if args.name:
            basename = args.name
        else:
            basename = Path(args.solution).stem.replace(".solution", "")
        _render_and_save(
            d, basename, spec.get("title", "CAFÉ Solution RA"),
            custom_cids=getattr(d, "_cafe_custom_cids", []),
        )


if __name__ == "__main__":
    main()
