# Visio → ArchiMate conversion method (greenfield)

The shared method both agents ground in. It is deliberately small and opinionated; the exact
ArchiMate vocabulary and the legal-relationship matrix live in the `semantic/` layer, which the
workflow calls to validate the Architect's output.

## The pipeline in one line

Informal Visio drawing → **BA** reads it into a plain-language, lightly-typed system description
(`ba_output.schema.json`) → **Architect** formalises that into an ArchiMate engine spec → the
workflow validates the spec against the semantic matrix, renders it, and stages it for approval.

## Classification order (how to type an element)

1. **Behaviour first.** Ask what the system *does* — the services and functions/processes. Behaviour
   is the backbone; active and passive structure hang off it.
2. **Active structure next.** What *performs* each behaviour — components, nodes, actors, roles,
   system software. A component is assigned to the function it performs; a node hosts software.
3. **Passive structure last.** What behaviour *acts on* — data objects, artifacts, information.
   Access relationships point from behaviour to these.
4. **Layer** follows from the thing: Business (people/process/product), Application (software
   components/services/data), Technology (nodes/system software/infrastructure services),
   Motivation (drivers/goals/principles/requirements), Strategy, Implementation. A **strong,
   specific stencil / `type_hint` / infrastructure icon is PRIMARY evidence** for type and layer;
   connectivity corroborates and overrides only a **weak, generic** stencil. In particular, a
   technology/infrastructure stencil (VM, server, database, storage, network) yields a
   Technology-layer element (Node / Device / SystemSoftware / Artifact / CommunicationNetwork) — do
   not flatten it into a generic ApplicationComponent.

**Classify each element on its own evidence (anti-anchoring).** Layer is per-element; an overall
"this is an X diagram" impression must never override an individual element's stencil, connectivity,
or text. Do not classify the diagram as a whole — a lone Technology node in an application diagram
stays Technology.

## Relationship strictness ladder (pick the *weakest* relation that is still true)

From strongest to weakest structural bond — do not over-claim:

1. **Composition** — whole owns part; the part cannot exist without the whole (a component *owns*
   its interface).
2. **Aggregation** — grouping; parts exist independently.
3. **Assignment** — an active element *performs* a behaviour, or an interface is assigned to the
   service it exposes (interface → service).
4. **Realization** — something realises a more abstract thing (component realises a service;
   function realises a service).
5. **Serving** — one element *provides/serves* another (a service serves a consumer). Prefer this
   for "A uses/depends-on B" when nothing stronger is evidenced.
6. **Access** — behaviour reads/writes a **passive** element (must target data).
7. **Triggering / Flow** — temporal / information handoff between behaviours.
8. **Influence** — a motivation element affects another (weak, non-structural).
9. **Association** — last resort when a line clearly exists but its nature is unknown.

Direction is part of the meaning: server→served, whole→part, realizer→realized, performer→behaviour.

## Interfaces are access points, not decoration

An interface is *the* access point of a service. When a service is reached **through** a shape,
model it as: `Composition owner → interface` **and** `Assignment interface → service`. A consumed
service with no assigned interface is a warning, not an error. Business channels are
`BusinessInterface`s realised by the `ApplicationInterface` that implements them.

## Functions are the decomposition unit

A component is *assigned to* a function; the function *realises* a service. Decompose behaviour into
functions rather than nesting components inside components.

## Reconciling multiple representations of one diagram

The BA may get BOTH a **structured parse** and a **rendered image** of the same diagram. They are
complementary, and each is authoritative for different things — do not treat one as a lesser copy:

- The **deterministic parse** is authoritative for element **identity, text, native connectors, and
  stencil/`type_hint`**. Never drop a parsed element because the image did not show it.
- The **rendered image** is authoritative for **grouping / containment** (which boxes sit inside
  which zone / swim-lane = subsystems or domains) and for **connectors the parse missed** (e.g.
  Lucidchart lines that never became native connectors).
- A connector marked **`recovered: "geometry"`** sits between the two: the file did not declare it,
  the parser reconstructed it from the line's endpoint geometry (`match_distance` = how tight the
  match was). Keep it, confirm it against the image, and raise a doubtful one as an `openQuestion`.
- When NO image is available (the deployment cannot render Visio), the parse is the only
  representation: read containment from its own evidence and record what it cannot settle.
- Where they **disagree**, prefer the deterministic source for identity and raise the disagreement
  as an `openQuestion`.

Every element carries a `provenance` OBJECT — `{"source": diagram|document|requirements,
"representation": structure|vision|document}` — recording which source it came from and how it was
read (a parsed shape = diagram/structure; a rendered image or figure = diagram/vision; a design or
requirements document = document|requirements / document).

## Documents: design (a source) vs requirements (evidence)

Documents reach the BA tagged with a role, and the role decides how far they may go:

- A **design** document (a technical / high-level-design of THIS system, including embedded
  component diagrams) is a **PRIMARY architecture source**, on a par with the diagram — it MAY
  contribute first-class elements (each with `provenance: {"source":"document","representation":"document"}`).
- A **requirements** document is **evidence, not new boxes** — the *why and what must be true*. An
  element existing only in requirements is added only if plainly part of this system; otherwise it
  is an `openQuestion`.

## What each agent must NOT do

- The **BA** does not pick final ArchiMate types with authority or draw anything — it proposes
  (`candidateType`) and flags doubt in `openQuestions`. It never emits an engine spec.
- The **Architect** does not read the Visio or invent elements absent from the BA description — it
  formalises what the BA described, correcting obvious mis-classifications against the matrix, and
  emits the engine spec only. Rendering, XSD validation, and repository writes are governed tools
  downstream, not the agent's job.
