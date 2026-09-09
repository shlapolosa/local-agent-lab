# Reference architecture model — components

**Artifact:** reference_architecture
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** components

| zone | name | detail | archetypes |
|---|---|---|---|
| exp | M365 Copilot | Teams · chat | A1; A7 |
| exp | Web / Power Apps | portal · SPA | A2; A3; A5 |
| exp | Mobile / Voice | apps · Voice Live | A2; A3; A6 |
| exp | System | REST · webhooks · A2A | A2; A3; A4; A5; A6; A8 |
| exp | External portal | partner · customer | A2; A3 |
| gw | Front Door + WAF | edge · DDoS | A2; A3; A5 |
| gw | APIM — AI Gateway | token limit · cache · safety | A1; A2; A3; A4; A5; A6; A7; A8 |
| gw | Channel adapters | Agents SDK · Bot · Event Grid | A1; A2; A3; A6; A7; A8 |
| gw | MCP edge | registry · OAuth (G04) | A2; A3; A4; A5; A6; A8 |
| cog | Declarative agent | M365 Copilot | A1; A7 |
| cog | Copilot Studio engine | custom engine | A2; A3 |
| cog | Foundry agents | prompt · workflow · hosted | A2; A3; A4; A5; A6; A8 |
| cog | Agent Framework | orchestration · manifests (G01) | A2; A3; A4; A5; A6; A8 |
| cog | Manifest & supply chain | Azure DevOps · GitHub Actions (G01) | A2; A3; A4; A5; A6; A8 |
| knw | Foundry IQ | federated · real-time-pull | A1; A2; A3; A5; A6; A8 |
| knw | Work IQ | M365 context | A1; A2; A5 |
| knw | Azure AI Search | vector · ranker | A1; A2; A3; A5; A6; A8 |
| knw | Fabric IQ | ontology · glossary | A5 |
| knw | Purview glossary | semantic layer | A1; A2; A5 |
| knw | Knowledge sources | SharePoint · OneLake · Blob · Web · MCP | A1; A2; A3; A4; A5; A6; A7; A8 |
| mod | Foundry model catalog | GPT · Claude · Llama | A1; A2; A3; A4; A5; A6; A7; A8 |
| mod | Local / fine-tuned | PTU · SLM | A2; A3; A5; A6 |
| mod | Remote (via APIM) | Anthropic · OpenAI | A2; A3; A4; A5 |
| too | MCP servers | Dataverse · GitHub (G02) | A2; A3; A4; A5; A6 |
| too | Dataverse skills | business skills | A2; A3 |
| too | Power Automate | approvals (G09) | A2; A3; A6 |
| too | Integration | Service Bus · Event Hubs | A2; A3; A6 |
| data | Dataverse | operational | A2; A3; A6 |
| data | Azure SQL | operational | A2; A3; A6 |
| data | OneLake | analytical | A1; A5 |
| data | SharePoint | content | A1; A2; A5; A7 |
| data | Agent state | Cosmos · Redis | A4; A6 |
| ext | ERP | SAP · D365 F&O | A2; A3; A6 |
| ext | CRM | D365 · Salesforce | A2; A3; A6 |
| ext | ITSM | ServiceNow | A2; A3; A6 |
| ext | SaaS / Web | partner APIs · Bing | A2; A3; A5; A6 |
| ext | On-prem gateway | ExpressRoute | A2; A3; A6 |
| ext | HRIS / Identity | Workday · SuccessFactors | A2; A3; A6 |
| ext | External agents (A2A) | partner agents | A4; A8 |
| ident | Microsoft Entra ID | users · workloads | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Entra Agent ID | blueprints | A2; A3; A4; A6 |
| ident | Conditional Access | adaptive | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Key Vault | secrets | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Purview | catalog · DLP | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Citadel Hub | policy-as-code | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Microsoft Agent 365 | control plane · cross-cloud (G14) | A1; A2; A3; A4; A5; A6; A7; A8 |
| ident | Agent Governance Toolkit | open-source · agent-level | A2; A3; A4; A6 |
| obs | App Insights | traces | A1; A2; A3; A4; A5; A6; A7; A8 |
| obs | Foundry traces | agent runs | A2; A3; A4; A5; A6 |
| obs | Evaluations | gate deploy (G10) | A1; A2; A3; A4; A5; A6; A7; A8 |
| obs | Cost Management | token metering | A1; A2; A3; A4; A5; A6; A7; A8 |
| obs | Microsoft Sentinel | SIEM / SOAR | A1; A2; A3; A4; A5; A6; A7; A8 |
| obs | Defender for Cloud | posture · workload protection | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | Landing zone | CAF AI Ready | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | Networking | private endpoints · firewall | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | Compute hosts | Foundry · ACA · AKS | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | WAF AI pillars | 5 pillars | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | AAC baselines | Foundry Chat · Agentic | A1; A2; A3; A4; A5; A6; A7; A8 |
| plat | Windows 365 for Agents | sandboxed agent runtime VM | A4; A5; A6 |
