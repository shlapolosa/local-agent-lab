# Reference architecture model — components

**Artifact:** reference_architecture
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** components

| id | zone | name | detail | archetypes |
|---|---|---|---|---|
| cmp-a9c03320dd | exp | M365 Copilot | Teams · chat | A1; A7 |
| cmp-033b5a487e | exp | Web / Power Apps | portal · SPA | A2; A3; A5 |
| cmp-42c5354b00 | exp | Mobile / Voice | apps · Voice Live | A2; A3; A6 |
| cmp-84e9a23288 | exp | System | REST · webhooks · A2A | A2; A3; A4; A5; A6; A8 |
| cmp-f829997915 | exp | External portal | partner · customer | A2; A3 |
| cmp-0627c94e41 | gw | Front Door + WAF | edge · DDoS | A2; A3; A5 |
| cmp-967db4e8ad | gw | APIM — AI Gateway | token limit · cache · safety | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-5cf110edd7 | gw | Channel adapters | Agents SDK · Bot · Event Grid | A1; A2; A3; A6; A7; A8 |
| cmp-509a96ba37 | gw | MCP edge | registry · OAuth (G04) | A2; A3; A4; A5; A6; A8 |
| cmp-bbc8ece486 | cog | Declarative agent | M365 Copilot | A1; A7 |
| cmp-6c71a39bbd | cog | Copilot Studio engine | custom engine | A2; A3 |
| cmp-5ebda000ea | cog | Foundry agents | prompt · workflow · hosted | A2; A3; A4; A5; A6; A8 |
| cmp-aeadf1eec9 | cog | Agent Framework | orchestration · manifests (G01) | A2; A3; A4; A5; A6; A8 |
| cmp-1c5c3eaa1e | cog | Manifest & supply chain | Azure DevOps · GitHub Actions (G01) | A2; A3; A4; A5; A6; A8 |
| cmp-356d2c0c79 | knw | Foundry IQ | federated · real-time-pull | A1; A2; A3; A5; A6; A8 |
| cmp-32f3ba0461 | knw | Work IQ | M365 context | A1; A2; A5 |
| cmp-e2eb6b87f6 | knw | Azure AI Search | vector · ranker | A1; A2; A3; A5; A6; A8 |
| cmp-478c3d8b94 | knw | Fabric IQ | ontology · glossary | A5 |
| cmp-a14ab8a7ec | knw | Purview glossary | semantic layer | A1; A2; A5 |
| cmp-32c1a7192d | knw | Knowledge sources | SharePoint · OneLake · Blob · Web · MCP | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-bd9ee43705 | mod | Foundry model catalog | GPT · Claude · Llama | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-525072e4ab | mod | Local / fine-tuned | PTU · SLM | A2; A3; A5; A6 |
| cmp-bdda5f32b1 | mod | Remote (via APIM) | Anthropic · OpenAI | A2; A3; A4; A5 |
| cmp-9b2ff06ba9 | too | MCP servers | Dataverse · GitHub (G02) | A2; A3; A4; A5; A6 |
| cmp-97a1005c0e | too | Dataverse skills | business skills | A2; A3 |
| cmp-aa1d470734 | too | Power Automate | approvals (G09) | A2; A3; A6 |
| cmp-9c2fb48665 | too | Integration | Service Bus · Event Hubs | A2; A3; A6 |
| cmp-80346290a1 | data | Dataverse | operational | A2; A3; A6 |
| cmp-176a9d7458 | data | Azure SQL | operational | A2; A3; A6 |
| cmp-a4e0fc557b | data | OneLake | analytical | A1; A5 |
| cmp-bb7cd41d32 | data | SharePoint | content | A1; A2; A5; A7 |
| cmp-4a273d4fb4 | data | Agent state | Cosmos · Redis | A4; A6 |
| cmp-2890589d1b | ext | ERP | SAP · D365 F&O | A2; A3; A6 |
| cmp-ce437fee9f | ext | CRM | D365 · Salesforce | A2; A3; A6 |
| cmp-8064b22dd7 | ext | ITSM | ServiceNow | A2; A3; A6 |
| cmp-81d9f22a6e | ext | SaaS / Web | partner APIs · Bing | A2; A3; A5; A6 |
| cmp-9966b5b9c7 | ext | On-prem gateway | ExpressRoute | A2; A3; A6 |
| cmp-ff5cdd7985 | ext | HRIS / Identity | Workday · SuccessFactors | A2; A3; A6 |
| cmp-71ed59abfd | ext | External agents (A2A) | partner agents | A4; A8 |
| cmp-b53c07acc7 | ident | Microsoft Entra ID | users · workloads | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-d217dd5b1b | ident | Entra Agent ID | blueprints | A2; A3; A4; A6 |
| cmp-be8e171c6e | ident | Conditional Access | adaptive | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-6b2726fb06 | ident | Key Vault | secrets | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-24a7eea78f | ident | Purview | catalog · DLP | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-f620c48a83 | ident | Citadel Hub | policy-as-code | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-2e97fd6b66 | ident | Microsoft Agent 365 | control plane · cross-cloud (G14) | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-03cb07d13f | ident | Agent Governance Toolkit | open-source · agent-level | A2; A3; A4; A6 |
| cmp-ad7e4cd271 | obs | App Insights | traces | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-c21bb9ac9b | obs | Foundry traces | agent runs | A2; A3; A4; A5; A6 |
| cmp-3d0221ca2e | obs | Evaluations | gate deploy (G10) | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-ba46b85574 | obs | Cost Management | token metering | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-e897ae4e0e | obs | Microsoft Sentinel | SIEM / SOAR | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-8d11d4f751 | obs | Defender for Cloud | posture · workload protection | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-424a9c13f5 | plat | Landing zone | CAF AI Ready | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-c4e17a8741 | plat | Networking | private endpoints · firewall | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-f560d81190 | plat | Compute hosts | Foundry · ACA · AKS | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-b7ef1e4759 | plat | WAF AI pillars | 5 pillars | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-b4fa47e277 | plat | AAC baselines | Foundry Chat · Agentic | A1; A2; A3; A4; A5; A6; A7; A8 |
| cmp-adcfb4323e | plat | Windows 365 for Agents | sandboxed agent runtime VM | A4; A5; A6 |
