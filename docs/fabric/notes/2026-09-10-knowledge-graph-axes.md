# Note 001 — Knowledge hangs off nothing: three typed axes, not a work-item hub

**Status:** agreed 2026-09-10 (design discussion) · **Supersedes:** initiative doc v1.0 principle 6 and FR-2 as worded
**Applies to:** the semantic layer's ontology, the catalog, the competency questions, the capability maps v1.6+

## Decision

The Azure DevOps work item is **one class in the ontology and the source of one edge type**, not the key
the catalog is built on. An artifact's identity is its own IRI (Catalog Management). Knowledge is a graph
with three typed axes, and "hanging off" something is a **query choice**, never a storage decision.

| Axis | Edge captured by (map 1.6b) | Answers | Serves |
|---|---|---|---|
| Delivery | Traceability Management · Delivery Association | why, when, by whom, together with what | Currency: impact, re-drafting, accountability |
| Structural | Traceability Management · Reference Extraction | what points to what | Currency: impact chains |
| Subject | Knowledge Classification · Concept Linking | what it is about | Discovery: search, clustering, dedup, expertise |

Ownership is a fourth axis for Governance, resolved from the owner map — never inferred from a work item's assignee.

## Why the work item stays essential (narrowly)

A business concept is timeless and unowned; it cannot say what changed, who is accountable, or what was
produced together and is therefore likely to invalidate each other. A work item is an event-bounded
container with an owner and a lifecycle — what change propagation needs. It is also the **cheapest strong
edge** in the design: captured at creation, deterministic, rung 1 of the association ladder. Principle 7
forbids concept co-occurrence as an impact edge and reference edges are sparse, so without delivery edges
the currency loop has almost nothing trustworthy to traverse.

**The ADO operating decision (§5.3) survives; its justification changes**: from "knowledge is keyed to
work" to "delivery edges are the only affordable trusted edges".

## Why business constructs are the primary discovery axis

People ask "what do we have on claims adjudication", "what constrains the Malaffi integration" — never
"what was delivered under PBI-4471". Coding agents ground on a system or a feature. Clustering,
recommendation, dedup and expertise run on subject edges. The constructs are the business architecture's
own vocabulary — capabilities, value streams, information concepts, products, systems, processes — most
of which already exist in the EA repository and the capability reference models. **The EA repository is
therefore a vocabulary SOURCE as well as a system of record**, and linking artifacts to constructs is the
same cross-mapping technique used to overlay the initiative on the enterprise capability map.

## Consequences

1. **Principle 6 is reworded**: *"Every artifact carries its own identity; every delivery artifact
   carries its work-item association."*
2. **FR-2 splits** into (a) identification — every captured artifact gets one IRI and a pointer to its
   system of record — and (b) association — delivery edges via the ladder, reference edges by extraction,
   subject edges by concept linking; each with provenance.
3. **"Unassociated" is a legal, complete state for non-delivery artifacts** (standards, policies,
   reference models, runbooks): subject edges + owner, no delivery edge. The steward's orphan queue holds
   only artifacts that *look like* delivery work and lack a parent.
4. **Work items are themselves concept-linked** (title, description, area path, linked artifacts), so
   orphan-to-work-item suggestion is a graph question with an explainable card, not a text-similarity score.
5. **Impact analysis traverses delivery + structural edges only**; discovery traverses subject edges;
   both from one store partitioned by provenance (constructed / extracted / human-confirmed / suggested).
6. **No change to the capability maps** — Traceability Management already holds both association kinds;
   Concept Linking already sits under Classification (assigning a subject is classification, not association).
7. **One competency question was missing** — the combined form a reviewer actually asks: CQ-27 in
   `competency-questions.md`.

## Related
- `docs/fabric/competency-questions.md` (draft 0.3)
- `docs/fabric/capability-map-v1.6b-km-capability.png` · `capability-map-v1.6d-km-technology.png`
- Initiative doc v1.0 §5.3 "The association model", principle 6, principle 7, FR-2, NFR-7
