---
name: drawio-cafe
description: >
  Render a CAFÉ M5 logical reference architecture (per CAFE_Framework v0.5) as an editable draw.io file
  plus a dark-themed SVG preview, for a chosen agent archetype (A1–A8) or an architect-supplied solution
  spec (JSON). Use this skill whenever the user mentions CAFÉ, CAM, M5 reference architectures, agent
  archetypes (A1..A8), the §9.3 interlock, or asks for an agentic-AI solution architecture diagram in
  CAFÉ vocabulary — even if they don't say "drawio". Self-contained: bundles the drawio-c4 layout/router
  engine. Enforces the M3/M4 interlock (closed component set; boundary comps dashed). Also triggered by
  /drawio-cafe.
---

# drawio-cafe

Generate **CAFÉ-vocabulary logical reference architectures** (M5L) for a chosen agent archetype, in
banded C4 style, editable in draw.io. The CAFÉ semantics are encoded here; the layout/router engine is
imported from `drawio-c4`.

**Companion to `/drawio-c4`.** Use `/drawio-c4` for *generic* solution/container diagrams (banded
trust zones, your own vocabulary). Use `/drawio-cafe` when the output must conform to CAFÉ — same
visual style, but bands are the M5 zones (Identity rail · Experience · Edge & AI Gateway · Cognitive ·
Knowledge · Models · Tools · Data · External · Observability rail · Platform), components are M4
catalogue entries only (closed-set rule, §9.3 of the framework doc), edges carry typed CAFÉ semantics
(`request`, `policy`, `knowledge`, `tool`, `data`, `event`, `identity`, `observe`), and per-archetype
filtering uses the archetype-to-component map embedded in CAFE_Artifacts_Visualisation.html `M5_COMPS`.

## What you get
- One `.drawio` per archetype (A1–A8) — opens in <https://app.diagrams.net>.
- A small inline SVG preview for in-HTML embedding (file://-friendly).
- The diagram obeys the **CAFÉ interlock**: only M4-catalogued components appear; M3 guardrails
  surface as edge labels where they govern the edge (e.g. `G06` on the knowledge edge, `G09` on the
  Power Automate approval edge, `G14` on the Agent 365 governance edge).

## How to invoke (Claude.ai)

Let `$SKILL` be this skill's installed directory (the folder containing this SKILL.md — shown as
`location` in `available_skills`). The script is pure Python 3.10+ stdlib; nothing to install.

**Archetype mode** — renders a canonical M5 RA for one of A1–A8:
```bash
python3 "$SKILL/drawio_cafe.py" --archetype A2 --out /mnt/user-data/outputs
python3 "$SKILL/drawio_cafe.py" --all --out /mnt/user-data/outputs        # all 8
```

**Solution mode** — renders an architect-designed solution from a JSON spec. Write the spec yourself
from the user's requirements (schema below; full doc in `SOLUTION_SPEC.md` next to this file;
worked example in `examples/UAE_EarlyWarning.solution.json`):
```bash
python3 "$SKILL/drawio_cafe.py" --solution /home/claude/my.solution.json --out /mnt/user-data/outputs
```

**After rendering**: present BOTH files to the user with `present_files` — the `.svg` first (instant
visual preview in chat), then the `.drawio` (editable in https://app.diagrams.net). If validation
fails (`--solution` exits non-zero), read the stderr message — it names the unknown cid; fix the spec
(catalogue the comp in `custom_comps` with `kind: boundary`, or correct the id) and re-run.

### Solution spec schema (JSON)

```json
{
  "title": "string — diagram title",
  "use_case": "optional ref to use-case doc",
  "base_archetype": "A1..A8 — start from this canonical RA",
  "additional_archetypes": ["A5"],                    // optional union
  "include_comps": ["c_apim", ...],                   // optional narrow filter
  "exclude_comps": ["c_pa", ...],                     // drop from canonical
  "custom_comps": [                                   // solution-specific
    {"cid": "c_uae_ingest", "zone": "z_ext", "title": "OSINT ingestion",
     "desc": "Event Hubs · streams", "kind": "boundary"}
  ],
  "edges": [                                          // solution-specific flows
    {"from": "c_uae_ingest", "to": "c_fiq", "kind": "knowledge"}
  ],
  "guardrails_enforced": ["G06","G09","G11","G12","G13","G14"],
  "decision_points": ["Corroboration ≥2 sources before high alert (G13)"]
}
```

**Interlock enforcement (§9.3)**: every comp must be either (a) M4-catalogued in `COMPS`
or (b) declared in `custom_comps` with `kind=boundary` (traditional architecture, not
catalogued) or `kind=m4-extension` (warning prompt to update M4 first). Edges to/from
unknown cids fail validation (`--solution` exits non-zero).

**Visual differentiation**: custom comps with `kind=boundary` render with **dashed borders**
so they read as "not M4-catalogued" at a glance.

## CAFÉ → C4 mapping (what this skill encodes)
- **Zones** = M5_ZONES (identity rail · experience · edge · cognitive · knowledge · models · tools ·
  data · external · observability rail · platform). Stable colours per zone, named per CAFÉ.
- **Components** = the M5_COMPS catalogue (subset filtered by archetype membership).
- **Edges** = the canonical request/policy/knowledge/tool/data/event/identity/observe flows. Edge type
  drives line style (solid sync, dashed async, gold cross-trust, purple identity).
- **Trust-boundary strip** appears after the *edge* zone (identity gate to all inner components).
- **Security context** strings cite the M3 guardrail enforced at that zone (`G01`, `G02`, `G06`, …).
- **Per-archetype filter** uses the same `["A1","A2",…]` membership lists as M5_COMPS — single source
  of truth.

## Edge types (CAFÉ-specific palette)
| key | line | meaning |
|---|---|---|
| `request`  | solid black, arrow                | user/system request → agent |
| `policy`   | gold dashed                       | APIM policy / Conditional Access / Purview DLP enforcement |
| `knowledge`| solid teal, arrow                 | grounding contract (G06) — retrieve via Foundry IQ |
| `tool`     | solid orange, arrow               | tool/skill invocation (G02) |
| `data`     | solid blue                        | read/write systems of record |
| `event`    | dashed grey, animated             | async event / webhook |
| `identity` | purple short-dash                 | identity rail → enforced zone |
| `observe`  | green short-dash                  | observability rail ← every zone |

## Engine
This skill bundles a copy of the `drawio-c4` layout/router engine (`drawio_c4.py` in this folder) so
it is fully self-contained. If a sibling `drawio-c4` skill is installed (checked at
`../drawio-c4`, `/mnt/skills/user/drawio-c4`, `/mnt/skills/public/drawio-c4`), that copy takes
precedence only when no bundled copy exists. Use the standalone `drawio-c4` skill for *generic*
banded C4 diagrams in your own vocabulary; use this skill when output must conform to CAFÉ.
