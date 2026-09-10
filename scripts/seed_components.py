"""Give the reference architecture's components an IDENTITY, link the capability map to them, and
derive the component price catalogue — the content step of deterministic cost.

    .venv/bin/python scripts/seed_components.py            # rewrites the seed JSON + their masters

WHY. G04 says components are admitted via the capability map only, and step 21 selected them as
FREE TEXT — there was nothing to admit against. Step 23's agent then string-matched those names to
a twelve-line, opex-only price sheet. Once (a) every component has a stable id, (b) a capability
row says which components realise it, and (c) prices are keyed by `(component, variant)` with an
envelope and a volume band, cost is a JOIN and the only judgement left is upstream, where it is
already gated.

THE ID. `content_id("cmp-", zone, name)` — the same helper every other content-addressed id in the
lab uses — so a re-run of this script, or a re-extraction from the framework HTML, mints the same
id for the same component. Stable across re-extraction, NOT across a rename: correcting a
component's name mints a new id, and a design that cited the old one resolves to nothing rather
than failing loudly — rename with a re-publish that says so.

THE LINK. A capability row's `components` are (a) the catalogue entries whose NAME occurs, as a
whole word, in its `primary`/`alternative` text — generic single words (`System`) never link this
way, only by hand — (b) ALIASES for the product names the sheet uses for a component, and (c) an
explicit hand table for label-level synonyms. Deterministic and reviewable, and the JSON is the
reviewed seed: a row that already carries `components` is MERGED into, never overwritten, so a
person's correction survives the next run (`--relink` clears and recomputes on purpose).

RUN AFTER THE EXTRACTOR. `extract_cafe_seed.py` regenerates these JSON files from the framework
HTML without ids, links or the volume row; this script must follow it, and the invariant tests
under tests/unit/core/usecase fail until it has.

THE PRICES. The framework's price sheet re-keyed by the component each line prices, with its
variant (a component can be bought several ways: a frontier model provisioned or consumed), the
quality-attribute ENVELOPE a variant is valid for, and — for volume-driven lines — the driver and
the two thresholds that place a line at low / expected / high. `opex_*`, `unit` and `note` are
the sheet's own figures; `variant`, `envelope_in`, `volume_driver`, `expected_at`, `high_at` and
the component mapping are THIS LAB's structural placeholders, said so in the artifact's caveat, and
Finance's to replace in the corpus. `capex_once` is a column the sheet does not fill; a run that
needs it says `requires_input` rather than guessing. A line is banded exactly when it has a
volume driver — there is no separate boolean to fall out of step (and a boolean through a
markdown master comes back as the string "False").

Seed-only and TDD-exempt (CLAUDE.md's scripts exemption); what it writes is exercised by the
master-parity test and by every consumer of these artifacts.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab.core.semantic.ids import content_id                       # noqa: E402

SEED = ROOT / "src" / "lab" / "core" / "usecase" / "seed"


def component_id(zone: str, name: str) -> str:
    return content_id("cmp-", zone, name)


#: price-sheet Service -> (zone, component name, variant, envelope_in, volume_driver, expected_at,
#: high_at). A variant's `envelope_in` says which quality-attribute envelopes may buy it: a
#: provisioned frontier model is a steady-high-volume purchase and nothing else. Thresholds are in
#: the driver's unit per month and place a driven line at low (below expected_at), expected, or
#: high (above high_at); `none` means a flat line. The drivers are the three volume assumptions
#: intake captures (runs_per_month, users, records); a per-message pack is driven by runs, one
#: conversation turn being one run of the front door.
PRICED = {
    "API Management (Developer)": ("gw", "APIM — AI Gateway", "developer", ["low", "expected", "high"], "none", 0, 0),
    "Container Registry (Basic)": ("plat", "Compute hosts", "container-registry-basic", ["low", "expected", "high"], "none", 0, 0),
    "Container Apps": ("plat", "Compute hosts", "container-apps", ["low", "expected", "high"], "runs_per_month", 5000, 50000),
    "AI Foundry hub and project": ("cog", "Foundry agents", "hub-and-project", ["low", "expected", "high"], "none", 0, 0),
    "Azure OpenAI — frontier model, provisioned": ("mod", "Foundry model catalog", "frontier-provisioned", ["high"], "none", 0, 0),
    "Azure OpenAI — smaller models": ("mod", "Foundry model catalog", "small-consumption", ["low", "expected"], "runs_per_month", 5000, 50000),
    "Azure OpenAI — embeddings": ("mod", "Foundry model catalog", "embeddings-consumption", ["low", "expected", "high"], "records", 100000, 1000000),
    "AI Search (Basic)": ("knw", "Azure AI Search", "basic", ["low", "expected", "high"], "none", 0, 0),
    "Key Vault": ("ident", "Key Vault", "standard", ["low", "expected", "high"], "none", 0, 0),
    "Application Insights and Log Analytics": ("obs", "App Insights", "ingest", ["low", "expected", "high"], "runs_per_month", 5000, 50000),
    "SharePoint and Graph": ("data", "SharePoint", "m365-included", ["low", "expected", "high"], "none", 0, 0),
    "Conversational front door": ("cog", "Copilot Studio engine", "message-pack", ["low", "expected", "high"], "runs_per_month", 5000, 50000),
}

#: Capability rows whose text names a component by a SYNONYM the substring match cannot see —
#: label-level pairs a person checks by eye ("API Management — AI Gateway" is the catalogue's
#: "APIM — AI Gateway"). Kept explicit rather than fuzzy-matched, because a wrong link admits the
#: wrong component under G04. A row absent here AND unmatched stays unlinked and is printed.
#: Generic single words that are also component names. They never auto-link: "system" occurs in
#: "system of record" and "Agentic AI Systems", and each such match admitted a client channel to a
#: row about compute.
GENERIC = frozenset({"System", "Integration", "Networking"})

#: The product names the capability map uses for a component the catalogue spells otherwise —
#: whole-word matches, applied like the names themselves.
ALIASES = {
    "Application Insights": ("obs", "App Insights"),
    "Azure Monitor": ("obs", "App Insights"),
    "Container Apps": ("plat", "Compute hosts"),
    "AKS": ("plat", "Compute hosts"),
    "M365 Agents SDK": ("gw", "Channel adapters"),
}

LINKED_BY_HAND = {
    "API Management — AI Gateway": [("gw", "APIM — AI Gateway")],
    # The four priced components no row names: models are chosen from the catalog, secrets live in
    # the identity zone's vault, and a declarative M365 agent is built in Copilot Studio.
    "Remote / non-Microsoft models": [("mod", "Remote (via APIM)"), ("mod", "Foundry model catalog")],
    "Local / fine-tuned models": [("mod", "Local / fine-tuned"), ("mod", "Foundry model catalog")],
    "Identity & access": [("ident", "Key Vault")],
    "Declarative agent (M365 surface)": [("cog", "Copilot Studio engine")],
    "Edge / DDoS / WAF": [("gw", "Front Door + WAF")],
    "Multi-channel adapter": [("gw", "Channel adapters")],
    "Multi-channel conversational SDK": [("gw", "Channel adapters")],
    "Custom-engine agent runtime": [("cog", "Agent Framework")],
    "Agent supply chain / manifests": [("cog", "Manifest & supply chain")],
    "Foundry control plane": [("cog", "Foundry agents")],
    "Agent state / durable memory": [("data", "Agent state")],
    "Compute for hosted agents": [("plat", "Compute hosts")],
    "Networking isolation": [("plat", "Networking")],
    "Spoke 'Agents Environment'": [("plat", "Landing zone")],
    "Landing zone / perimeter": [("plat", "Landing zone")],
    "Baseline — agentic on containers": [("plat", "AAC baselines"), ("plat", "Compute hosts")],
    "Non-functional invariants (AI)": [("plat", "WAF AI pillars")],
    "Baseline — basic chat": [("plat", "AAC baselines")],
    "Baseline — production chat": [("plat", "AAC baselines")],
    "Influence-sized evaluation": [("obs", "Evaluations")],
    "Runtime governance hub": [("ident", "Citadel Hub")],
    "Eventing / messaging": [("too", "Integration")],
}

VOLUME_ROW = ["Volume assumptions",
              "Runs per month, users, records (Finance-owned)",
              "Cost — places every banded price line in its band; a driver left blank makes that "
              "line requires_input, never a guess"]


def _generator():
    spec = importlib.util.spec_from_file_location("extract_cafe_seed", ROOT / "scripts" / "extract_cafe_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _three_point(estimate: str) -> tuple[float, float, float]:
    from lab.core.usecase.cost import parse_estimate
    point = parse_estimate(estimate)
    return point.low, point.expected, point.high


def _word(name: str, text: str) -> bool:
    import re
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])", text) is not None


def main(argv: list[str] | None = None) -> int:
    relink = "--relink" in (argv or sys.argv[1:])
    gen = _generator()
    ra = json.loads((SEED / "reference_architecture.json").read_text())
    rows = ra["components"]
    if rows and len(rows[0]) == 4:                       # [zone, name, detail, archetypes] -> id first
        ra["components"] = [[component_id(z, n), z, n, d, a] for z, n, d, a in rows]
    by_name = {row[2]: row[0] for row in ra["components"]}

    caps = json.loads((SEED / "ai_capability_map.json").read_text())
    unlinked = []
    for cap in caps["capabilities"]:
        text = f"{cap.get('primary', '')} {cap.get('alternative', '')}".lower()
        auto = [cid for name, cid in by_name.items() if name not in GENERIC and _word(name, text)]
        auto += [component_id(z, n) for alias, (z, n) in ALIASES.items() if _word(alias, text)]
        auto += [component_id(z, n) for z, n in LINKED_BY_HAND.get(cap["capability"], ())]
        held = [] if relink else list(cap.get("components") or [])
        cap["components"] = list(dict.fromkeys(held + auto))     # merged, never overwritten
        if not cap["components"]:
            unlinked.append(cap["capability"])

    sheet = json.loads((SEED / "price_sheet.json").read_text())
    lines = []
    for service, unit, estimate, banded, note in sheet["lines"]["rows"]:
        if service not in PRICED:
            raise SystemExit(f"price line {service!r} has no component mapping in PRICED")
        zone, name, variant, envelopes, driver, expected_at, high_at = PRICED[service]
        low, expected, high = _three_point(estimate)
        if banded.lower().startswith("y") != (driver != "none"):
            raise SystemExit(f"{service!r}: the sheet says banded={banded!r} but the driver is "
                             f"{driver!r} — a line is banded exactly when a volume drives it")
        lines.append({"component": component_id(zone, name), "variant": variant,
                      "component_name": name, "zone": zone, "unit": unit,
                      "opex_low": low, "opex_expected": expected, "opex_high": high,
                      "capex_once": "",
                      "envelope_in": envelopes, "volume_driver": driver,
                      "expected_at": expected_at, "high_at": high_at,
                      "source_line": service, "note": note})
    prices = {"prices": lines,
              "_source": "price_sheet.json (Intake_Agent_Requirements_v2_7.docx Annexure F) joined to "
                         "reference_architecture.json by scripts/seed_components.py",
              "_caveat": "opex_low/opex_expected/opex_high, unit and note are the reference price "
                         "sheet's own figures, illustrative of the STRUCTURE. variant, envelope_in, "
                         "volume_driver, expected_at, high_at and the component mapping are this "
                         "lab's structural placeholders — Finance's to replace in the corpus, not "
                         "the sheet's. capex_once is not in the sheet: a design that needs it gets "
                         "requires_input, never a guess. A line is volume-driven exactly when "
                         "volume_driver is not none."}

    intake = json.loads((SEED / "intake_fields.json").read_text())
    if not any(r[0] == VOLUME_ROW[0] for r in intake["field_groups"]["rows"]):
        intake["field_groups"]["rows"].append(VOLUME_ROW)
    # The signed master must not attribute to the requirements docx a row it does not hold.
    addition = " + the Volume assumptions row, this lab's own addition (scripts/seed_components.py)"
    if addition not in intake.get("_source", ""):
        intake["_source"] = intake.get("_source", "") + addition

    written = {"reference_architecture": ra, "ai_capability_map": caps, "component_prices": prices,
               "intake_fields": intake}
    for name, payload in written.items():
        (SEED / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        for stem, text in gen.masters_for(name, payload).items():
            (SEED / "masters" / f"{stem}.md").write_text(text, encoding="utf-8")
    print(f"{len(ra['components'])} components with ids; {len(lines)} price lines over "
          f"{len({l['component'] for l in lines})} components; "
          f"{len(caps['capabilities']) - len(unlinked)}/{len(caps['capabilities'])} capabilities linked")
    if unlinked:
        print("capabilities whose primary/alternative names no catalogue component (complete by hand):")
        for c in unlinked:
            print("  -", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
