# Solution spec — JSON schema

A **solution spec** lets an architect describe a specific CAFÉ-conformant solution and have
`/drawio-cafe` render it. The spec inherits from a base archetype (M1) and adds solution-specific
extensions — bound by the M3/M4/§9.3 interlock.

## Quick example

```json
{
  "title": "CAFÉ M5 Solution RA — UAE Multi-Domain Early-Warning System",
  "use_case": "UAE_EarlyWarning_UseCase.md",
  "base_archetype": "A4",
  "additional_archetypes": ["A5"],
  "exclude_comps": ["c_pa", "c_cps"],
  "custom_comps": [
    {"cid": "c_uae_ingest", "zone": "z_ext", "title": "OSINT ingestion pipeline",
     "desc": "Event Hubs · streams · polls", "kind": "boundary"}
  ],
  "edges": [
    {"from": "c_uae_ingest", "to": "c_fiq", "kind": "knowledge"}
  ],
  "guardrails_enforced": ["G06", "G09", "G11", "G12", "G13", "G14"],
  "decision_points": [
    "Corroboration ≥2 sources before high alert (G13)"
  ]
}
```

Render:

```bash
python3 ~/.claude/skills/drawio-cafe/drawio_cafe.py \
  --solution my-solution.json --out ./out/
```

Outputs `my-solution.drawio` + `my-solution.svg` in `./out/`.

## Field reference

| Field | Type | Required | Meaning |
|---|---|---|---|
| `title` | string | yes | Diagram title (appears at top of the canvas + SVG header). |
| `use_case` | string | no | Reference to the use-case document (for provenance only — not rendered). |
| `base_archetype` | `"A1".."A8"` | yes | Canonical RA to inherit from. Determines the starting composition. |
| `additional_archetypes` | array of `"Ax"` | no | Union additional archetypes (e.g. `["A5"]` to add Research/Analytic comps to A4). |
| `include_comps` | array of cid | no | If non-empty, narrow the inherited composition to just these comps (whitelist). |
| `exclude_comps` | array of cid | no | Drop these comps from the inherited composition (blacklist). |
| `custom_comps` | array of object | no | Solution-specific comps not in M4 catalogue. Each: `{cid, zone, title, desc, kind}`. See below. |
| `edges` | array of object | no | Solution-specific edges added on top of canonical. Each: `{from, to, kind, label?}`. See below. |
| `guardrails_enforced` | array of `"Gxx"` | no | Cited in spec metadata. Not visually rendered yet — captured for documentation. |
| `decision_points` | array of string | no | Captured for documentation. |

### `custom_comps` entries

| Field | Type | Required | Meaning |
|---|---|---|---|
| `cid` | string starting `c_` | yes | Unique component id. Must not collide with M4 catalogue cids. |
| `zone` | one of `z_ident`, `z_exp`, `z_edge`, `z_cog`, `z_knw`, `z_mod`, `z_too`, `z_data`, `z_ext`, `z_obs`, `z_plat` | yes | Which CAFÉ band the comp belongs to. |
| `title` | string | yes | Label shown on the comp tile. |
| `desc` | string | no | Sub-label below the title (8pt). |
| `kind` | `"boundary"` \| `"m4-extension"` | yes | See **Interlock contract** below. |
| `rationale` | string | no | Free-text rationale — not rendered; useful for review. |

### `edges` entries

| Field | Type | Required | Meaning |
|---|---|---|---|
| `from` | cid | yes | Source comp id (must be in M4 catalogue or in `custom_comps`). |
| `to` | cid | yes | Target comp id (same rule). |
| `kind` | one of `request`, `knowledge`, `tool`, `data`, `event`, `policy`, `identity`, `observe` | yes | CAFÉ edge type — drives line style + colour + guardrail mapping. |
| `label` | string | no | Optional edge label (currently captured but not rendered — line clutter risk). |

## Interlock contract — what the skill enforces

Per CAFÉ Framework v0.5 §9.3:

1. **Closed component set** — every comp must be either:
   - **M4-catalogued** (its cid is in the COMPS table inside `drawio_cafe.py`); OR
   - **declared in `custom_comps`** with `kind = "boundary"` (traditional-architecture component referenced but not catalogued; renders with **dashed border** to indicate this); OR
   - **declared in `custom_comps`** with `kind = "m4-extension"` (a proposed new AI-architecture component; the skill emits a **WARN** prompting the architect to add a row to the framework M4 tables before publishing).
2. **Edge endpoints** — every `from`/`to` cid must be known (M4 catalogue or `custom_comps`). Unknown cids → `ERROR`, render aborts (exit code 1).
3. **Base archetype** — must be one of A1..A8.
4. **Vocabulary consistency** — custom comp titles should not clash with M4 catalogue titles (the post-processor matches by `<b>title</b>` text).

Run validation without rendering (CI-friendly — coming in v0.2):

```bash
# in v0.2:
python3 ~/.claude/skills/drawio-cafe/drawio_cafe.py --solution my.json --validate
```

For now, `--solution` always validates before rendering and exits non-zero on ERROR.

## Edge kinds — quick visual reference

| `kind` | Colour (dark theme) | Guardrail | Use for |
|---|---|---|---|
| `request` | light slate `#C7CED8` | — | User/system request → agent; in-band request flow. |
| `knowledge` | bright teal `#2DD4BF` | G06 | Agent → grounding contract (Foundry IQ, Fabric IQ). |
| `tool` | bright orange `#FB923C` | G02 | Agent → tool/skill (MCP server, Power Automate). |
| `data` | bright blue `#60A5FA` | — | Read/write systems of record. |
| `event` | light grey `#9CA3AF` | — | Async event / webhook / message; animated dashes in `.drawio`. |
| `policy` | bright gold `#FBBF24` | G01/G04 | Manifest enforcement / admission control / APIM policy mediation. |
| `identity` | bright purple `#A78BFA` | G03/G14 | Identity rail → enforced zone (Entra, Agent 365). |
| `observe` | bright green `#4ADE80` | G10 | Observability rail ← every key zone; eval-gate. |

In the `.drawio` editable file these render with darker colours (light-mode friendly for editing).
The dark-theme palette is applied at SVG-preview render time.

## Available zones + canonical comp cids

To use `include_comps` or `exclude_comps`, you need the canonical cids. Run:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/skills/drawio-cafe')
from drawio_cafe import COMPS
for cid, zone, title, desc, archs in COMPS:
    print(f'{cid:14s} {zone:8s} {title:40s} ({sorted(archs)})')
"
```

## Validation errors you might see

| Error | Cause | Fix |
|---|---|---|
| `ERROR base_archetype 'Z9' not in A1..A8` | Typo in `base_archetype` | Use A1, A2, … A8. |
| `ERROR edge source 'c_foo' not in M4 catalogue or custom_comps` | Edge references an unknown cid | Either add a `custom_comps` entry or fix the cid. |
| `ERROR custom_comp 'c_x' kind must be 'boundary' or 'm4-extension'` | Missing/invalid `kind` | Add `"kind": "boundary"`. |
| `WARN custom_comp 'c_y' is an M4 extension — add a row to CAFE_Framework v0.5 M4 tables` | Declared as `m4-extension` | Update framework docx before publishing the RA. |

## Worked example

See `skills/drawio-cafe/examples/UAE_EarlyWarning.solution.json` for a full real-world spec
(UAE multi-domain early-warning system, A4 + A5 base, 3 boundary comps, 6 solution-specific edges,
12 enforced guardrails). The rendered output is at `examples/solutions/UAE_EarlyWarning.{drawio,svg}`.
