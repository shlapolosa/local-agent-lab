# Logical reference architecture — principles and constraints

**Artifact:** reference_architecture_principles
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| id | principle |
|---|---|
| RP01 | Every AI call passes the AI gateway and the sensitive-data policy point. |
| RP02 | Health data stays in the UAE: block, redact or reroute before any out-of-region call. |
| RP03 | Deterministic core, agentic shell: the workflow — not a model — owns control flow. |
| RP04 | No business logic in prompts: rules and context arrive through governed runtime channels. |
| RP05 | Traditional systems are reached only through governed integration — standard tool protocol by default. |
| RP06 | One identity per person and agent; access follows the HR lifecycle. |
| RP07 | Nothing runs unregistered; every agent and tool can be stopped. |
| RP08 | Microsoft is the preferred, billing-consolidating vendor; Core42 is the in-country provider. |
| RP09 | Evaluation gates every release; production quality is monitored continuously. |
| RP10 | Received agents are governed, not built: admitted, configured and monitored. |
