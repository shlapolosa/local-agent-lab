# Phased realisation — MVP (simplest tools) → Transitional (improve, cost-managed) → Target (no expense spared)

**Driver:** cost. **Constraint (initiative doc §5.8):** the pipeline shape is final at MVP; promotion is
activation, not re-plumbing. **How both hold at once:** every phase step is an ADAPTER swap behind a PORT
the workload never sees — the store port, the graph port, the event port, the retrieval port, the
vocabulary port. This is the lab's own abstraction → adapter → DI seam applied to the fabric.

**Cost classes** (list prices Sept 2026, order of magnitude — verify before budgeting):
`0` included in licences already held · `$` consumption, negligible at MVP volume · `$$` a fixed monthly
resource under ~USD 300 · `$$$` capacity or enterprise licence, USD 1 000+/month or /year.

## Realisation per capability

| L4 (map 1.6b) | MVP — simplest tools | Transitional — improve, manage cost | Target — no expense spared |
|---|---|---|---|
| 1.1 Vocabulary Management | SharePoint term store (`0`) for subject schemes + SKOS/SHACL files in git, validated in CI (P, `0`) | VocBench 3 self-hosted for steward workflow and alignment (`$$` one container) — or stay on term store + git if steward load is low | Commercial platform with SPO app + term-store sync (PoolParty / Semaphore, `$$$`); Fabric IQ Ontology for 1.1.2 once GA |
| 1.2 Catalog Management | Cosmos DB serverless, ONE container: records, edges, embeddings (`$`) | same, registered in Purview Unified Catalog (`0`) | OneLake + Purview Unified Catalog (Fabric capacity `$$$`) |
| 2.1 Content Synthesis | Functions consumption + model via AI Hub Gateway (`$` per token); templates as SP list (`0`) | same, per-type templates, batched re-drafts | same; Foundry agents; larger models |
| 2.2 Knowledge Classification | Purview labels + SP metadata columns (`0`); type suggested by the same model call (`$`) | SharePoint Premium classifier pilot (`$` 0.10/doc) only if it beats the model on measured accuracy | SP Premium at scale + auto-tagging from the taxonomy platform (`$$$`) |
| 2.3 Version Management | SharePoint versioning (`0`) | same | same |
| 2.4 Traceability Management | edges as Cosmos documents; rung 1 = ADO links; rung 2 = reference extraction in Functions; rung 4 = Teams card (P, `$`) | + rung 3 signals from Work IQ (`$` consumption, capped) | Fabric Graph on OneLake (`$$$`) |
| 3.1 Ownership & Stewardship | owner map = SP list; steward queue = SP list + Teams (`0`) | Power Apps steward console (`$` per-app plan) | same |
| 3.2 Knowledge Review | Teams Approvals + Power Automate standard connectors (`0` with M365) | + timer escalation, digest batching | pro-code Teams bot when PA limits bite (Azure Bot Service, ~`0`) |
| 3.3 Duplicate Management | gateway routes "no"; embeddings still stored (`$`) | Cosmos DB vector search (`$`) + steward adjudication | AI Search hybrid + vector (`$$`) or Foundry IQ |
| 4.1 Knowledge Retrieval | M365 Copilot + Microsoft Search / Graph search API (`0`); catalog joins in Functions | Work IQ MCP door for agents (`$` consumption, capped) + thin fabric MCP facade | + Foundry IQ knowledge bases; Fabric IQ ontology MCP |
| 4.2 Knowledge Recommendation | — | Copilot Studio discovery agent (`$$` message packs) | + Work IQ proactive context |
| 4.3 Expertise Identification | — | — | Work IQ people signals (`$`) + catalog query |
| 5.1 Change Detection | Graph change notifications + ADO service hooks → Functions; Storage Queue (`$`, ~0) | Service Bus topics when fan-out is needed (`$$` ~10/mo) | Fabric Eventstreams + Activator (`$$$` capacity) |
| 5.2 Change Impact Analysis | pass-through (per doc) | adjacency traversal in Functions over Cosmos edges (P, `$`) | Fabric Graph traversal |
| 5.3 Subscription Management | — | subscriptions in Cosmos + Power Automate digest flow (`0`/`$`) | Activator → Teams |
| 5.4 Republication | Functions → ADO wiki via REST (`0`); index = Cosmos vectors (`$`) | + AI Search index refresh (`$$`) | + Foundry IQ |
| 5.5 Catalog Reconciliation | — | Functions timer + Graph delta queries (`$`) | Fabric pipelines |
| 5.6 Remediation Management | — | button-first, late Transitional: Functions + Graph/ADO APIs in draft mode (`$`) | Foundry / Agent 365 agents + writeback |
| Consumed: Access, Audit, Retention | Entra + Purview (`0`) | same | same |

## What each phase costs to keep on (fixed, excluding people and model tokens)

| Phase | Fixed monthly | What is deliberately absent |
|---|---|---|
| POC (lab) | negligible: Railway Hobby substrate, Neon free tier, flat-rate inference | everything Azure-specific; nothing licensed — the lab already holds every port with an adapter behind it (FRS §10.1) |
| MVP | tens of USD: Cosmos serverless, Functions consumption, storage, queue | no AI Search, no Service Bus, no Copilot Studio, no Fabric, no vocabulary licence, no Work IQ |
| Transitional | low hundreds: + AI Search Basic (~75) or stay on Cosmos vectors, + VocBench container (~30), + Copilot Studio packs (~200 / 25k msgs), + Work IQ consumption under a cap | no Fabric capacity, no commercial taxonomy platform |
| Target | F-SKU capacity (F2 ≈ 260/mo minimum; realistic F4–F8 500–1 000+, feature gating to verify) + taxonomy platform licence (`$$$`/yr) + AI Search Standard + Foundry IQ | — |

## The ports that make this activation, not re-plumbing

| Port | POC adapter (lab) | MVP adapter | Transitional adapter | Target adapter |
|---|---|---|---|---|
| Store (catalog, embeddings) | Postgres (Neon) + pgvector | Cosmos serverless | Cosmos + Purview registration | OneLake + Purview |
| Graph (edges, traversal) | rdflib named graphs, SPARQL (`semantic-mcp`) | Cosmos adjacency documents | same, traversal in Functions | Fabric Graph |
| Event (change → pipeline) | Redis Streams | Storage Queue | Service Bus topics | Eventstreams + Activator |
| Content by reference | `storage-mcp`, `collab_mcp` | Graph / ADO adapters | same | same |
| Retrieval (people and agents) | gateway-registered MCP tools | Graph search API + Copilot | Work IQ MCP | + Foundry IQ, Fabric IQ ontology MCP |
| Vocabulary | `semantic-mcp` SKOS + git | term store + SKOS in git | VocBench 3 | PoolParty / Semaphore + Fabric IQ Ontology |
| Review surface | review app + Teams card channel | Teams Approvals + PA | + Power Apps console | pro-code Teams bot |
| Model gateway | LiteLLM | AI Hub Gateway | same | same |

## Work IQ — from the beginning?

**No — from Transitional, with one exception.** At MVP the consumers are people through Copilot and
Microsoft Search, both included in licences held; Work IQ adds nothing to the ADR thin slice that those
do not, and its UAE-geo residency and billing controls are still unverified. It enters at Transitional
for two things only the fabric cannot get elsewhere cheaply: the permission-aware MCP door for agents
(NFR-8) and the rung-3 association signals. Consumption billing suits that — cost follows use and a cap
works. **Exception:** if the MVP must prove the agent door (coding agents grounding on ADRs is named in
§1), take Work IQ at MVP under a budget; it is still the cheapest agent door because it needs no capacity.

## Fabric IQ — Target only

Graph and Operations Agents are GA, Ontology is preview, and the cost is reserved capacity. Nothing at MVP
or Transitional depends on it; the graph port's Cosmos adapter carries impact analysis until volume or
query complexity justifies capacity. The quarterly estate review (principle 10) re-asks this each time.
