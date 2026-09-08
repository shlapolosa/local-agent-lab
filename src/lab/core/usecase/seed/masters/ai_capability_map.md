# AI capability map

**Artifact:** ai_capability_map
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| domain | capability | primary | rationale | alternative | sources |
|---|---|---|---|---|---|
| Cross-cutting | Independent outcome monitoring | Azure Monitor scheduled query rules over the system of record | Enforces G19; reads the authoritative source, never an agent output | Incumbent platform reporting / SLA engine, declared as a boundary interface with a named owner | S23 |
| Cross-cutting | Confidence-threshold escalation | Agent Framework middleware branch to a human queue | Enforces G18 second clause; thresholds live in the orchestrator, not the inference service | Power Automate approval branch; Copilot Studio human-in-the-loop step | S6; S8; S2 |
| Cross-cutting | Influence-sized evaluation | Foundry evaluation harness per influencing step with a declared recall gate | Enforces G18 first clause; sized by influence, not by determinism tier | Any harness supporting per-step recall targets and regression gating | S3 |
| Cross-cutting | Ontology / alias-set stewardship | Fabric IQ ontology + Purview term governance with a named steward | Enforces G15; closing criteria 6 and 7 moves steps D1 → D0 | Stardog or equivalent with an equivalent stewardship process | S10; S13 |
| Cross-cutting | Gate decision and approval evidence store | Dataverse approval log, or Azure Monitor logs at audit retention | Evidence for G09, G19 and conformance review | Incumbent platform audit log, declared as a boundary interface | S8; S23 |
| Business | Capability map / value streams | Power BI semantic models, Dataverse | Already in M365 estate; integrates with Fabric IQ | LeanIX, Ardoq | S10; S8 |
| Business | Business process automation | Power Automate | Low-code; deep integration with Dataverse + Copilot Studio | n8n, Camunda | S8 |
| Business | Business skills (process knowledge) | Dataverse business skills | Discoverable by any MCP-compatible agent | Custom MCP server | S8; S12 |
| Semantic | Ontology (entities, rules) | Fabric IQ Ontology item | Native graph engine; binds to OneLake; multi-hop reasoning | Stardog, GraphDB, Neo4j | S10 |
| Semantic | Business glossary | Microsoft Purview Unified Catalog | Glossary terms carry policy (DLP, classification) | Collibra, Alation | S13 |
| Semantic | Master / reference data | Dataverse | Native to Power Platform; agent-addressable via MCP | Profisee, Reltio | S8 |
| Semantic | Temporal / event-time modelling | Fabric IQ ontology temporal properties + Azure Data Explorer (time-series) | Model time & event ordering so rules express temporal correlation; ADX/KQL for windowed analysis | GraphDB time, custom | S10 |
| Semantic | Geospatial / location modelling | Fabric IQ ontology spatial properties + Azure Maps | Model location & proximity so rules express geospatial correlation (area-of-interest, co-location) | PostGIS, GeoSPARQL | S10 |
| Semantic | Tempo / rate-of-change | Semantic rules over time-series (Fabric IQ + ADX) | Derive escalation tempo (rate-of-change) as a reasoned property, not raw feed rows | Custom stream analytics | S10 |
| Knowledge | Agentic retrieval | Foundry IQ | Federated subquery decomposition; semantic ranker normalises scores | LlamaIndex, custom RAG | S9 |
| Knowledge | Enterprise context layer | Work IQ | Permission-aware; understands collaboration patterns | Glean, Coveo | S7 |
| Knowledge | Vector / hybrid search | Azure AI Search | Underlies Foundry IQ; also standalone | Pinecone, Weaviate, Qdrant | S9 |
| Knowledge | Document corpora (static) | SharePoint, OneLake, Azure Blob | Static / data-at-rest; batch-indexed (scheduled re-index = dynamic). Foundry IQ indexed sources | S3 + custom indexers | S9 |
| Knowledge | Real-time knowledge source (pull) | Foundry IQ federated / remote + MCP + web | Real-time-pull: external APIs & DBs queried live at request time; MCP (private preview) + Bing web; merged & reranked with indexed content | Custom API / MCP connector | S9; S12 |
| Knowledge | External tool / data | MCP servers (Foundry IQ private preview) | Standard protocol; Dataverse, GitHub expose MCP | Custom REST adapters | S12; S8 |
| Cognitive | Declarative agent (M365 surface) | M365 Copilot declarative agent | Copilot orchestrator + foundation models; no separate hosting | — | S1 |
| Cognitive | Custom-engine agent runtime | Foundry Agent Service (prompt / workflow / hosted) | Hosted, scalable; Responses API; private networking; MCP auth | LangGraph + own infra | S3 |
| Cognitive | Agent SDK / framework | Microsoft Agent Framework 1.0 (.NET, Python) | Successor of Semantic Kernel + AutoGen; Magentic-One | LangGraph, CrewAI | S6 |
| Cognitive | Multi-channel conversational SDK | Microsoft 365 Agents SDK | Channel-normalised Activity model; AI-agnostic | Bot Framework v4 | S2 |
| Cognitive | Agent identity | Microsoft Entra Agent ID + blueprints (governed via Microsoft Agent 365) | Lifecycle, Conditional Access, governance for agent principals; Agent 365 issues + governs the identities end-to-end | Workload identity federation | S5; S30 |
| Cognitive | Agent control plane (observe / govern / secure) | Microsoft Agent 365 | GA May 2026 — the agent-equivalent of M365 for users: inventory, identity, policy, audit and runtime for every agent (Microsoft, partner, custom, cross-cloud); enforcement plane for G01/G03/G04/G07/G10/G14 | Custom registry + bespoke policy fabric | S30; S31 |
| Cognitive | Agent supply chain / manifests | Source-controlled agent manifest + prompt/template library + Azure DevOps / GitHub Actions deploy pipeline | G01 enforcement — manifests signed, version-controlled, reviewable; promotes immutability at runtime | Custom GitOps | S6; S2 |
| Cognitive | Evaluation | Foundry Evaluations + project eval suite | Required by G10; harness gates deploy | Promptfoo, DeepEval | S3; S11 |
| Cognitive | Remote / non-Microsoft models | Anthropic, OpenAI direct, Google (mediated by APIM AI Gateway) | Pluggable model providers; policy + token metering enforced at the gateway | — | S25; S27 |
| Cognitive | Local / fine-tuned models | Foundry fine-tunes + PTU dedicated capacity; AKS-hosted SLM (opt) | Performance / cost / residency control when remote models won't fit constraints | HuggingFace TGI | S3 |
| Application | Action invocation surface | Power Automate | Approval, schedule, RPA, deep M365 connectors | Logic Apps | S8 |
| Application | Business app fabric | Power Apps | Hosts Dataverse-backed UIs that agents drive via skills | — | S8 |
| Application | RPA | Power Automate Desktop | UI automation for legacy systems an agent must drive but cannot API into | UiPath, Blue Prism | S8 |
| Data | Operational data store | Dataverse | Row-level security; first-class skills surface | SQL Database | S8 |
| Data | Analytical lakehouse | OneLake | Single copy across Fabric workloads | Delta Lake on S3 | S10 |
| Data | Catalog & lineage | Microsoft Purview | DLP, classification, glossary, lineage in one plane | DataHub, OpenMetadata | S13 |
| Data | Agent state / durable memory | Cosmos DB | Multi-region; low-latency reads for A4 / A6 long-running agents | DynamoDB | S3 |
| Data | Session cache / counters | Azure Cache for Redis | Per-turn state, rate-limit + budget counters used by G08 middleware | Memcached | S3 |
| Technology | Edge / DDoS / WAF | Azure Front Door + Application Gateway + WAF + DDoS Protection | Mandatory for any externally-exposed agent or portal | Cloudflare, Akamai | S17 |
| Technology | API Management — AI Gateway | Azure API Management with GenAI policies | Token-limit, semantic-cache, model-load-balance, prompt-shield / content-safety; runtime enforcement for G01/G02/G06/G08 | Kong AI Gateway, Apigee | S25; S27 |
| Technology | Eventing / messaging | Event Grid, Event Hubs, Service Bus | Required for A6 event-triggered agents and any async path | Kafka | S3 |
| Technology | Networking isolation | Hub-and-spoke vNet, Private Endpoints, Private DNS, Azure Firewall | Required by CAF landing zone for regulated workloads | — | S19; S22 |
| Technology | SecOps | Microsoft Defender for Cloud + Microsoft Sentinel | SIEM / SOAR correlation of agent activity with identity events | Splunk | — |
| Technology | Multi-channel adapter | Azure Bot Service + M365 Agents SDK | Channel normalisation for Teams / web / custom | — | S2; S14 |
| Technology | Compute for hosted agents | Foundry hosted-agent runtime | Sandboxed; managed scaling; OAuth passthrough for MCP | AKS + own controllers | S3 |
| Technology | Sandboxed agent runtime VM | Windows 365 for Agents | Managed, isolated cloud-PC for agents that need a desktop / browser / legacy-UI surface; provisioned + governed by Agent 365 | AKS-hosted sandbox, Browserbase | S32; S30 |
| Technology | Identity & access | Microsoft Entra ID | Single plane for users, workloads and agents | Okta + workload federation | S5 |
| Technology | Observability | Application Insights + Foundry traces | Built-in agent traces; correlates with Entra sign-in | OpenTelemetry stack | S3; S5 |
| Technology | Container/orchestration host | Azure Container Apps; AKS (per AAC Baseline Agentic AI Systems) | Hosts non-Foundry frameworks (LangChain, etc.) | Self-managed Kubernetes | S23 |
| Cross-cutting | Non-functional invariants (AI) | Azure Well-Architected Framework — AI workloads | Mandatory for production; structures M3 evidence | — | S16; S17 |
| Cross-cutting | Landing zone / perimeter | CAF AI Ready + Azure landing zones | No separate AI LZ; deploy as application landing zones | — | S18; S19 |
| Cross-cutting | Runtime governance hub | Foundry Citadel — Governance Hub (AI Gateway) | Enforcement plane for G01/G02/G06/G08 | — | S24; S25; S27 |
| Cross-cutting | Spoke 'Agents Environment' | Foundry Citadel — spoke via Azure/AI-Landing-Zones | One per BU / use case; built-in identity, observability, eval scaffold | — | S24; S26 |
| Cross-cutting | Foundry control plane | Microsoft Foundry control plane | Governs Foundry projects, models, agents | — | S28 |
| Cross-cutting | Agent discovery / shadow-AI inventory | Microsoft Agent 365 (uses Defender + Intune; registry sync to AWS Bedrock & Google Cloud — public preview) | Discovers local + cloud agents across the estate, including non-Microsoft platforms; turns shadow AI into a governed asset class; satisfies G14 | Bespoke CMDB + scanners | S30; S31 |
| Cross-cutting | Agent governance toolkit (open-source) | Microsoft Agent Governance Toolkit | Agent-level governance primitives (policy, scoring, evaluation hooks) usable alongside Agent 365 in code | Custom hooks + OPA | S29 |
| Cross-cutting | Baseline — basic chat | AAC: Basic Foundry Chat | POC only | — | S20 |
| Cross-cutting | Baseline — production chat | AAC: Baseline Foundry Chat | Production baseline for RA-1 | — | S21 |
| Cross-cutting | Baseline — chat in landing zone | AAC: Baseline Foundry Chat in Landing Zone | Regulatory / network isolation | — | S22 |
| Cross-cutting | Baseline — agentic on containers | AAC: Baseline Agentic AI Systems | RA-3/4/5 hosted-container path | — | S23 |
| Boundary | Alerting / notification | Notification service · SMS gateway · push (traditional architecture) | Boundary interface — owned by traditional architecture; referenced by M5, not an M4 AI component | Twilio · FCM / APNs | — |
| Boundary | Real-time-push / streaming ingestion | Event / stream pipeline (traditional architecture) | Boundary interface — continuous event-feed ingestion (data-in-motion); the AI grounds on the resulting state via a real-time-pull source | Kafka · Event Hubs (as infra) | — |
| Boundary | Comms resilience / fallback | Network · satellite messaging (traditional architecture) | Boundary interface — comms-denied operation; outside CAFÉ's AI scope | Iridium · Starlink | — |
