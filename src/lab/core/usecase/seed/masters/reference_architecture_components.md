# Reference architecture model — components

**Artifact:** reference_architecture
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py
**Section:** components

| id | zone | name | detail | archetypes | code | building_block | l3 | uae_north_status | constraint | archimate_type | deployed_on |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cmp-42c5354b00 | ex | Staff channels | Teams · web · mobile | A2; A3; A6 | EX-01 | EX1 | TEC.06; COG.05 | green — available in UAE North |  | Application component |  |
| cmp-033b5a487e | ex | Business apps & embedded agents | Power Apps · M365 apps | A2; A3; A5 | EX-02 | EX1 | APP.02; APP.09 | green — available in UAE North |  | Application component |  |
| cmp-a9c03320dd | ex | Microsoft 365 Copilot | Copilot Chat · Researcher · incl. Claude | A1; A7 | EX-03 | EX2 | RCV.01; COG.01 | amber — partial / preview / not region-pinned | Claude via Microsoft path — non-resident | Application component |  |
| cmp-85ac79369e | ex | Copilot Cowork | plan-then-execute on M365 work |  | EX-04 | EX2 | RCV.01 | amber — partial / preview / not region-pinned | residency unverified | Application component |  |
| cmp-8838b63d4c | ex | Desktop & coding agents | Claude Desktop (incl. Cowork) · Claude Code · GitHub Copilot |  | EX-05 | EX3 | RCV.02; COG.17 | third-party — admitted via gateway | gateway mode only · Entra SSO · Intune config | Application component | Node: managed developer / staff device |
| cmp-b79503cff6 | ex | SaaS-embedded vendor agents | Dynamics 365 · ServiceNow · others |  | EX-06 | EX4 | RCV.03 | amber — partial / preview / not region-pinned | vendor-controlled | Application component |  |
| cmp-fade0af952 | ex | Personal desktop agent | Microsoft Scout |  | EX-07 | EX3 | RCV.02 | red — not available in UAE North / out-of-region | blocked pending assurance | Application component | Node: user device |
| cmp-f829997915 | ex | Patient & citizen channels | portal · app · voice | A2; A3 | EX-08 | EX1 | TEC.06 | green — available in UAE North |  | Application component |  |
| cmp-45b5f71698 | ex | Sovereign assistant | Core42 Compass Chat |  | EX-09 | EX2 | RCV.01 | sovereign — Core42 in-country |  | Application component |  |
| cmp-0627c94e41 | gw | Edge protection | Front Door · WAF · DDoS | A2; A3; A5 | GW-01 | GW1 | TEC.01 | green — available in UAE North |  | Technology service |  |
| cmp-967db4e8ad | gw | AI traffic gateway | APIM AI Gateway · Entra JWT · token limits · metering | A1; A2; A3; A4; A5; A6; A7; A8 | GW-02 | GW2 | TEC.02; DAT.05; TEC.21 | amber — partial / preview / not region-pinned | UAE North: Standard v2 | Application component | Node: Azure UAE North |
| cmp-99247be24b | gw | Sensitive-data decision | Azure Language PII/PHI — block · redact · reroute |  | GW-03 | GW3 | KNW.11 | green — available in UAE North | gate before any out-of-region call | Application component | Node: Azure UAE North |
| cmp-5cf110edd7 | gw | Channel & telephony adapters | Bot Service · ACS Call Automation | A1; A2; A3; A6; A7; A8 | GW-04 | GW4 | TEC.06; TEC.12 | green — available in UAE North |  | Application component |  |
| cmp-9c2fb48665 | gw | Eventing | Event Grid · Service Bus · Event Hubs | A2; A3; A6 | GW-05 | GW4 | TEC.03 | green — available in UAE North |  | System software |  |
| cmp-6c71a39bbd | ag | Low-code agents | Copilot Studio | A2; A3 | AG-01 | AG1 | COG.24; COG.01 | green — available in UAE North |  | Application component |  |
| cmp-5ebda000ea | ag | Hosted agent runtime | Foundry Agent Service (prompt · hosted) | A2; A3; A4; A5; A6; A8 | AG-02 | AG1 | COG.02; TEC.07 | green — available in UAE North | hosted: 2 vCPU / 4 GiB, no GPU | Application component |  |
| cmp-aeadf1eec9 | ag | Pro-code agents | Agent Framework on Container Apps / AKS | A2; A3; A4; A5; A6; A8 | AG-03 | AG1 | COG.03; TEC.11 | green — available in UAE North |  | Application component |  |
| cmp-4c70d67472 | ag | Deterministic orchestration | Agent Framework workflows · Logic Apps · Power Automate |  | AG-04 | AG2 | COG.04; BUS.02 | green — available in UAE North |  | Application component |  |
| cmp-34dd73a433 | ag | Agent registry & routing | Agent 365 registry · intent cards · domain taxonomy |  | AG-05 | AG3 | COG.08; BUS.05 | amber — partial / preview / not region-pinned | Agent 365 integration preview | Application component |  |
| cmp-20e41d4b2e | ag | Agent-to-agent delegation | Agent Framework A2A |  | AG-06 | AG3 | COG.18 | green — available in UAE North |  | Application component |  |
| cmp-03cb07d13f | ag | Runtime interception | Agent Framework middleware (onTaskStart · onToolCall) | A2; A3; A4; A6 | AG-07 | AG4 | COG.10; XCT.07 | green — available in UAE North |  | Application component |  |
| cmp-c83449d4aa | ag | Rule brokering | Dataverse rules + MCP · business rule editor |  | AG-08 | AG4 | COG.09; BUS.07 | green — available in UAE North |  | Application component |  |
| cmp-b9693ce6b1 | ag | Content safety & task adherence | Foundry Guardrails · Content Safety |  | AG-09 | AG5 | COG.20; COG.30 | amber — partial / preview / not region-pinned | no groundedness in UAE North | Application component |  |
| cmp-ab16720e0c | ag | Output validation | structured outputs · APIM schema policy |  | AG-10 | AG5 | COG.29 | green — available in UAE North |  | Application component |  |
| cmp-aa1d470734 | ag | Escalation & human approval | Power Automate approvals in Teams | A2; A3; A6 | AG-11 | AG6 | XCT.19; APP.07 | green — available in UAE North |  | Application component |  |
| cmp-c7b57a4b55 | ag | Voice & language | Voice Live · Speech · Translator |  | AG-12 | AG7 | COG.15; COG.16; COG.21 | amber — partial / preview / not region-pinned | many voice features red | Application component |  |
| cmp-2d25e10bff | ag | Media generation & provenance | image models · Content Credentials |  | AG-13 | AG7 | COG.22; XCT.12 | amber — partial / preview / not region-pinned | not region-pinned | Application component |  |
| cmp-4a273d4fb4 | ag | Agent state & memory | Foundry memory · Cosmos DB · Redis | A4; A6 | AG-14 | AG8 | DAT.06; DAT.04 | amber — partial / preview / not region-pinned | memory preview | System software |  |
| cmp-e0c9ab8f82 | kn | Grounding source registry | Purview Unified Catalog data products |  | KN-01 | KS1 | KNW.13; DAT.03 | green — available in UAE North |  | Application component |  |
| cmp-356d2c0c79 | kn | Agentic retrieval | Foundry IQ | A1; A2; A3; A5; A6; A8 | KN-02 | KS3 | KNW.01 | amber — partial / preview / not region-pinned | mixed GA / preview | Application component |  |
| cmp-e2eb6b87f6 | kn | Permission-aware search | Azure AI Search | A1; A2; A3; A5; A6; A8 | KN-03 | KS1 | KNW.03; KNW.09 | green — available in UAE North |  | System software |  |
| cmp-32c1a7192d | kn | Ingestion & extraction | indexers · Content Understanding | A1; A2; A3; A4; A5; A6; A7; A8 | KN-04 | KS2 | KNW.12; KNW.08; KNW.04 | green — available in UAE North |  | Application component |  |
| cmp-32f3ba0461 | kn | Work context | Work IQ | A1; A2; A5 | KN-05 | KS4 | KNW.02 | amber — partial / preview / not region-pinned | preview | Application component |  |
| cmp-b5556027f1 | kn | Structured-data Q&A | Fabric data agent |  | KN-06 | KS3 | KNW.07 | amber — partial / preview / not region-pinned | preview connectors | Application component |  |
| cmp-478c3d8b94 | kn | Ontology & reasoning | Fabric IQ — temporal · spatial · rate | A5 | KN-07 | KS5 | SEM.01; SEM.04; SEM.05; SEM.06; KNW.10; XCT.21 | amber — partial / preview / not region-pinned | preview | Application component |  |
| cmp-a14ab8a7ec | kn | Glossary & metrics | Purview glossary · Power BI semantic models | A1; A2; A5 | KN-08 | KS5 | SEM.02; SEM.07 | green — available in UAE North |  | Application component |  |
| cmp-24df20516f | kn | Master data & entity resolution | Dataverse · Customer Insights |  | KN-09 | KS5 | SEM.03; SEM.08 | green — available in UAE North |  | Application component |  |
| cmp-2d9f6e2d22 | kn | Clinical standards | AHDS FHIR · Text Analytics for Health |  | KN-10 | KS5 | SEM.09; SEM.10 | green — available in UAE North |  | Application component |  |
| cmp-81d9f22a6e | kn | Live & web knowledge | live APIs via MCP · Grounding with Bing | A2; A3; A5; A6 | KN-11 | KS4 | KNW.05; KNW.14 | amber — partial / preview / not region-pinned | web queries leave tenant | Application component |  |
| cmp-509a96ba37 | tl | Tool registry | API Center · Foundry Toolbox | A2; A3; A4; A5; A6; A8 | TL-01 | TS1 | TEC.16 | green — available in UAE North |  | Application component |  |
| cmp-9b2ff06ba9 | tl | Tool servers (MCP default) | Foundry / custom MCP behind APIM | A2; A3; A4; A5; A6 | TL-02 | TS2 | KNW.06; BND.01 | green — available in UAE North |  | Application component |  |
| cmp-97a1005c0e | tl | Business skills & actions | Dataverse skills · Power Automate | A2; A3 | TL-03 | TS2 | BUS.03; BND.02; APP.01 | green — available in UAE North |  | Application component |  |
| cmp-acbbda4cda | tl | Custom tools & compensation | Functions · Logic Apps · Durable sagas |  | TL-04 | TS2 | APP.08; APP.11 | green — available in UAE North |  | Application component |  |
| cmp-a5a82d6e99 | tl | Document assembly | Word templates · M365 document processing |  | TL-05 | TS2 | APP.06 | green — available in UAE North |  | Application component |  |
| cmp-8fe3ba0074 | tl | UI automation | Power Automate Desktop · computer use · browser |  | TL-06 | TS3 | APP.03; APP.04; APP.05 | amber — partial / preview / not region-pinned | Foundry computer use not in UAE North | Application component |  |
| cmp-adcfb4323e | tl | Isolated execution | Container Apps sessions · Windows 365 for Agents | A4; A5; A6 | TL-07 | TS4 | TEC.13; TEC.08 | red — not available in UAE North / out-of-region | W365 for Agents not in UAE | Node |  |
| cmp-9966b5b9c7 | tl | Legacy adapters | on-prem gateway · Logic Apps HL7v2 | A2; A3; A6 | TL-08 | IN1 | APP.10 | green — available in UAE North |  | Application component |  |
| cmp-71ed59abfd | tl | System-agent delegation | A2A client to vendor agents | A4; A8 | TL-09 | IN1 | BND.03 | green — available in UAE North |  | Application component |  |
| cmp-b8240b9c4a | mp | Model selection & routing | Foundry Model Router · APIM backend pools |  | MP-00 | MS1 | COG.23 | amber — partial / preview / not region-pinned | follows Global Standard | Application component |  |
| cmp-525072e4ab | mp | Regional Provisioned models | UAE North · 9 chat models | A2; A3; A5; A6 | MP-01 | MS2 | COG.14; COG.13 | green — available in UAE North | in-region processing | Application component | Node: Azure UAE North |
| cmp-8b6a0424ac | mp | Standard embeddings & speech | UAE North |  | MP-02 | MS2 | COG.13 | green — available in UAE North |  | Application component | Node: Azure UAE North |
| cmp-04eb9f6438 | mp | On-device / edge inference | Foundry Local |  | MP-03 | MS5 | TEC.14 | green — available in UAE North |  | System software | Node: user device / edge |
| cmp-53268858c5 | mp | Core42 Compass | 50+ models incl. Claude · Azure UAE |  | MP-04 | MS3 | COG.13; COG.23 | sovereign — Core42 in-country | in-country | Application component | Node: Core42, Azure UAE (in-country) |
| cmp-a04d92973f | mp | Core42 AI Cloud | dedicated sovereign GPU capacity |  | MP-05 | MS3 | COG.14 | sovereign — Core42 in-country |  | Node | — |
| cmp-bd9ee43705 | mp | Foundry Global Standard | OpenAI & partner models | A1; A2; A3; A4; A5; A6; A7; A8 | MP-06 | MS4 | COG.13 | amber — partial / preview / not region-pinned | inference not pinned to UAE | Application component | Node: Azure global (not region-pinned) |
| cmp-bdda5f32b1 | mp | Foundry Claude | non-UAE region · Azure-billed | A2; A3; A4; A5 | MP-07 | MS4 | COG.13 | red — not available in UAE North / out-of-region | out-of-region · PHI never sent | Application component | Node: Azure non-UAE region |
| cmp-7ab6cbe5a9 | mp | Anthropic via M365 Copilot | Microsoft subprocessor |  | MP-08 | MS4 | RCV.01 | amber — partial / preview / not region-pinned | direct from EX-03, not via APIM | Application component | Node: Anthropic, outside Microsoft-managed environment |
| cmp-80346290a1 | dt | Operational store | Dataverse | A2; A3; A6 | DT-01 | DS1 | DAT.01 | green — available in UAE North |  | System software |  |
| cmp-a4e0fc557b | dt | Analytical store | OneLake | A1; A5 | DT-02 | DS1 | DAT.02 | green — available in UAE North |  | System software |  |
| cmp-bb7cd41d32 | dt | Content & records | SharePoint · Purview records | A1; A2; A5; A7 | DT-03 | DS1 | DAT.07 | green — available in UAE North |  | Application component |  |
| cmp-cfcb60a693 | dt | Telemetry store | Log Analytics · Eventhouse |  | DT-04 | GV6 | DAT.08 | green — available in UAE North |  | System software |  |
| cmp-414ec62cf6 | me | Model sourcing | Foundry catalog · benchmarks |  | ME-01 | ME1 | MOD.01 | amber — partial / preview / not region-pinned |  | Application component |  |
| cmp-d10c878a6e | me | Training & test data | Azure ML labelling · AHDS de-id |  | ME-02 | ME2 | MOD.02; DAT.09 | green — available in UAE North |  | Application component |  |
| cmp-e025ba39a5 | me | Model customisation | Foundry fine-tuning · Core42 fine-tuning |  | ME-03 | ME2 | MOD.03 | red — not available in UAE North / out-of-region | Foundry not in UAE North — use Core42 | Application component |  |
| cmp-170ae7a2ca | me | Validation & registry | Foundry evaluations · Azure ML registry |  | ME-04 | ME1 | MOD.04; MOD.05 | green — available in UAE North |  | Application component |  |
| cmp-3cdc0f8afd | me | Serving & capacity | deployment types · quotas |  | ME-05 | ME3 | MOD.06 | amber — partial / preview / not region-pinned | no Batch / Data Zone | Technology service |  |
| cmp-1124661061 | me | Monitoring & lifecycle | deployment monitoring · drift · retirement |  | ME-06 | ME3 | MOD.07; MOD.08 | green — available in UAE North |  | Application component |  |
| cmp-6f03e705a2 | me | Experimentation | Foundry portal · Compass Playground |  | ME-07 | ME2 | COG.27 | green — available in UAE North |  | Application component |  |
| cmp-b53c07acc7 | sec | Identity | Entra ID — users · keyless | A1; A2; A3; A4; A5; A6; A7; A8 | SEC-01 | SC1 | TEC.09 | green — available in UAE North |  | Application component |  |
| cmp-d217dd5b1b | sec | Agent identity | Entra Agent ID | A2; A3; A4; A6 | SEC-02 | SC1 | COG.06 | green — available in UAE North |  | Application component |  |
| cmp-6b2726fb06 | sec | Secrets & keys | Key Vault · Managed HSM | A1; A2; A3; A4; A5; A6; A7; A8 | SEC-03 | SC2 | TEC.18 | green — available in UAE North |  | Technology service | Node: Azure UAE North |
| cmp-97b34e3212 | sec | AI provider egress control | Global Secure Access · Defender for Cloud Apps |  | SEC-04 | SC3 | TEC.15 | amber — partial / preview / not region-pinned | blocks direct vendor access | Application component |  |
| cmp-e897ae4e0e | sec | Security operations | Defender for Cloud · Sentinel | A1; A2; A3; A4; A5; A6; A7; A8 | SEC-05 | SC4 | TEC.05; TEC.17 | green — available in UAE North |  | Application component |  |
| cmp-24a7eea78f | sec | Data protection | Purview DSPM for AI · DLP · labels | A1; A2; A3; A4; A5; A6; A7; A8 | SEC-06 | SC5 | XCT.13; RCV.06 | green — available in UAE North |  | Application component |  |
| cmp-2e97fd6b66 | gov | Agent control plane | Agent 365 · Foundry control plane · Citadel hub | A1; A2; A3; A4; A5; A6; A7; A8 | GOV-01 | GV1 | COG.07; XCT.05; XCT.03; XCT.06 | amber — partial / preview / not region-pinned | cross-cloud sync preview | Application component |  |
| cmp-d558ec486a | gov | Emergency stop | Agent 365 block · Agent ID disable · APIM kill switch |  | GOV-02 | GV1 | XCT.23 | green — available in UAE North |  | Application service | Composed of GOV-01, SEC-02 and GW-02 functions |
| cmp-6764064c46 | gov | Access lifecycle | Entra ID Governance — people & agents |  | GOV-03 | GV2 | XCT.24; XCT.15; XCT.17 | green — available in UAE North |  | Application component |  |
| cmp-e82410cd2b | gov | Managed client configuration | Intune |  | GOV-04 | GV3 | RCV.09; RCV.07 | green — available in UAE North |  | Application component |  |
| cmp-1c5c3eaa1e | gov | Release & supply chain | GitHub Actions · signed manifests · staged rollout | A2; A3; A4; A5; A6; A8 | GOV-05 | GV4 | COG.11; COG.28 | green — available in UAE North |  | Application component |  |
| cmp-3d0221ca2e | gov | Evaluation & improvement | Foundry Evaluations · continuous · human · feedback · optimizer | A1; A2; A3; A4; A5; A6; A7; A8 | GOV-06 | GV5 | COG.12; COG.26; COG.31; COG.32; COG.33; XCT.20 | amber — partial / preview / not region-pinned | agent evaluation partial | Application component |  |
| cmp-aea7a42520 | gov | Adversarial testing | AI Red Teaming Agent / PyRIT |  | GOV-07 | GV5 | COG.19 | red — not available in UAE North / out-of-region | run PyRIT locally | Application component |  |
| cmp-ad7e4cd271 | gov | Observability & cost | App Insights · Foundry tracing · Cost Management | A1; A2; A3; A4; A5; A6; A7; A8 | GOV-08 | GV6 | TEC.10 | green — available in UAE North |  | Application component |  |
| cmp-b9e1efa0d4 | gov | Assurance & evidence | Compliance Manager · approval log · outcome checks |  | GOV-09 | GV7 | XCT.14; XCT.22; XCT.18 | green — available in UAE North |  | Application component |  |
| cmp-f40986dc3c | gov | Adoption & received-agent oversight | Copilot analytics · Agent 365 |  | GOV-10 | GV8 | RCV.08; BUS.06 | green — available in UAE North |  | Application component |  |
| cmp-78981a2d34 | gov | Sovereignty controls | Sovereign Public Cloud controls · Core42 boundary |  | GOV-11 | GV9 | XCT.16 | sovereign — Core42 in-country |  | Technology service |  |
| cmp-424a9c13f5 | pf | Governed cloud foundation | Azure landing zone | A1; A2; A3; A4; A5; A6; A7; A8 | PF-01 | FD1 | XCT.02 | green — available in UAE North |  | Grouping |  |
| cmp-0f7bf7363a | pf | Team agent environments | Citadel spoke |  | PF-02 | FD1 | XCT.04 | green — available in UAE North |  | Grouping |  |
| cmp-c4e17a8741 | pf | Network isolation | private endpoints · firewall | A1; A2; A3; A4; A5; A6; A7; A8 | PF-03 | FD2 | TEC.04 | green — available in UAE North |  | Communication network |  |
| cmp-b34fc7072e | pf | Policy-as-code | Azure Policy |  | PF-04 | FD1 | TEC.19 | green — available in UAE North |  | Technology service |  |
| cmp-f560d81190 | pf | Compute | Container Apps · AKS | A1; A2; A3; A4; A5; A6; A7; A8 | PF-05 | AG1 | TEC.11; TEC.07 | green — available in UAE North |  | Node |  |
| cmp-9e12cc8029 | pf | Resilience & recovery | zones · Site Recovery · Backup |  | PF-06 | FD3 | TEC.22 | amber — partial / preview / not region-pinned | no paired region | Technology service |  |
| cmp-856e928095 | pf | Confidential computing | confidential VMs & containers |  | PF-07 | FD4 | TEC.20 | green — available in UAE North |  | Node |  |
