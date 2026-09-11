# Note 005 — The provenance ladder: how an assertion earns its place in the graph

**Status:** agreed 2026-09-11 · **Generalises** the initiative doc's association ladder (§5.3, delivery edges
only) to EVERY assertion in the products · **Applies to:** the graph's named-graph partitions, the port
read-policies, the curator gates, the Gate B/NFR-6 metrics, the conceptual views.

## The rungs (ordered by trust, lettered by the named graph they live in)

| Rung | Letter | How an assertion enters | Trusted for impact | Examples |
|---|---|---|---|---|
| Observed | O | a source event or signal; lands in Change Events, never in the graph | no | artifact X changed by A at T |
| Suggested | S | probabilistic, carries a confidence and a method | **never** | embedding similarity · AI-proposed type · cluster-derived candidate concept · Work IQ signal |
| Extracted | X | deterministic parse of an explicit reference; has a known error class | yes | work-item id in text · embedded diagram · label match to a concept's pref/alt label |
| Constructed | C | deterministic by construction: a lookup or a link at creation | yes | IRI minted · ADO link at creation · owner from the owner map · inherited label |
| Confirmed | H | a person accepted a suggestion or an extraction | yes | one-tap card · adjudication · owner approval · steward accepts a concept |
| Derived | D | inferred from trusted assertions by a stated rule; recomputed, never captured | yes, at the weakest input's grade | narrower-concept closure · impact chains · expertise scores |

"Deterministic" splits into **Constructed** and **Extracted** (extraction has an error class);
"non-deterministic" splits into **Suggested** and **Confirmed**. **Derived** is the fifth kind principle 7
does not name: *captured, never guessed — or derived from captured assertions by a stated rule.*

## Entry rules by assertion type

| Assertion | May enter at | Promoted by |
|---|---|---|
| Identity (IRI), owner, sensitivity | **C only** (NFR-3: never suggested) | — |
| Delivery edge | C (link at creation) · X (id in text) · S (signals) | card → H |
| Reference edge | X (links, embeds) · S (similarity) | approval / card → H |
| Document type | S (model) | owner approval → H |
| Concept link | X (label match) · S (nearest neighbour, model) | approval or steward → H |
| Concept (vocabulary) | C (seeded) · S (candidate) | steward accept → H; deprecate = retract |
| Back-book artifact edges | **X or H only** (NFR-7: never C — no link at creation existed) | card / steward → H |
| Correction proposal | S (remediation agent) | owner disposal → H, filed in the source's own review |

## Mechanics
- **Promotion is a transaction**; each rung crossing IS a curator-side gate on the operating process, and
  there is no crossing without one. **Retraction is supersession** (PROV-O invalidation), never deletion —
  CQ-22's audit chain stays whole. **Derived is recomputed** after any promotion or retraction beneath it.
- **Each output port declares the rungs it reads**: impact = C · X · H (+ D from them); discovery = all,
  grade shown; curator queues = S above threshold; the facade returns the grade with every answer.
- **The gate metrics are the distribution over rungs**: Gate B auto-association ratio = share of edges
  entering at C or X vs needing H; NFR-6 precision is measured per rung.
- **Rung = named graph.** A SPARQL query over a chosen set of graphs is, literally, a trust policy. The
  lab's per-provenance named-graph store already implements this.

Related: [[2026-09-10-knowledge-graph-axes]] (001) · [[2026-09-11-data-products]] (004).
