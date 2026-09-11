# Vocabulary Management (L4 1.1) — decomposition and bake-off

Companion to `vocabulary-management-v1.0a-decomposition.png` and `vocabulary-management-v1.0b-bakeoff.png`
(generator `scripts/fabric_vocabulary_management.py`).

## Is there a standard breakdown?

Yes, for most of it. **ISO 25964** is the international standard for thesauri and their interoperability:
Part 1 (2011) covers concepts and terms, equivalence, hierarchical and associative relationships, facet
analysis, multilingual equivalence, presentation, managing construction and maintenance, guidelines for
management software, and a data model (clause 15) with exchange formats and protocols; Part 2 (2013)
covers mapping between vocabularies — mapping types (exact, inexact, partial equivalence; hierarchical;
associative), structural models (direct-linked, hub) and interoperability with classification schemes,
taxonomies, subject-heading schemes, name authorities, ontologies, terminologies and synonym rings.
**ANSI/NISO Z39.19** overlaps Part 1 for monolingual vocabularies and is stronger on maintenance.
**SKOS** is the W3C data model both serialise to. **Hedden (2019)** is the practitioner checklist for
selecting management software.

What ISO 25964 does **not** cover is ontology management — classes, properties, constraints, rules — which
follows W3C RDFS/OWL/SHACL and the EKG/MM "Ontologies" capability. So the decomposition is ISO 25964 for
three of four L5s and functional decomposition for the fourth.

## Decomposition (L4 → L5 → L6)

| L5 | L6 | Source |
|---|---|---|
| **1.1.1 Concept Scheme Management** — define what things mean and how they relate | 1.1.1.1 Concept & Label Management | ISO 25964-1 concepts & terms · SKOS prefLabel/altLabel |
| | 1.1.1.2 Equivalence Management | ISO 25964-1 equivalence, compound equivalence |
| | 1.1.1.3 Hierarchy Management | ISO 25964-1 generic, whole-part, instance; polyhierarchy |
| | 1.1.1.4 Associative Relationship Management | ISO 25964-1 associative; custom relations |
| | 1.1.1.5 Facet & Array Management | ISO 25964-1 facet analysis, arrays, node labels |
| | 1.1.1.6 Multilingual Equivalence Management | ISO 25964-1 cross-language equivalence degrees |
| **1.1.2 Ontology Management** — define the classes, properties and rules the graph obeys | 1.1.2.1 Class & Property Definition | RDFS / OWL · EKG/MM Ontologies |
| | 1.1.2.2 Constraint & Shape Definition | W3C SHACL |
| | 1.1.2.3 Upper Vocabulary Reuse | DCAT · PROV-O · DCTerms · schema.org |
| | 1.1.2.4 Inference Rule Definition | OWL · SPARQL CONSTRUCT · SHACL rules |
| **1.1.3 Vocabulary Alignment** — relate one vocabulary to another without merging | 1.1.3.1 Mapping Management | ISO 25964-2 mapping types |
| | 1.1.3.2 Cross-KOS Interoperability | ISO 25964-2 other vocabulary types |
| | 1.1.3.3 Mapping Structure Management | ISO 25964-2 direct-linked vs hub |
| | 1.1.3.4 Mapping Verification | ISO 25964-2 selective mapping · human confirmation (fabric principle 7) |
| **1.1.4 Concept Lifecycle Management** — grow and govern the vocabulary over time | 1.1.4.1 Candidate Term Intake | Z39.19 candidate terms · corpus term extraction (Hedden) — the fabric's proposed-concept queue |
| | 1.1.4.2 Editorial Workflow | ISO 25964-1 construction & maintenance · roles, permissions — the steward |
| | 1.1.4.3 Versioning & Deprecation | Z39.19 maintenance · status, replaced-by, history |
| | 1.1.4.4 Quality Assurance | ISO / Z39.19 logic: unique preferred labels, reciprocals, no hierarchy cycles |
| | 1.1.4.5 Publication & Access | ISO 25964-1 data model, exchange formats, protocols · APIs, term-store sync |

Competency questions CQ-15 to CQ-18 map onto 1.1.1, 1.1.3 and 1.1.4; 1.1.2 is exercised by every SHACL
fitness function (CQ-03, CQ-13, CQ-23).

## Bake-off criteria (Hedden 2019 + fabric constraints)

Standards supported (ISO 25964 / Z39.19 logic enforcement, SKOS, OWL, SHACL) · reciprocal relationship
maintenance on rename/merge/delete · candidate vs approved terms · multilingual · user-defined relations and
attributes · automated mapping between vocabularies · candidate term extraction from a corpus ·
auto-classification module · URIs / linked data · connectors (SharePoint term store, search, Purview) ·
import/export formats · quality-control flags and reports · multi-user permissions · **in-tenant /
in-region deployment** (NFR-1) · **SharePoint / M365 integration** (the projection target) · pricing model.

## Leading providers (September 2026)

| Class | Products | Verdict for the bake-off |
|---|---|---|
| Estate as shipped | SharePoint term store (+ SharePoint Premium taxonomy tagging), Microsoft Purview glossary, Azure AI Search synonym maps | Cover 1.1.1 partially, nothing of 1.1.2–1.1.3, thin 1.1.4. The term store is a taxonomy, not a thesaurus. It stays the SharePoint-side **projection target** of whatever wins. |
| Specialist SKOS/OWL platforms | **PoolParty** (Semantic Web Company), **Progress Semaphore**, **TopBraid EDG** (TopQuadrant), **Synaptica Graphite**, **Mondeca ITM** | Full on 1.1.1 and 1.1.4. Differ on 1.1.2 (EDG strongest — native SHACL and rules), 1.1.3 (EDG, PoolParty) and M365 integration (PoolParty and Semaphore ship SharePoint Online apps with term-store sync; Semaphore can set Purview labels from classification; Synaptica and Mondeca have connectors; EDG has none). |
| Thesaurus-model tools | Data Harmony (Access Innovations), MultiTes | Z39.19-native with strong QA and term extraction; no ontology, no mapping. Fine for 1.1.1 alone. |
| Open source | **VocBench 3** (EU Publications Office; SKOS/OWL, workflow, alignment, integrity validation), **Protégé** (ontology only), TemaTres | VocBench matches the specialists on the standard at zero licence cost; no SharePoint connector, no term extraction. The baseline a paid product must beat. |
| POC substitute | the lab's `semantic-mcp` (rdflib SKOS store, SPARQL, cross-scheme exactMatch) | Proves the pattern locally; not a product. Its gaps (associative relations, workflow, versioning, QA) are the pro-code that would otherwise be written. |

**Shortlist for the bake-off:** PoolParty, Semaphore, TopBraid EDG, with VocBench 3 as the open-source
control and the term store as the mandatory projection target. Decide on 1.1.2 depth (does the fabric's
ontology live in the same tool as the subject schemes, or in code with SHACL in CI?), on term-store sync
fidelity (labels and hierarchy survive; associative relations and mappings do not), and on residency.

Ratings in the bake-off image are from product documentation and Hedden's 2019 survey; connector claims for
Synaptica, Mondeca and Data Harmony are from that survey and should be re-verified with the vendors.
