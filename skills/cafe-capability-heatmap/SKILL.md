---
name: cafe-capability-heatmap
description: Render the CAFÉ technology capability map (the A0 L1/L2/L3 poster) as a RAG heatmap of the capabilities a use case impacts — red missing, green new, amber consumed or updated — as a self-contained HTML page. Use this whenever a capability-match / coverage-map step (CAFÉ E0.3) has produced a list of impacted technology or business capabilities, or whenever the user asks to show, visualise, heatmap, colour or highlight which L3 capabilities a use case, solution or initiative touches, even if they don't say "heatmap".
---

# CAFÉ capability heatmap

Renders the full technology capability map in its published A0 template and fills the impacted L3 blocks by status. Everything else stays on the page, faded, so readers see the impact in the context of the whole map.

## In this lab

The pipeline draws this view itself at step 5 (match capabilities): the `semantic_view_capabilities` tool on semantic-mcp reads the
tables under the run's pin and stores the page by reference, and the approval shows it as a tab.
The renderer is `lab.core.usecase.views.capability_heatmap` — the same code whether the pipeline or you run it.
Output is ONE self-contained HTML page (no browser is driven here, so no PNG): open it in a browser
and print to PDF from there.

## Where it sits in the pipeline

1. Functional decomposition (E0.2) → element inventory
2. Capability match (E0.3) → **impacted capability list** → *this skill*
3. Realisation match (E0.4) → realisation list → `cafe-realisation-heatmap`
4. Architecture mapping (Q6) → solution scope → `cafe-scoped-reference-architecture`

This skill only renders. It never decides which capabilities are impacted — that belongs to the step before it — so the same input always gives the same picture.

## Input

Build a JSON file from the capability-match result:

```json
{
  "use_case": "UC-014",
  "title": "Governed Claude access for developers and staff",
  "date": "2026-09-25",
  "capabilities": [
    {"id": "KNW.11", "status": "updated", "note": "block, redact or reroute PHI"},
    {"id": "XCT.24", "status": "new"},
    {"id": "TEC.02", "status": "consumed"},
    {"id": "XCT.13", "status": "missing", "note": "coverage unconfirmed"},
    {"name": "AI licence reconciliation", "parent_l2": "XCT-B", "status": "missing"}
  ]
}
```

| status | Colour | Meaning |
|---|---|---|
| `missing` | red fill | Required, and nothing provides it — an unresolved gap |
| `new` | green fill | Introduced by the solution |
| `consumed` | amber fill, tag **C** | Exists and is reused unchanged |
| `updated` | amber fill, tag **U** | Exists and the solution changes it |

- `note` (optional) prints in bold inside the block — keep it to one line.
- A capability that is **not on the map** is given as `name` + `parent_l2` (+ `status`, usually `missing`). It is drawn as a red dashed *proposed* block under that L2 and signals a capability-map delta.
- Retired IDs (for example XCT.09) are resolved automatically to their successor and reported.
- Unknown IDs are never silently dropped: they appear in an "Unresolved IDs" panel on the page and in the script output. Tell the user about them.

## Run

```bash
.venv/bin/python scripts/cafe_views.py capability_heatmap --input impacts.json \
    --workbook ~/Downloads/cafe-artifacts.xlsx --out var/out/views/<use-case>_capability_heatmap.html
```

The workbook is the single source; this reads it with the corpus importer's own reader, so a table
is found by its marker exactly as the corpus names it. There is no bundled snapshot: the CAFÉ
tables include restricted-source content that never enters this repository.

## After rendering

Present the page, then give a one-paragraph readout: how many L3s are impacted, the split new / consumed-or-updated / missing, any proposed capabilities, and any unresolved or retired IDs. Don't restate every block — the picture does that.

## Rendering rules (why it looks the way it does)

- The template is the published poster, so a heatmap is always recognisable as the map people already know; never rearrange blocks.
- The whole block is filled, not just the text, because colour on text alone is easy to miss when printed.
- Non-impacted blocks are faded rather than hidden so the reader keeps the context of the full map.
- L1 and L2 headers carry impact counts so the reader can scan at domain level first.
