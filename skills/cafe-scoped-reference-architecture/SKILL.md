---
name: cafe-scoped-reference-architecture
description: Render the CAFÉ logical reference architecture and physical reference implementation (A0 H-pattern — layers as rows, security and governance pillars) showing only a solution's scope, hiding out-of-scope building blocks and components (or ghosting them), as a self-contained HTML page. Use this whenever realisations have been mapped to reference-architecture components (CAFÉ Q6 compose), or whenever the user asks to show a solution architecture, solution scope, "what's in scope" view or a filtered/scoped version of the reference architecture, even if they don't name the reference architecture.
---

# CAFÉ scoped reference architecture

Produces two renders from one input: the **logical** view (vendor-neutral building blocks) and the **physical** view (products). Instead of colouring, it shows only what is in the solution — the same show/hide behaviour as the interactive reference-architecture canvas. The layout is compact and content-driven, sized for a single **A4** page by default.

## In this lab

The pipeline draws this view itself at step 22 (compose): the `semantic_view_architecture` tool on semantic-mcp reads the
tables under the run's pin and stores the page by reference, and the approval shows it as a tab.
The renderer is `lab.core.usecase.views.scoped_architecture` — the same code whether the pipeline or you run it.
Output is ONE self-contained HTML page (no browser is driven here, so no PNG): open it in a browser
and print to PDF from there.

## Where it sits in the pipeline

1. Functional decomposition (E0.2)
2. Capability match (E0.3) → `cafe-capability-heatmap`
3. Realisation match (E0.4) → `cafe-realisation-heatmap`
4. Architecture mapping (Q6) → **solution scope** → *this skill*

## Input

```json
{
  "use_case": "UC-014",
  "title": "Governed Claude access for developers and staff",
  "date": "2026-09-25",
  "pattern": "P5",
  "components": ["EX-05", "SEC-04", "GW-02", "GW-03", "MP-00", "MP-04", "cmp-967db4e8ad"],
  "building_blocks": ["GV2"],
  "ghost": false
}
```

- `components` — physical component codes (for example `GW-02`) or component ids (`cmp-…`) from the reference-architecture model. Retired ids resolve to their successor automatically.
- The **logical building blocks are derived** from the components through the component → building-block mapping; `building_blocks` adds any extra ones (rarely needed).
- `pattern` (optional, `P1`–`P5`) highlights the pattern the solution follows in the logical view's pattern strip; in-scope blocks on every pattern path are shown filled.
- `ghost: true` (or `--ghost`) shows out-of-scope boxes as faint dashed outlines — useful in reviews to show what was deliberately left out. Default is to hide them.

## Run

```bash
.venv/bin/python scripts/cafe_views.py scoped_architecture --input scope.json \
    --workbook ~/Downloads/cafe-artifacts.xlsx --out var/out/views/<use-case>_scoped_architecture.html
```

The workbook is the single source; this reads it with the corpus importer's own reader, so a table
is found by its marker exactly as the corpus names it. There is no bundled snapshot: the CAFÉ
tables include restricted-source content that never enters this repository.

## Rendering rules

- **The H structure is kept, the space is not wasted.** Layers stay as rows in the same order and the security and governance pillars stay left and right, so any solution view is recognisable as the same architecture. Zone sizes follow the content: a layer with nothing in scope collapses to a thin labelled strip ("not in scope"), empty zones in a shared row shrink to a narrow labelled column, and the design width is chosen so the drawing fills the page.
- Model providers keep their residency lanes (in-region, sovereign, out-of-region) — residency is architecturally significant, so the lane a model sits in must stay visible.
- Flows are drawn only when both ends are visible. The boundary (traditional systems) appears whenever tool services are in scope.
- No RAG colours here. UAE North availability appears in light grey text on physical boxes for information only.

## After rendering

Present both pages and give a short readout: components and building blocks in scope, layers touched and untouched, the residency lanes used by models, the pattern, and any unresolved or retired ids reported by the script.
