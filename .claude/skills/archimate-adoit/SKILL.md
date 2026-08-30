---
name: archimate-adoit
description: >
  Generate ArchiMate 3.1 architecture models and views as Model Exchange XML that imports
  cleanly into ADOIT (also Archi/BiZZdesign), with a deterministic layout engine that produces
  orthogonal, parallel, equally-spaced connectors, preserved layer bands, and interfaces drawn
  as icons. Use this skill whenever the user asks to model architecture in ADOIT or ArchiMate,
  create/update architectural views or diagrams (business, application, technology, motivation,
  strategy layers), export architecture to ADOIT, or draw enterprise-architecture diagrams of
  any system — even if they just say "add this to the EA repository", "diagram this
  architecture", or "create the views for X".
---

# ArchiMate views for ADOIT

Turn architecture content (documents, conversations, code) into an ArchiMate model with laid-out
views, emitted as `.archimate.xml` for ADOIT import plus an `.svg` preview per view.

## Workflow

1. **Model first, views second.** Identify elements (exact ArchiMate types — see
   `references/archimate-3.1-reference.md` for the full vocabulary and the layer×aspect grid) and
   relationships (direction matters: server→served, realizer→realized). Getting relationship
   direction right is most of the work — the layout derives from it.
2. **Write a generator script** (keep it in the repo, e.g. `architecture/gen_<name>.py`, so views
   are regenerable) that uses the engine:

```python
import sys; sys.path.insert(0, "<this-skill>/scripts")
from archimate_engine import Model

m = Model("Lab Platform")
m.el("gw",   "ApplicationComponent", "LiteLLM Proxy", doc="Gateway for /v1, /mcp, A2A")
m.el("v1",   "ApplicationInterface", "/v1 (OpenAI)")     # interfaces auto-render as icons
m.el("route","ApplicationService",   "Model Routing")
m.el("host", "ApplicationComponent", "Workflow Host")
m.rel("Composition",  "gw", "v1")
m.rel("Realization",  "gw", "route")   # gw realizes the service
m.rel("Serving",      "route", "host") # service serves the host -> host floats above it

v = m.view("gov", "Governance Plane")   # scoped view: you choose the cast
v.place("gw", "v1", "route", "host")   # rank/order optional; layout is automatic
v.auto_edges()                          # draws all relations between placed elements
m.standard_views()                      # + the standard mapping catalogue (see below)
report = m.render("architecture/out", "lab")   # XML + SVG per view; raises if invariants break
```

   One `Model` may hold many views; elements shared across views stay one catalogue object in
   ADOIT. **Avoid nesting/containers by default** — embedding hides the relationship it stands
   for; draw the line instead. `v.container()` exists only for genuine co-location boxes.

   Before rendering, when the lab's semantic layer is reachable (`semantic_*` MCP tools via the
   gateway, or `semantic/` importable), **classify with it and validate with it**:
   `semantic_classify("<concept in words>")` gives candidate types with definitions;
   `semantic_check(src, rel, tgt)` / `semantic_validate_model(spec)` apply the exact ArchiMate
   relationship matrix and the interface rule (every consumed service needs an interface
   assigned to it). Load the model (`semantic_load_model`) to answer traceability questions
   (`semantic_ask`). Previews render real ArchiMate notation per type — if everything looks
   like the same box, the classification is wrong, not the renderer.
3. **Render and self-check.** `render()` enforces the layout invariants (orthogonal-only,
   no overlaps/crossings, equal lane spacing, Serving/Realization pointing upward). On an
   AssertionError, fix the *model* (usually a reversed relationship), not coordinates — see
   `references/layout-rules.md` for what each violation means. The report also carries
   `warnings` from `validate_relations()` — ArchiMate legality checks (Access must target
   passive, Influence must target motivation, no cross-layer composition, …). Resolve every
   warning before hand-off; they are the "strict ArchiMate rules" gate.
4. **Review the SVG preview** (open it or attach to an artifact) before offering the XML for
   import. Check: layers banded correctly, no visual clutter, labels readable.
5. **Hand off for import** following `references/adoit-import.md` — includes the ADOIT:CE UI
   steps, the duplicate-handling behaviour, and the post-import checklist (interface icon
   toggle, layout survival). Note ADOIT:CE has no working REST write API; UI file import is
   the write path.

## Standard view catalogue

`m.standard_views()` derives the cross-layer mapping views automatically: motivation→strategy,
strategy→business, business→application, application→technology/physical, implementation &
roadmap, and the all-in-one `full` view. Empty/relationship-free views are skipped, so it is
always safe to call. Use catalogue views for coverage, hand-built scoped views for
storytelling. `m.layer_view(vid, title, layers, expand=)` builds a custom slice.

## Building an architecture from scratch

When starting from requirements (not an existing description), the *decomposition* — identifying
behaviour, then active structure, then passive structure, then relationships — is the calling
agent's reasoning job, not this skill's. Follow the method in `references/method.md` (aspect
questions, relationship strictness ladder, quality gates), then feed the result through the
engine, which validates and renders it. That file also defines the skill/agent/MCP boundary:
this skill is the deterministic library; the ADOIT-facing facade (catalogue reads, governed
writes) belongs to the `adoit-mcp` server which imports the same engine.

## Rules of thumb

- Element ids: short, stable, alphanumeric (`gw`, `presidio`, `entra`) — they become ADOIT
  identifiers (`id-<eid>`) and should not change between regenerations, or ADOIT will import
  duplicates instead of matching.
- One view per concern (governance plane, one business process, technology footprint) rather
  than one mega-view; ~8–20 elements per view stays readable. Elements can appear on many views.
- Use `rank=`/`order=` overrides sparingly; prefer fixing relationships. Use `doc=` on elements
  — it becomes searchable documentation in the ADOIT catalogue.
- Access relationships take `accessType="Read"|"Write"|"ReadWrite"`.

## References

- `references/method.md` — requirements→architecture method, view catalogue, skill/agent/MCP boundary
- `references/archimate-3.1-reference.md` — element/relationship vocabulary (read when choosing types)
- `references/layout-rules.md` — layout spec + how to interpret violations (read when a view fights you)
- `references/adoit-import.md` — ADOIT import steps, minimum fields, post-import checklist
- `references/archimate-3.1-cheatsheet.pdf` — visual notation poster (for humans)
