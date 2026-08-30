# Method: from requirements to an ArchiMate architecture

## Who does what (read this first)

This skill is the **deterministic half** of architecture work: vocabulary, layout, view
derivation, validation, XML emission, ADOIT import mechanics. The **judgment half** —
reading requirements and deciding what the elements and relationships *are* — belongs to the
architect agent using the skill. This file is the method that agent follows so that every
architect (business, application, technology, or a human) decomposes the same way; the skill
then validates and renders whatever they decide.

Runtime split (lab architecture): the engine is a plain library. Claude Code agents import it
directly. The own-built `adoit-mcp` server imports the *same* library and exposes it behind the
LiteLLM gateway — read/query tools shared to all processes, write/import tools ACL-restricted to
the EA Modeling Agent with approval gates. Only the ADOIT-facing facade needs MCP governance;
generation and validation are pure functions and stay callable everywhere.

Sourcing decisions (Aug 2026): the MCP server starts from the `archimate-mcp` PyPI package
(model engine + MCP tools, OEF import/export) extended with the ADOIT facade and this engine as
its layout layer — evaluate before writing from scratch. The library core stays owned (the
layout *policy* is the differentiator); `pyArchimate` is the designated seam if model
*reading*/merging (round-trip with ADOIT, Archi/ARIS files) is ever needed — extend the seam,
not our emitter. For the future solution-architect (EA→SA in draw.io/mermaid): our own
`drawio_c4.py` engine (health-service-idp) is the renderer; `mcp-Archimate` (github
RMRanjit/mcp-Archimate) is the reference for ArchiMate→C4/draw.io mapping.

## Decomposition (strict ArchiMate, per layer)

Work layer by layer, and within each layer ask the three aspect questions in this order:

1. **Behaviour first** — what happens? Verbs in the requirements become processes/functions;
   the *offer* someone consumes becomes a Service (one per consumer-facing capability, not one
   per function). Events are the things that start or interrupt behaviour.
2. **Active structure** — who/what performs each behaviour? Actors and roles (business),
   components (application), nodes/devices/system software (technology). Every behaviour needs
   exactly one Assignment from its performer; if you can't name the performer, the behaviour is
   speculative — cut it or flag it.
3. **Passive structure** — what is acted upon? Business objects, data objects, artifacts.
   Only model data that at least one behaviour Accesses; unreferenced data is inventory, not
   architecture.

Then relationships, in decreasing strictness — use the strongest relationship that is true:
Composition/Aggregation (structure) → Assignment (who performs) → Realization (what makes the
abstract concrete, incl. cross-layer: component realizes service, artifact realizes data
object) → Serving (who offers to whom — this defines the vertical reading of every view) →
Access (behaviour ↔ data, with accessType) → Triggering/Flow (sequence/transfer between
behaviours) → Association (last resort; if you reach for it, ask what you actually mean).

Cross-layer stitching: each layer's services are what the layer above consumes (Serving up);
each layer's components realize the services above them. Motivation connects via Realization
(outcome/goal realized by capability) and Influence. Strategy connects via Realization
(capability realized by business elements) and Assignment (resource to capability).

**Do not nest by default.** Embedding elements inside others hides the relationship the nesting
stands for, and mapping views live off visible relationships. Draw the line instead. Reserve
`container()` for genuine co-location boxes (e.g. middleware deployed inside a host) where the
drawn alternative would be pure clutter — and even then the model still carries the explicit
relationship.

## Interfaces, functions and services — the strict reading

- An **interface** is the access point where a service is made available: `Composition`
  from its owner (component / role / node) and **`Assignment` to the service it exposes**.
  Business interfaces are channels (portal, chat, counter); application interfaces are APIs,
  UIs, protocol endpoints; technology interfaces are ports/protocols. The application
  interface that implements a business channel `Realization`s the business interface.
- A **function** is the internal unit of work (verb + object) — the functional decomposition:
  `Assignment` component/role → function, `Realization` function → service. A component may
  realize a service directly only when no decomposition is modelled.
- A **service** is the externally visible outcome (noun phrase). Consumed services without an
  assigned interface are flagged by the semantic layer.
- Every type has its own notation (see `archimate-classification.json` and the cheat sheet);
  classification is checked against the semantic layer's taxonomy and the complete
  relationship matrix, not by intuition.

## Standard view catalogue

`Model.standard_views()` derives these automatically from the finished model (views whose
layers are empty or relationship-free are skipped):

| View id | Content | Question it answers |
|---|---|---|
| `mot-strategy` | Motivation + Strategy | why do we act, with what capabilities |
| `strategy-biz` | Strategy + Business | which business services/processes realize the capabilities |
| `biz-app` | Business + Application | what applications serve the business |
| `app-tech` | Application + Technology + Physical | what runs the applications |
| `impl-roadmap` | Implementation (+1-hop neighbours) | work packages, plateaus, gaps — the roadmap |
| `full` | everything | the all-in-one reading, top of canvas to bottom |

Hand-built views (`m.view()` + `place()`) remain the right tool for *scoped* views — one
business process, one governance plane — where you choose the cast. Rule of thumb: catalogue
views for coverage, scoped views for storytelling; both can coexist in one model/import.

## Quality gates before hand-off

- Every Service has a Realization from below and a Serving to above (no orphan offers).
- Every behaviour has a performer (Assignment); every datum is Accessed.
- Zero render violations (`strict=True` passes).
- Element ids stable across regenerations (ADOIT matches by import, duplicates by name).
