---
name: cafe-ontology-graph
description: Render a use case's match against the CAFÉ ontology as a D3 force-directed graph (the ontology topology view) — concepts as nodes carrying their full record, relationships as labelled edges, green matched, amber partial or enhancement, red gap (needed but not in the ontology), grey context — as an interactive offline HTML page. Use this whenever an ontology check (CAFÉ E0.6) or ontology delta (step 9) has been done, or whenever the user asks to show, visualise or graph which ontology concepts or relationships a use case uses, matches or is missing, even if they just say "topology view", "concept graph" or "what's in the ontology for this".
---

# CAFÉ ontology graph (topology view)

Shows what a use case needs from the ontology and how much of it already exists. Each node is a concept; clicking it shows the full record (definition, module, kind, parent, authoritative source, platforms, FHIR mapping, Guild reference, competency questions and indicators that use it, and its relationships). Edges are the ontology's relationships, labelled with their predicate.

## In this lab

The pipeline draws this view itself at step 9 (check the ontology): the `semantic_view_ontology` tool on semantic-mcp reads the
tables under the run's pin and stores the page by reference, and the approval shows it as a tab.
The renderer is `lab.core.usecase.views.ontology_graph` — the same code whether the pipeline or you run it.
Output is ONE self-contained HTML page (no browser is driven here, so no PNG): open it in a browser
and print to PDF from there.

## Where it sits

It visualises the ontology check at E0.6 and the ontology delta at step 9. It runs alongside the capability, realisation and reference-architecture views: those show *what the solution uses*, this shows *what it means* and where meaning is missing.

## Input

Build the match from the ontology check:

```json
{
  "use_case": "UC-CLAUDE-DEV-01",
  "title": "Governed Claude Code for developers — ontology match",
  "date": "2026-09-25",
  "context": "neighbours",
  "concepts": [
    {"id": "Person", "status": "matched"},
    {"id": "AIAgent", "status": "partial", "note": "received device agent, not a registered agent"},
    {"id": "SensitivityLabel", "status": "enhancement", "note": "extend to prompt content"},
    {"id": "Prompt", "status": "gap", "name": "Prompt", "module": "ENG", "kind": "document",
     "definition": "Text and code context a user or agent sends to a model."}
  ],
  "relationships": [
    {"subject": "Prompt", "predicate": "submittedBy", "object": "Person", "status": "gap"},
    {"subject": "SensitivityLabel", "predicate": "classifies", "object": "Prompt", "status": "enhancement"}
  ]
}
```

| status | Colour | Meaning |
|---|---|---|
| `matched` | green | The concept or relationship exists and fits the use case as is |
| `partial` | amber | It exists but only covers part of what is needed, or is itself a gap concept in the ontology |
| `enhancement` | amber, dashed | It exists and the use case needs it extended (new attribute, state or relationship) |
| `gap` | red, dashed | Needed but not in the ontology — an ontology delta. Give `name`, `module`, `kind` and a one-line `definition` so the delta is reviewable |

- Use ontology concept ids exactly as in the ontology (for example `AIAgent`, `HealthCondition`). Unknown ids that are not marked `gap` are reported as unresolved — tell the user.
- Relationships that already exist between two matched or partial concepts are **added automatically**; list only relationships the use case adds or changes.
- `context` controls grey surrounding concepts: `neighbours` (default — one hop around the matched set), `module` (the matched concepts' modules), `all` (whole ontology, faded) or `none`.

## Run

```bash
.venv/bin/python scripts/cafe_views.py ontology_graph --input match.json \
    --workbook ~/Downloads/cafe-artifacts.xlsx --out var/out/views/<use-case>_ontology_graph.html
```

The workbook is the single source; this reads it with the corpus importer's own reader, so a table
is found by its marker exactly as the corpus names it. There is no bundled snapshot: the CAFÉ
tables include restricted-source content that never enters this repository.

## Admission reminder

A red node is a proposal, not an addition. The Ontology Council admits it through the ontology delta: a concept needs a definition, module, kind, steward, authoritative source (or an explicit gap), at least one relationship to an existing concept, and the use case or indicator that needs it. Point this out when the graph shows gaps.

## After rendering

Present the page, then summarise: matched / partial-or-enhancement / gap counts, the gap concepts and relationships (these form the ontology delta), and any unresolved ids.
