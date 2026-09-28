# Technology capability map — L1 domains

**Artifact:** technology_capability_l1
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| id | name | description | when_exercised | l2_count | l3_count |
|---|---|---|---|---|---|
| BUS | Business | What the business does and the rules it runs by — the source of agent intent. | Design · Stage 0; whenever a business rule changes | 4 | 7 |
| SEM | Semantic | Shared meaning: concepts, terms and reference data an agent reasons over. | Design · Stage 0 E0.6; runtime when a step names a concept | 4 | 11 |
| KNW | Knowledge | Finding and supplying grounding content, permission-trimmed and cited. | Design · Stage 0 E0.8; runtime on every retrieval | 4 | 14 |
| COG | Cognitive | Agents, models and their governance — reasoning, identity, evaluation. | Design · Stages 4–5; runtime on every inference | 7 | 32 |
| MOD | Model engineering | Creating, adapting and managing models themselves — as distinct from using them (Cognitive). | Stage 5 model decisions; each training cycle; through model end-of-life | 3 | 8 |
| APP | Application | Doing things in business systems — actions, apps, UI automation. | Runtime · whenever a step writes or acts | 3 | 10 |
| DAT | Data | Storing operational, analytical, content and agent-state data. | Runtime · on every read and write | 3 | 8 |
| TEC | Technology | Infrastructure that carries traffic and hosts agents securely. | Provisioned at deployment; exercised on every request | 7 | 24 |
| XCT | Cross-cutting | Governance, baselines and assurance applied across all domains. | Design · Stages 6–7; continuously in operation | 5 | 19 |
| RCV | Received agents | Agents that arrive with a licence, device or SaaS product rather than being built — governed, not composed. | At vendor or tenant enablement; continuously while enabled | 3 | 9 |
| PPL | People & operating model | The skills, roles and ways of working that let people build, oversee, use and live with agents safely. | From business case to retirement; gates access to every other domain | 4 | 9 |
| BND | Boundary — traditional systems | Never catalogued here: reached only by integration — MCP by default, a skill for business actions, A2A only where the system exposes its own agent. Replaces the six system-type rows (alerting, streaming, comms fallback, LOB / identity systems of record, sensor telemetry). | Runtime · every call from an agent to a traditional system | 1 | 4 |
