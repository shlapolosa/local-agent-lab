---
name: visio-reader
description: >
  Read and interpret Microsoft Visio (.vsdx) diagrams into a structured, plain-language
  description of the system they depict — shapes (with their stencil/master hint and caption)
  and the connectors between them (source, target, label). Use this skill whenever a business
  analyst or architect must understand an uploaded Visio diagram, extract the system's actors,
  components, data and behaviours from it, or convert a Visio drawing into a downstream model
  (e.g. ArchiMate). Covers how to turn loosely-drawn boxes-and-lines into a faithful system
  description without over-committing to a formal notation the diagram does not actually use.
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
  "shapes":     [{"id":"1","text":"LiteLLM Proxy","master":"Component","page":"Lab System"}],
  "connectors": [{"from":"LiteLLM Proxy","to":"/v1 (OpenAI)","label":"Composition","page":"Lab System"}]
}
```

- **`text`** is the human caption — the primary identity of the thing. Catalogue by it.
- **`master`** is the *stencil* the author dragged from (Component, Interface, Node, Actor, Data
  Store, Service, Process…). Treat it as a **soft hint** to intent, never as ground truth — authors
  reuse whatever stencil is handy. Weigh it against the caption and the connections.
- **`connectors`** are directed `from → to` with an optional `label`. The label may be an ArchiMate
  relationship name (Composition/Assignment/Serving/Realization…), a verb ("calls", "routes to"),
  or empty. Use it as evidence of the *kind* of dependency, but you decide the real intent.

## How to interpret

1. **Read every shape and connector before classifying anything.** The meaning of a box comes from
   how it connects, not from its stencil alone. An "Interface"-stencil box that everything routes
   *through* is an access point; a "Box" that *contains* others is a component or a node.
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

## Boundaries

- Reading is local, read-only file I/O — nothing about the Visio egresses except what you write into
  the description (which is then PII-scanned at the gateway like any prompt).
- Multiple pages are common; keep each element's `page` in mind and describe the system as a whole.
- You do not render, validate against ArchiMate, or write to any repository — that is the Architect
  agent (`archimate-adoit` skill) and the governed tools downstream. Stay in the analysis lane.
