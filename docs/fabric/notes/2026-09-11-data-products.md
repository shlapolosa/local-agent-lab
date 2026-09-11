# Note 004 — The fabric is four metadata products and one aggregate; competency questions are their features

**Status:** agreed 2026-09-11 · **Applies to:** `competency-questions.md` (draft 0.4), the conceptual view,
Purview Unified Catalog registration at Target.

## Decision

Using data-mesh vocabulary (Dehghani: domain-owned, discoverable, addressable, self-describing,
interoperable, secure; input ports, output ports, service levels, an owner):

| Product | Holds (metadata only) | Owner | Output ports | Service level |
|---|---|---|---|---|
| Knowledge Catalog | pointers, lifecycle state, owner, label, baseline | fabric; per-artifact owner from the owner map | catalog tools, SPARQL | metadata-only fitness function; currency |
| Traceability Graph | delivery, reference, subject edges with provenance | fabric; stewards confirm | traversal tools, SPARQL over chosen provenance graphs | edge precision (NFR-7); impact over C·X·H·D only (never S; a D edge carries the weakest of its inputs) |
| Vocabulary | concept schemes, ontology, alignments | the steward | SKOS export, term-store sync, MCP | concept lifecycle; alignments human-confirmed |
| Change Events | inbound and finished streams | platform | subscriptions | durable, at-least-once, idempotent per pointer |
| **Knowledge Layer facade** (aggregate) | nothing of its own — composes the four | fabric team | composite tools (the MCP door for agents, the search facade for people) | the WEAKEST of its constituents, per answer |

**The embedding index is not a product.** It is derived, rebuildable data (from catalog records via the
content port) used as a mechanism by composite answers (dedup, recommendation, association suggestion). It
has no owner distinct from the fabric and no consumer that reads it directly.

## Composite ownership (the concern, and the rule)

A composite question (CQ-08, 15, 16, 19, 20, 24, 26, 27) is a feature of the **aggregate** product, which
has its own owner — the team that runs the facade. Constituents keep their owners, service levels and
provenance. The aggregate (1) never writes to a constituent; (2) inherits the weakest constituent service
level per answer; (3) returns per-constituent provenance; (4) is the only place a cross-product query is
implemented. This is the standard source-aligned → aggregate → consumer-aligned pattern; it keeps
ownership single-homed without pretending composites do not exist.

## Competency questions as features

A CQ is a functional feature of its product's output port: the SPARQL/tool call is the implementation and
the fixture-triples test is the acceptance (BDD applied to a data product). The rest of a product's
specification is its **contract**: schema, provenance partitions, service levels, access rules, lineage —
not expressed as CQs. The CQ groups partition cleanly by product (draft 0.4), which is evidence the product
boundaries are real rather than imposed.

## Target-state mapping
Each of the five registers as a Purview Unified Catalog **data product**; the metadata-only rule is each
product's primary fitness function. See also [[2026-09-11-ports-adapters-events]] (note 003) and
[[2026-09-10-knowledge-graph-axes]] (note 001).
