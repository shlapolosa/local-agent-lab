# Build surface decisions

**Artifact:** build_surface
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Q | Question | Outcome |
|---|---|---|
| S1.0 | Does an incumbent platform already own the workflow graph and the system of record? | YES → evaluate its own inference or extension point against the control requirement set, on equal terms. Satisfies the obligations → select it and record the AI components as extensions (this is RA-8). Fails them → record which obligations it failed , then continue. NO → continue to S1.1 |
| S1.1 | Must the agent run inside M365 Copilot surfaces and use the Copilot orchestrator? | YES → declarative agent (Copilot Studio / Agents Toolkit). NO → continue |
| S1.2 | Is the orchestration logic non-trivial (multi-agent, custom tool routing, custom model) AND must it run outside M365 surfaces? | YES → custom engine agent on Microsoft Agent Framework, hosted on Foundry Agent Service. NO → Foundry prompt agent (configuration-only) |
| S1.3 | Does it require its own identity for background or autonomous workloads? | YES → Entra Agent ID from an Agent Identity Blueprint, authenticating via Managed Identity. NO → user-delegated permissions only |
