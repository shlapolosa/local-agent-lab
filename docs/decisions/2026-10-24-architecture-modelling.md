# Architecture modelling is intake's capability (24 Oct 2026)

**Status:** accepted by the user, 24 Oct 2026. **Owner:** the use-case intake agent.

## Context

Architecture is two capabilities, each with its own owner:

- **Modelling** turns every input artifact into the model. Owned by intake.
- **Visualisation** turns the model into views, Exchange XML, per-view SVG and the ADOIT import.
  Owned by the fabric / TO-BE session; its input is `contracts/archimate-spec.schema.json` (FR-11).

SAF (Solution Architecture Forum, a channel of the Documentation Fabric) needs "Word document → model
with provenance" and raised requests M-1..M-7. SAF builds a placeholder that mirrors these contracts
until the lab lands in the work tenant.

What intake did at commit 9120174:
- step 2 kept only the submission's TEXT;
- attachments and embedded figures were never read;
- the model was business-layer only, and application components came from the catalogue at step 21;
- relations came from structural rules only;
- `props.provenance` was an optional free string on step-4 elements;
- `Model.to_spec()` already returned the engine shape.

## Decisions

| # | Decision |
|---|---|
| D1 | M-1..M-7 are intake's backlog. M-2 is limited by D3. |
| D2 | visio_to_archimate's reading (the parse + vision reconcile in its BA) moves into intake's modelling. The visio workload stays as a thin caller of modelling. |
| D3 | Application and technology components the inputs DESCRIBE become their own elements, linked by realisation to the components step 21 SELECTS from the catalogue. They never replace the catalogue pick: cost stays a join on catalogue ids (G04). |
| D4 | One NEW modelling element schema, built on the visio BA's `ba_output.schema.json`, because that schema already requires provenance. It supersedes intake's step-4 element contract. |
| D5 | Provenance = `{source_ref, location: {page \| paragraph \| figure \| shape}, quote}`, REQUIRED on every element and every relation. A quote that is not found verbatim in its source is FLAGGED as an open question. It does not fail the gate. |
| D6 | The output is an ENVELOPE. The FR-11 spec sits inside it unchanged, exactly what visualisation consumes. Provenance, open questions and dropped relations sit beside the spec, not inside it. |
| D7 | Modelling is its own process (`architecture_modelling` ProcessSpec, externally startable). `use_case_screening` calls it, and SAF can start it without a screening. |
| D8 | The model gets its own human approval gate before visualisation and the ADOIT import: an architect checks the model against its provenance. |
| D9 | The contract file is `contracts/modelling.json`, semver. Every change is notified to SAF. |
| D10 | Order: M-4 + M-5 (provenance + envelope) first, because SAF mirrors those; then M-1, M-3, M-2. M-6 and M-7 ship with the first. |
| D11 | Build on `feat/usecase-intake-domain`. It was fast-forwarded to origin/main (033459a) on 24 Oct. |
| D12 (M-8) | The envelope carries a `references` block: `capabilities[]` and `realisations[]`, each tied to a model element, with status in the CAFÉ heatmap vocabulary (new / consumed / updated / missing). This is needed because the map matches live in element `props`, which FR-11 refuses. Built in slice 1 with M-4/M-5. |
| D13 (M-9) | M-2 covers EVERY layer, derived from the inputs: motivation (adds Outcome, Principle), strategy (adds ValueStream, CourseOfAction, Resource), business, data (DataObject realising BusinessObject), application (the systems the inputs describe) and technology (Node, SystemSoftware, TechnologyService, Device, network). Today application comes only from steps 5, 6 and 21, and technology is the single build-surface Node from step 20. Built with M-2. |
| D14 | Provenance read by vision is never treated as confirmed. An image source, or a `figure`/`shape` location, yields an `unverifiable` open question for the architect to verify at the D8 gate. |

### Contract 1.1.0: SAF's review (R-1..R-5) and visualisation's M-10, accepted 24 Oct

| # | Decision |
|---|---|
| D15 (R-1) | `reviews[]` in the envelope. On a re-run, a decision on an id that still exists carries over, one on a renamed id follows the rename, and one on a vanished id becomes a `review-orphaned` open question. |
| D16 (R-2) | `renamed_from {id: [old ids]}`, declared only on evidence (same provenance location or the same repository id), never guessed from names. |
| D17 (R-3) | Repository resolution is MODELLING. visio's `resolve_existing` moves here with D2, through the EA port's `ea_search`, as `references.repository[]` `{element_id, repository_id?, repository_class?, match, confidence, candidates[]}`. Built with M-1. |
| D18 (R-4) | `references.concepts[]` `{element_id, concept_iri?, label, scheme, status linked\|candidate, confidence}`: step 9's ontology check, published. |
| D19 (R-5, M-10) | ONE change vocabulary: `new \| updated \| consumed \| removed` for elements (`changes {element_id: status}` and the repository `match`). Capabilities add `missing`. `removed` comes only from an input that retires something. The vocabulary's one home is `lab.core.modelling.envelope.CHANGES`. Visualisation was scoped back the same day to the standard views visio_to_archimate produces today, so it ignores `changes` for now; SAF's impact path reads it. |
| D20 | Every id is an IRI local name `[A-Za-z0-9_-]+`, and the prefix table is published (`x-id-prefixes`). A business capability becomes `cap-<slug>` (today it is the raw map id `B1.1.2`, which breaks the rule). That mapper change lands in the wiring slice, and until then the builder flags such ids as `invalid-id`. |

## Slice 1 (24 Oct): new files only

These were added as new files only, because arch/to-be-seam moves `lab/workloads/usecase/*` into
`lab/core/usecase/`, and editing those files now would collide with that move:
- `lab.core.modelling` (`provenance`, `envelope`);
- `contracts/modelling.json` v1.0.0, draft;
- `contracts/archimate-spec.schema.json`, vendored from 8f9210c, same path.

Wiring them into the use-case steps (agent schemas requiring provenance, deriving `references` from
the model, the `architecture_modelling` ProcessSpec, the D8 gate) comes after that branch merges.
