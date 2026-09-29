---
name: cafe-realisation-heatmap
description: Render the CAFÉ capability realisation view (the A0 poster of every L3 with its Microsoft, UAE-sovereign/Core42 and alternative realisations) as a RAG heatmap of a solution's chosen realisations — red missing, green new, amber consumed or updated — highlighting which realisation route was picked, as a self-contained HTML page. Use this whenever a realisation-match step (CAFÉ E0.4) has mapped shortlisted capabilities to products or platforms, or whenever the user asks to show, visualise or heatmap which products, services or realisations a solution uses, even if they don't say "heatmap".
---

# CAFÉ realisation heatmap

Renders the full capability realisation view in its published A0 template and fills the realisation blocks of the shortlisted L3s by status. The chosen realisation line (Microsoft, UAE sovereign or alternative) is marked with ✔ and a dark label.

## In this lab

The pipeline draws this view itself at step 6 (match realisations): the `semantic_view_realisations` tool on semantic-mcp reads the
tables under the run's pin and stores the page by reference, and the approval shows it as a tab.
The renderer is `lab.core.usecase.views.realisation_heatmap` — the same code whether the pipeline or you run it.
Output is ONE self-contained HTML page (no browser is driven here, so no PNG): open it in a browser
and print to PDF from there.

## Where it sits in the pipeline

1. Functional decomposition (E0.2)
2. Capability match (E0.3) → `cafe-capability-heatmap`
3. Realisation match (E0.4) → **realisation list** → *this skill*
4. Architecture mapping (Q6) → `cafe-scoped-reference-architecture`

This skill only renders; the realisation decision belongs to the step before it.

## Input

```json
{
  "use_case": "UC-014",
  "title": "Governed Claude access for developers and staff",
  "date": "2026-09-25",
  "realisations": [
    {"id": "COG.13", "route": "sovereign", "product": "Core42 Compass (Claude in-country)", "status": "new"},
    {"id": "TEC.02", "route": "microsoft", "product": "Azure API Management AI Gateway", "status": "consumed"},
    {"id": "KNW.11", "route": "microsoft", "status": "updated", "note": "add block / redact / reroute policy"},
    {"id": "XCT.13", "status": "missing", "note": "no realisation confirmed"}
  ]
}
```

| field | Required | Meaning |
|---|---|---|
| `id` | yes | L3 ID from the technology capability map |
| `status` | yes | `missing` (red) · `new` (green) · `consumed` (amber, **C**) · `updated` (amber, **U**) |
| `route` | no | `microsoft` · `sovereign` · `alternative` — which realisation line to highlight |
| `product` | no | The specific product chosen; printed as "Chosen: …" |
| `note` | no | One-line remark printed in bold |

Use `missing` for an in-scope capability that has no realisation available. Retired IDs resolve automatically; unknown IDs are listed in an on-page panel and in the script output — tell the user about them.

## Run

```bash
.venv/bin/python scripts/cafe_views.py realisation_heatmap --input realisations.json \
    --workbook ~/Downloads/cafe-artifacts.xlsx --out var/out/views/<use-case>_realisation_heatmap.html
```

The workbook is the single source; this reads it with the corpus importer's own reader, so a table
is found by its marker exactly as the corpus names it. There is no bundled snapshot: the CAFÉ
tables include restricted-source content that never enters this repository.

## Colour discipline

The published realisation poster uses red/amber/green for UAE North availability. In the heatmap those signals are shown in **light grey** with glyphs (✓ available · ⚠ partial or preview · ✕ not available) so the block fill is the only colour on the page. Keep it that way — two colour meanings on one poster make the heatmap unreadable.

## After rendering

Present the page and give a short readout: realisations in scope, the new / consumed-or-updated / missing split, routes chosen (how many Microsoft, sovereign, alternative), and any capability flagged missing or any availability caveat (✕ or ⚠) on a chosen line that the user should know about.
