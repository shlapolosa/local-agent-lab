---
name: visio-reader
description: >
  Read and interpret a system diagram — a Microsoft Visio (.vsdx) file OR a diagram image
  (PNG/JPEG) — together with any accompanying requirements documents (.docx/.pdf/.md/.txt)
  into a structured, plain-language description of the system: shapes (with their stencil/master
  or visual hint and caption) and the connectors between them (source, target, label), enriched
  with the behaviours, data, rules and actors the requirements make explicit. Use this skill
  whenever a business analyst or architect must understand an uploaded diagram or requirements
  pack, extract the system's actors, components, data and behaviours from it, or convert a
  drawing into a downstream model (e.g. ArchiMate). Covers how to turn loosely-drawn
  boxes-and-lines into a faithful system description without over-committing to a formal
  notation the diagram does not actually use, and how to use requirements as evidence rather
  than as a source of invented elements.
---

# Reading Visio into a system description

A Visio diagram is an *informal* picture: rectangles, icons and connecting lines a person drew to
communicate a system. It is NOT ArchiMate and carries no guaranteed semantics. Your job as the
Business Analyst is to read it faithfully and describe the system in plain language + light
structure, so an Architect can later formalise it. Do not invent a formal notation the drawing
does not support; describe what is drawn and what it evidently means.

## What the parser gives you

The deterministic ingest step (`scripts/read_vsdx.py`, run for you — you do NOT call it) returns:

```json
{
  "pages": ["Lab System"],
  "shapes":     [{"id":"1","text":"LiteLLM Proxy","master":"Component","type_hint":null,"page":"Lab System"},
                 {"id":"2","text":"Claims DB","master":"com.lucidchart.AzureSqlDatabase","type_hint":"DataObject","page":"Lab System"}],
  "connectors": [{"from":"LiteLLM Proxy","to":"/v1 (OpenAI)","label":"Composition","page":"Lab System"}]
}
```

- **`text`** is the human caption — the primary identity of the thing. Catalogue by it.
- **`master`** is the *stencil* the author dragged from (Component, Interface, Node, Actor, Data
  Store, Service, Process, an Azure / Lucidchart cloud icon…). A **strong, specific** stencil is
  **PRIMARY evidence for the element's ArchiMate type AND its layer** — treat it as ground truth for
  classification unless the connectivity plainly contradicts it. This matters most for the
  Technology layer: a server / database / network / storage stencil is a Node, SystemSoftware,
  CommunicationNetwork or Artifact, never a generic application component. Only a **weak, generic**
  stencil (a bare rectangle, an unlabelled box, a shape with no distinguishing master) yields to
  the caption and the connections.
- **`type_hint`** is the parser's own reading of a *typed* stencil: the mapped ArchiMate type
  (e.g. `Node`, `SystemSoftware`, `DataObject`, `Artifact`, `CommunicationNetwork`,
  `ApplicationComponent`) when the master is a recognised Lucidchart export (`com.lucidchart.*`)
  or an Azure-branded stencil; **`null`** for a native Visio master or one the parser does not
  recognise (nothing is inferred from a bare `Database.70`-style native shape). A non-null
  `type_hint` carries the same weight as a strong stencil — start from it, and only move off it
  when the connections make the hint impossible, recording why in `openQuestions`.
- **`connectors`** are directed `from → to` with an optional `label`. The label may be an ArchiMate
  relationship name (Composition/Assignment/Serving/Realization…), a verb ("calls", "routes to"),
  or empty. Use it as evidence of the *kind* of dependency, but you decide the real intent.

## How to interpret

1. **Read every shape and connector before classifying anything.** A **strong, specific stencil or
   `type_hint`** is PRIMARY evidence for type and layer; connectivity **corroborates** it and
   overrides only a **weak, generic** stencil (a bare box). An "Interface"-stencil box that
   everything routes *through* is an access point; a generic "Box" that *contains* others is a
   component or a node — decided from what it contains and what crosses it. Never flatten a
   Technology-layer stencil into a generic application component because of how it is wired.
2. **Group into aspects** as you describe: who acts on the system (**actors/roles**), the moving
   parts (**components / services / interfaces / functions**), the **data** it holds or moves, and
   the **behaviours** (processes, events, what calls what). Every shape should land in one group.
3. **Name a candidate ArchiMate aspect and type per element** — your best reading, e.g.
   `application / active — ApplicationComponent`, `technology / active — Node`,
   `application / passive — DataObject`. This is a *proposal* for the Architect, who will validate
   it against the semantic layer; flag anything you are unsure of in `openQuestions`.
4. **Preserve every relationship** with its direction and your reading of intent (e.g.
   "LiteLLM Proxy exposes /v1 (OpenAI)" from a Composition; "gateway serves the EA agent" from a
   Serving). Direction matters downstream — server→served, whole→part, realizer→realized.
5. **Interfaces are access points, not decoration.** If a service is reached *through* a shape,
   say so — that shape is the interface exposed by the owner and assigned to the service.
6. **Say what the picture does not tell you.** Missing types, ambiguous lines, orphan shapes, or a
   caption that contradicts its stencil all go in `openQuestions` rather than being guessed silently.

## Output contract

Emit the structured system description defined by `schemas/ba_output.schema.json` — `systemName`,
`summary`, `actors[]`, `components[]`, `data[]`, `behaviors[]`, `relationships[]` (each
`{from,to,type,intent}`), and `openQuestions[]`. Respond with **only** that JSON object — no prose,
no markdown fences. It is the validated contract handed to the Architect agent; a schema-invalid
response is rejected and you are asked to correct it.

## Diagram images and requirements documents

The same method applies when the diagram is a **raster image** instead of a `.vsdx`, and when
**requirements documents** accompany it. Inputs are named by an exact *source*: normally an
`art://` reference into the upload store, which you read ONLY through the gateway's governed
tools — `storage_read_vsdx` for a Visio file, `storage_read_document` for a document — or, in
local development, a file path read with `read_vsdx` / `read_document`. The message names the
tool for each source; call exactly that one with the source unchanged. Images are never a tool
for you: the diagram image and every figure embedded in a document are fetched (through the same
gateway, `storage_get` / `storage_extract_figures`) and **attached to the message** for you to
read directly. Sizing contract you can rely on: every attached image is at most 1600 px on its
longest edge, PNG or JPEG, with decorations (under 2 KB or 64 px) already dropped and at most 8
figures per document — so read them as-is, nothing is hidden behind a download.

**Reading an image diagram.** Every box (or icon with a caption) is a shape whose `text` is its
caption; every arrow is a connector `from → to` with the arrow-head giving direction and any text
on or beside it as the `label`. Visual cues split the same way stencils do: a **specific
infrastructure or product icon** (a server, database cylinder, network cloud, storage, queue, a
cloud-provider glyph) is PRIMARY type/layer evidence exactly like a strong stencil or `type_hint`;
plain boxes, colours, swim-lanes, containers and line styles are **weak** cues where the caption
and the connections decide. Read every box and every arrow before classifying anything. A grouping box around several
shapes usually means a boundary (a system, a node, a domain), not an element of its own — decide
from what crosses it. If an arrow-head or a label is genuinely unreadable, record that in
`openQuestions` rather than guessing a direction.

**Using requirements documents.** Requirements are *evidence about* the system the diagram
shows — they are not a second diagram. Read each one fully first, then use them to:
- name the **behaviours** (processes, functions, events, services) the diagram only implies;
- describe **data** precisely — what is held, what moves, who owns it;
- refine each element's `role` and `candidateType` (a "portal" that requirements describe as
  a channel for citizens is an interface, not a component);
- surface business rules, SLAs, volumes and constraints in the `summary`.
An element that exists only in the requirements is not invented silently: if it is plainly a
component/actor of *this* system, include it and mark its `role` with `source: requirements`;
otherwise raise it as an `openQuestion`. A conflict between the diagram and the requirements is
always an `openQuestion` quoting both sides. Never paste requirements prose into the output.

**Figures embedded in documents.** Requirements packs carry diagrams and screenshots the text
never spells out. They are extracted from the document (its image parts / page images) and
attached alongside the main diagram, labelled "figure N embedded in <document>". Read each one
with the image rules above; treat what it shows as evidence of the same weight as the document
text, and cite the figure in `intent`/`openQuestions` when it is your source. Decorative images
(logos, icons) carry no system meaning — ignore them.

## Boundaries

- Reading is local, read-only file I/O — nothing about the Visio egresses except what you write into
  the description (which is then PII-scanned at the gateway like any prompt).
- Multiple pages are common; keep each element's `page` in mind and describe the system as a whole.
- You do not render, validate against ArchiMate, or write to any repository — that is the Architect
  agent (`archimate-adoit` skill) and the governed tools downstream. Stay in the analysis lane.
