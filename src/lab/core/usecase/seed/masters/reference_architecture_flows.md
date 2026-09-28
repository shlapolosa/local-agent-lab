# Reference architecture — flows

**Artifact:** reference_architecture_flows
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| id | from | to | meaning | controls |
|---|---|---|---|---|
| F01 | ex | gw | All AI traffic from people and received agents | AI provider egress control; Entra sign-in; managed client settings |
| F02 | gw | ag | Requests to governed agents | Gateway authentication, quotas, logging |
| F03 | ag | gw | Agents call models through the gateway | Same gateway policies as clients |
| F04 | gw | mp | Every model call → sensitive-data decision → residency lane | Block · redact · reroute; out-of-region for PHI-free content only (G29) |
| F05 | ex | mp | Microsoft 365 Copilot to Anthropic (Microsoft-managed path, not via the gateway) | Purview DLP and sensitivity labels |
| F06 | ag | kn | Retrieve grounding | Registered sources only; permission-trimmed (G06) |
| F07 | ag | tl | Act through tools | Registered tools; interception pre-flight (G02) |
| F08 | tl | bn | Traditional systems via standard tool protocol (default), skill or A2A | Boundary rule |
| F09 | kn | dt | Read sources |  |
| F10 | tl | dt | Write records | Compensation on failure (G23) |
| F11 | me | mp | Publish approved models | Validation and registry (G32) |
| F12 | sec · gov | all | Security and governance pillars apply to every layer |  |
