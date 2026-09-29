---
name: cafe-bpmn-flow
description: Turn a list of L3 capabilities (use-case sub-capabilities such as "1.1 Audio capture", or CAFÉ technology L3 IDs such as KNW.11) into a BPMN-style process flow — swimlanes, tasks labelled with their capability IDs, exclusive/parallel gateways, start and end events, sequence and message flows, and phase colouring for MVP → transitional → target — rendered as a self-contained HTML page. Use this whenever the user wants a process flow, BPMN, swimlane diagram, flow of capabilities, or phased/roadmap view of how a use case's capabilities work together, even if they only paste a capability list and say "show the flow".
---

# CAFÉ BPMN capability flow

Renders a phased BPMN-style process view in which **every task is an L3 capability**. It shows how the capabilities of a use case run in sequence, who performs each (lanes), where decisions branch (gateways), where information crosses lanes (message flows) and what is delivered in which phase.

## In this lab

The pipeline draws this view itself at step 10 (sequence the workflow): the `semantic_view_workflow` tool on semantic-mcp reads the
tables under the run's pin and stores the page by reference, and the approval shows it as a tab.
The renderer is `lab.core.usecase.views.bpmn` — the same code whether the pipeline or you run it.
Output is ONE self-contained HTML page (no browser is driven here, so no PNG): open it in a browser
and print to PDF from there.

A capability list alone is not a process, so this skill has two parts: **you** turn the list into a flow specification (lanes, order, decisions, phases), and the bundled script renders it deterministically.

## Step 1 — Build the flow specification from the capability list

Work from what the conversation already tells you (the functional decomposition, the capability match, the use-case description). Ask only for what you genuinely cannot infer — typically the phasing if none was stated.

1. **Lanes** — one per actor or system that performs capabilities (the active-structure elements of the decomposition): e.g. *Meeting owner*, *AI pipeline (system)*, *Consumers*. Keep to 2–5 lanes, top-to-bottom in the order work first appears.
2. **Tasks** — one per L3 capability that is *performed* as a step. Put the capability ID in `cap` and a short qualifier in `note` (≤ 25 characters). For CAFÉ technology L3 IDs (e.g. `KNW.11`) you may omit `name`; it is filled from the bundled technology capability map.
3. **Order** — sequence flows follow the behaviour of the decomposition (what triggers what). A start event opens the flow; an end event closes each path.
4. **Decisions** — add an exclusive gateway wherever the path depends on a condition (label it as the question, e.g. "conf ≥ τ ?"), and label its outgoing flows ("yes", "no / unsure"). Use a parallel gateway only for genuinely concurrent branches.
5. **Message flows** — dashed red flows for information that crosses lanes without passing control (e.g. "voiceprints → gallery", "usage record").
6. **Cross-cutting capabilities** (trust, governance, residency…) that apply to every step are not tasks: put them in an `annotation` node so the flow stays readable.
7. **Phases** — tag each task (and phase-specific gateways) `mvp`, `transitional` or `target`; give each phase a legend line in `phases`. If the user gave no phasing, omit `phase` and `phases` entirely.
8. **Check coverage** — every capability in the input list must appear as a task or in the annotation. Say which, if any, you left out and why.

## Step 2 — Layout

`col` (0, 1, 2 …) and `row` (0, 1 …, within the lane) are optional. Without them, nodes are placed left-to-right by flow depth inside their lane, and nodes reached only by message flows sit under their source. For flows longer than about seven steps in one lane, **snake**: put the return leg in `row: 1` running right-to-left (as in the example), which keeps the picture compact.

Edge `route` (default `auto`): `hv` right-then-down · `vh` down-then-right · `vhv` down-across-down · `hvh` · `below` / `above` (bypass under or over other nodes, e.g. a gateway's short-cut branch) · `right` (loop round the right-hand side). Use `offset` to separate parallel lines and `label_at` (`start`/`end`) or `label_side` (`above`/`below`) to place labels.

A complete worked example is bundled at `assets/example_speaker_tagging.json` — read it before writing a new spec; it shows lanes, snake layout, gateways, bypass route, message flows, annotation and phases.

## Run

```bash
.venv/bin/python scripts/cafe_views.py bpmn --input flow.json \
    --workbook ~/Downloads/cafe-artifacts.xlsx --out var/out/views/<use-case>_bpmn.html
```

The workbook is the single source; this reads it with the corpus importer's own reader, so a table
is found by its marker exactly as the corpus names it. There is no bundled snapshot: the CAFÉ
tables include restricted-source content that never enters this repository.

## Spec reference

```json
{
  "title": "Meeting speaker tagging — BPMN (L3 capabilities), phased MVP → transitional → target",
  "subtitle": "optional second line",
  "lanes": [{"id": "owner", "label": "Meeting owner"}, {"id": "ai", "label": "AI pipeline (system)"}],
  "phases": {"mvp": "MVP — tag-once", "transitional": "+ Transitional — …", "target": "+ Target — …"},
  "nodes": [
    {"id": "start", "type": "start", "lane": "owner"},
    {"id": "capture", "type": "task", "lane": "owner", "name": "Audio capture", "cap": "1.1", "note": "room / device", "phase": "mvp"},
    {"id": "gw", "type": "gateway", "kind": "exclusive", "lane": "ai", "label": "per-speaker channels?", "label_side": "left"},
    {"id": "tg", "type": "annotation", "lane": "ai", "col": 5, "span": 2.5, "text": "6 Trust & Governance … applies across all lanes"},
    {"id": "end", "type": "end", "lane": "ai"}
  ],
  "edges": [
    {"from": "start", "to": "capture"},
    {"from": "gw", "to": "capture", "label": "yes", "route": "below"},
    {"from": "capture", "to": "gw", "type": "message", "label": "metadata"}
  ]
}
```

Node types: `task`, `gateway` (`kind`: exclusive · parallel · inclusive · event), `start`, `end`, `intermediate`, `annotation`. Edge types: `sequence` (default, solid), `message` (dashed red, open arrow), `association` (dotted, no arrow).

## After rendering

Present the page and give a two- or three-sentence readout: lanes, number of capabilities per phase, the decision points, and any input capability not shown. Offer to adjust layout (explicit `col`/`row`, routes) if lines cross awkwardly — the first render of a new flow often benefits from one tidy-up pass.
