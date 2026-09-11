# Documentation Fabric — semantic layer competency questions (draft 0.4)

Method: Grüninger & Fox (1995). A competency question (CQ) is a question the semantic layer must
answer; the ontology is complete when every CQ has a SPARQL query that answers it over fixture
triples. Each CQ becomes a unit test in `tests/unit/core/semantic/` before any production triple exists.

**Grouped by data product (note 004).** The fabric is four metadata products sharing one ontology —
Knowledge Catalog, Traceability Graph, Vocabulary, Change Events — plus one aggregate product, the
Knowledge Layer facade, which owns every COMPOSITE question. The embedding index is NOT a product: it is
derived, rebuildable data used as a mechanism by composite answers. A CQ is a functional feature of its
product's output port: the SPARQL/tool call is the implementation, the fixture-triples test is the acceptance.

Columns: **Capability** is the L3 group and L4 capability (with the L5 line where one applies) the
question exercises, using the names in `capability-map-v1.6b` / `v1.6a`; *CONSUMED* marks a question
answered by an estate capability the fabric uses but does not own. A question that needs two L4s to
answer is a MECE warning on the map, not on the question. **Graphs** names the provenance partitions the query may read:
C = constructed, X = extracted, H = human-confirmed, S = suggested; O = observed (Change Events, not in the graph) and D = derived (recomputed) per note 005. **Phase** follows the initiative doc.

## Product 1 — Knowledge Catalog

Owner: the fabric, per-artifact ownership resolved from the owner map. Output ports: catalog tools, SPARQL. Service level: metadata-only fitness function (CQ-03), currency.

| ID | Question | FR / NFR | Capability (L3 · L4 · L5, per map v1.6b / v1.6a) | Graphs | Phase |
|---|---|---|---|---|---|
| CQ-01 | Given a source-system item (SharePoint file id, ADO work item id, EA object id), what is its one fabric IRI, and does it resolve back to the system of record? | FR-2, NFR-2 | Organisation · Catalog Management (Artifact Identification, Location Reference Management) | C | MVP |
| CQ-02 | Which artifacts exist in the catalog with lifecycle state *pending*, *published*, or *unassociated*? | FR-2, FR-7 | Organisation · Catalog Management (Lifecycle State Management) | C | MVP |
| CQ-03 | Does any catalog record hold document body content? (Must be answerable and must answer *none*: the NFR-2 fitness function.) | NFR-2 | Organisation · Catalog Management (Location Reference Management — fitness function) | all | MVP |
| CQ-04 | For a published artifact, which SharePoint version was baselined and when, and which projection(s) were rebuilt from it? | FR-7 | Production · Version Management; Currency · Republication | C | MVP |
| CQ-12 | What is the document type of artifact A, was it confirmed or only suggested, and by what? | FR-3 | Production · Knowledge Classification (Type Classification) | H, S | MVP |
| CQ-13 | Who owns artifact A and which sensitivity label does it carry, and from which authoritative source was each resolved? (Must never be answerable from S.) | FR-3, NFR-3 | Production · Knowledge Classification (Owner Resolution, Sensitivity Resolution) — consumes Identity & Access Mgmt | C | MVP |
| CQ-14 | Which artifacts of type T are owned by person P? | FR-3, FR-6 | Governance · Ownership & Stewardship (Owner Assignment) | C | MVP |
| CQ-21 | For principal P, which artifacts may be returned at all, given the labels P may read? (The same answer for a person and for an agent acting for P.) | FR-9, NFR-3, NFR-8 | CONSUMED · Identity & Access Management (Principal Scoping) — parity for people and agents | C | MVP |
| CQ-25 | Where does the catalog disagree with the source system (deleted, moved, relabelled)? (Reconciliation sweep.) | 5.x reconciliation | Currency · Catalog Reconciliation (Drift Detection) | C | Transitional |

## Product 2 — Traceability Graph

Owner: the fabric; stewards confirm edges. Output ports: traversal tools, SPARQL over chosen provenance graphs. Service level: edge precision per NFR-7; impact served over C · X · H only.

| ID | Question | FR / NFR | Capability (L3 · L4 · L5, per map v1.6b / v1.6a) | Graphs | Phase |
|---|---|---|---|---|---|
| CQ-05 | Which artifacts are delivered under work item W? | FR-2 | Production · Traceability Management (Delivery Association) | C, X, H | MVP |
| CQ-06 | Under which work item is artifact A delivered, by which rung of the association ladder, and with what confidence? | FR-2, NFR-7 | Production · Traceability Management (Delivery Association, provenance) | C, X, H, S | MVP |
| CQ-07 | Which artifacts have no delivery association (the steward orphan queue), ordered by age and traffic? | FR-2, FR-12 | Production · Traceability Management (Orphan Management) | C, X, H | MVP |
| CQ-09 | Which artifacts reference artifact A (an embedded diagram, a link, an ID mention), and which does A reference? | FR-2 | Production · Traceability Management (Reference Extraction) | X, H | MVP |
| CQ-10 | Which artifacts are downstream of changed item X over *trusted* edges only, to bounded depth N? (Impact analysis; S is excluded by definition.) | FR-7, NFR-7, NFR-9 | Currency · Change Impact Analysis (Impact Chain Determination, Impact Scope Bounding) | C, X, H | Transitional |
| CQ-11 | Which edges are older than the operating-model adoption date and were neither harvested from an explicit reference nor human-confirmed? (Back-book exclusion.) | NFR-7 | Production · Traceability Management (provenance); Currency · Change Impact Analysis | C, X, H | Transitional |

## Product 3 — Vocabulary

Owner: the steward. Output ports: SKOS export, term-store sync, MCP. Service level: concept lifecycle (propose → accept → deprecate), alignments human-confirmed.

| ID | Question | FR / NFR | Capability (L3 · L4 · L5, per map v1.6b / v1.6a) | Graphs | Phase |
|---|---|---|---|---|---|
| CQ-17 | Which labels proposed by tagging matched no concept in any scheme, and how many artifacts carry each? (Proposed-concept queue.) | FR-3 | Organisation · Vocabulary Management (Concept Lifecycle Management) | S | MVP |
| CQ-18 | Which concepts in scheme A align to which concepts in scheme B, and who confirmed each alignment? | — | Organisation · Vocabulary Management (Vocabulary Alignment) | H | Transitional |

## Product 4 — Change Events

Owner: the platform. Output ports: subscriptions on the inbound and finished streams. Service level: durable, at-least-once, idempotent per pointer (note 003).

| ID | Question | FR / NFR | Capability (L3 · L4 · L5, per map v1.6b / v1.6a) | Graphs | Phase |
|---|---|---|---|---|---|
| CQ-22 | For artifact A, what is the full audit chain: which event triggered synthesis, which model call drafted it, who approved it, when, through which channel, and which propagation followed? | FR-7, NFR-4 | CONSUMED · Audit Management (Audit Query) over fabric-recorded events | C | MVP |
| CQ-23 | Which fabric-originated writes exist, and has any re-entered the pipeline as a change event? (Loop guard; must answer *none*.) | NFR-9 | Currency · Change Detection (Change Attribution) | C | MVP |

## Composite — the Knowledge Layer facade (aggregate product)

**Ownership rule (resolves the composite-ownership concern).** In data-mesh terms a composite is an
*aggregate* (consumer-aligned) product with its OWN owner — the fabric team that runs the facade — while
every constituent keeps its owner, service level and provenance. The aggregate: (1) never writes to a
constituent; (2) inherits the WEAKEST service level among its constituents (a composite over trusted edges
and a suggested concept is only as trustworthy as the suggestion); (3) returns per-constituent provenance in
its answer so a consumer can see which part came from where; (4) is the ONLY place a cross-product query is
implemented — no constituent product answers a composite question. A composite needing many products is by
design here, not a MECE warning.

| ID | Question | FR / NFR | Capability | Graphs | Phase | Constituent products |
|---|---|---|---|---|---|---|
| CQ-08 | For orphan artifact A, which work items are candidate parents, what evidence supports each (shared concepts, authorship, time window, similar linked artifacts), and does the score cross the ask threshold? | FR-2, NFR-7 | Production · Traceability Management (Association Confirmation); Discovery · Knowledge Retrieval | S | Transitional | Graph + Vocabulary + Catalog (embedding similarity as mechanism) |
| CQ-15 | Which concepts is artifact A about, in which scheme, and were they matched by label, extracted, suggested, or confirmed? | FR-3, FR-8 | Production · Knowledge Classification (Concept Linking) | X, H, S | MVP | Graph (subject edges) + Vocabulary (labels, provenance of the link) |
| CQ-16 | Which artifacts are about concept K or any narrower concept of K? | FR-8 | Discovery · Knowledge Retrieval (Relationship Navigation) | X, H | MVP | Graph (subject edges) + Vocabulary (narrower-concept closure) |
| CQ-19 | Which published artifacts are similar to draft D above the overlap threshold, and what do they share (concepts, work item, owner)? | FR-5 | Governance · Duplicate Management (Overlap Detection) | S over published only | Transitional | Catalog + Graph (embedding similarity as mechanism; published-only scope from Catalog) |
| CQ-20 | Which artifacts should be recommended before creating a new one under work item W about concept K? | FR-8 (3.3 recommendation) | Discovery · Knowledge Recommendation (Reuse Suggestion) | C, X, H | Transitional | Catalog + Graph + Vocabulary |
| CQ-24 | Which published artifacts have a source that changed after their baseline (staleness), and which subscribers follow them? | FR-7, FR-8 | Currency · Change Detection; Currency · Subscription Management (Following) | C | Transitional | Catalog (baseline, staleness) + Change Events (source changed) + Graph (followers) |
| CQ-26 | Who has authored, owned or approved artifacts about concept K, weighted by recency and count? (Expertise location.) | FR-11 | Discovery · Expertise Identification (Authorship Analysis, Ownership Analysis) | C, H | Target | Graph (person edges) + Vocabulary (concept) |
| CQ-27 | Which artifacts about concept K were delivered under work item W and have a source that changed since their baseline? (All three axes in one query — see note 001.) | FR-2, FR-7, FR-8 | Production · Traceability Management; Production · Knowledge Classification (Concept Linking); Currency · Change Detection | C, X, H | Transitional | Catalog + Graph + Vocabulary + Change Events — all four |

## Open for the business to answer

The questions above are derived from the FRs. The ones only DOH can supply are the *business*
questions people will actually ask the layer — e.g. "which decisions constrain system S", "what did we
agree with vendor V", "which capabilities have no current documentation". Add them here as CQ-27+
with the asker's role; they decide which schemes get seeded first.
