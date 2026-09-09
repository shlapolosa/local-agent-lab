# Reference architecture model — topologies

**Artifact:** reference_architecture
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** topologies

| id | name | desc | base | families | note |
|---|---|---|---|---|---|
| T1 | T1 · Inline | The calling surface owns control flow. A single request and response, with no plan. Choose when the workflow is one step, or a few with no branching. | Baseline: AAC Basic Chat / production chat reference. | F2 inference, F6 identity, F7 control plane, F8 evaluation; F1 where the step retrieves. | Modifiers commonly: interactive trigger, human in-loop. |
| T2 | T2 · Agent-orchestrated | The agent owns a plan graph and calls tools. Choose when the workflow exists only because this agent runs it and nothing outside the AI estate would execute the graph. | Baseline: AAC Baseline Agentic AI Systems. | F1 (federated where sources exceed one), F2, F3 where concepts are named, F4 and F5 where a step commits, plus F6, F7, F8; F9 where influence reaches 2. | This is where budgets and circuit breakers (G08) sit, because the agent owns the plan. |
| T3 | T3 · Platform-orchestrated | A non-AI orchestrator outside CAFÉ's AI scope owns the workflow graph and invokes inference per step. The common case in an estate with an existing process portfolio. | Baseline: the incumbent platform's own release and deployment model. | F1, F2, F3, F9, F11, F12 in the AI estate; F4, F5, F10 and F13 resolve to the platform as declared boundary interfaces. | The canvas below is drawn agent-centric and cannot render this inversion — the highlight shows only the AI-estate components. Control flow, commits and outcome monitoring sit outside the frame. |
| T4 | T4 · Delegated | An agent routes to other agents, each owning its own sub-graph. Choose on ownership — different tool surfaces, data boundaries or owning teams — never merely because the graph is large. | Baseline: AAC Baseline Agentic AI Systems with an A2A channel. | F14 delegation plus the union of the families each sub-agent requires. | Carries G07: inter-agent channels are authenticated and handoffs logged with intent and payload. |
