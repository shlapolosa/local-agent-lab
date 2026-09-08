# Reference architecture model

**Artifact:** reference_architecture
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

{
  "archetypes": [
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "A7",
    "A8"
  ],
  "zones": {
    "exp": {
      "label": "Experience & Channels",
      "sub": "channels",
      "x": 264,
      "y": 64,
      "w": 952,
      "h": 92,
      "fill": "#20304f",
      "stroke": "#5a82c4"
    },
    "gw": {
      "label": "Edge & AI Gateway",
      "sub": "runtime enforcement",
      "x": 264,
      "y": 176,
      "w": 952,
      "h": 104,
      "fill": "#16384a",
      "stroke": "#4aa0c4"
    },
    "cog": {
      "label": "Cognitive Plane",
      "sub": "agents · orchestration",
      "x": 264,
      "y": 300,
      "w": 952,
      "h": 120,
      "fill": "#2f1d47",
      "stroke": "#9a6fd0"
    },
    "knw": {
      "label": "Knowledge & Semantic",
      "sub": "grounding (G06)",
      "x": 264,
      "y": 440,
      "w": 300,
      "h": 156,
      "fill": "#0e3b30",
      "stroke": "#3fae8e"
    },
    "mod": {
      "label": "Models",
      "sub": "via APIM gateway",
      "x": 584,
      "y": 440,
      "w": 300,
      "h": 156,
      "fill": "#3f2a0c",
      "stroke": "#d09a4e"
    },
    "too": {
      "label": "Tools & Integration",
      "sub": "actions (G02)",
      "x": 904,
      "y": 440,
      "w": 312,
      "h": 156,
      "fill": "#093840",
      "stroke": "#4faab8"
    },
    "data": {
      "label": "Data Plane",
      "sub": "systems of record",
      "x": 264,
      "y": 616,
      "w": 952,
      "h": 104,
      "fill": "#20304f",
      "stroke": "#5a82c4"
    },
    "ext": {
      "label": "External Systems",
      "sub": "mediated by APIM",
      "x": 264,
      "y": 740,
      "w": 952,
      "h": 112,
      "fill": "#322820",
      "stroke": "#9a7a5a"
    },
    "ident": {
      "label": "Identity & Trust",
      "sub": "cross-cutting",
      "x": 16,
      "y": 64,
      "w": 232,
      "h": 860,
      "fill": "#34141e",
      "stroke": "#c0526e"
    },
    "obs": {
      "label": "Observability · Cost · Eval",
      "sub": "cross-cutting",
      "x": 1232,
      "y": 64,
      "w": 232,
      "h": 860,
      "fill": "#1b321a",
      "stroke": "#6aaa60"
    },
    "plat": {
      "label": "Platform Foundation",
      "sub": "Azure landing zone · WAF",
      "x": 16,
      "y": 944,
      "w": 1448,
      "h": 120,
      "fill": "#23272f",
      "stroke": "#6a7488"
    }
  },
  "components": [
    [
      "exp",
      "M365 Copilot",
      "Teams · chat",
      [
        "A1",
        "A7"
      ]
    ],
    [
      "exp",
      "Web / Power Apps",
      "portal · SPA",
      [
        "A2",
        "A3",
        "A5"
      ]
    ],
    [
      "exp",
      "Mobile / Voice",
      "apps · Voice Live",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "exp",
      "System",
      "REST · webhooks · A2A",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "exp",
      "External portal",
      "partner · customer",
      [
        "A2",
        "A3"
      ]
    ],
    [
      "gw",
      "Front Door + WAF",
      "edge · DDoS",
      [
        "A2",
        "A3",
        "A5"
      ]
    ],
    [
      "gw",
      "APIM — AI Gateway",
      "token limit · cache · safety",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "gw",
      "Channel adapters",
      "Agents SDK · Bot · Event Grid",
      [
        "A1",
        "A2",
        "A3",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "gw",
      "MCP edge",
      "registry · OAuth (G04)",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "cog",
      "Declarative agent",
      "M365 Copilot",
      [
        "A1",
        "A7"
      ]
    ],
    [
      "cog",
      "Copilot Studio engine",
      "custom engine",
      [
        "A2",
        "A3"
      ]
    ],
    [
      "cog",
      "Foundry agents",
      "prompt · workflow · hosted",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "cog",
      "Agent Framework",
      "orchestration · manifests (G01)",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "cog",
      "Manifest & supply chain",
      "Azure DevOps · GitHub Actions (G01)",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "knw",
      "Foundry IQ",
      "federated · real-time-pull",
      [
        "A1",
        "A2",
        "A3",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "knw",
      "Work IQ",
      "M365 context",
      [
        "A1",
        "A2",
        "A5"
      ]
    ],
    [
      "knw",
      "Azure AI Search",
      "vector · ranker",
      [
        "A1",
        "A2",
        "A3",
        "A5",
        "A6",
        "A8"
      ]
    ],
    [
      "knw",
      "Fabric IQ",
      "ontology · glossary",
      [
        "A5"
      ]
    ],
    [
      "knw",
      "Purview glossary",
      "semantic layer",
      [
        "A1",
        "A2",
        "A5"
      ]
    ],
    [
      "knw",
      "Knowledge sources",
      "SharePoint · OneLake · Blob · Web · MCP",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "mod",
      "Foundry model catalog",
      "GPT · Claude · Llama",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "mod",
      "Local / fine-tuned",
      "PTU · SLM",
      [
        "A2",
        "A3",
        "A5",
        "A6"
      ]
    ],
    [
      "mod",
      "Remote (via APIM)",
      "Anthropic · OpenAI",
      [
        "A2",
        "A3",
        "A4",
        "A5"
      ]
    ],
    [
      "too",
      "MCP servers",
      "Dataverse · GitHub (G02)",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6"
      ]
    ],
    [
      "too",
      "Dataverse skills",
      "business skills",
      [
        "A2",
        "A3"
      ]
    ],
    [
      "too",
      "Power Automate",
      "approvals (G09)",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "too",
      "Integration",
      "Service Bus · Event Hubs",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "data",
      "Dataverse",
      "operational",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "data",
      "Azure SQL",
      "operational",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "data",
      "OneLake",
      "analytical",
      [
        "A1",
        "A5"
      ]
    ],
    [
      "data",
      "SharePoint",
      "content",
      [
        "A1",
        "A2",
        "A5",
        "A7"
      ]
    ],
    [
      "data",
      "Agent state",
      "Cosmos · Redis",
      [
        "A4",
        "A6"
      ]
    ],
    [
      "ext",
      "ERP",
      "SAP · D365 F&O",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "ext",
      "CRM",
      "D365 · Salesforce",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "ext",
      "ITSM",
      "ServiceNow",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "ext",
      "SaaS / Web",
      "partner APIs · Bing",
      [
        "A2",
        "A3",
        "A5",
        "A6"
      ]
    ],
    [
      "ext",
      "On-prem gateway",
      "ExpressRoute",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "ext",
      "HRIS / Identity",
      "Workday · SuccessFactors",
      [
        "A2",
        "A3",
        "A6"
      ]
    ],
    [
      "ext",
      "External agents (A2A)",
      "partner agents",
      [
        "A4",
        "A8"
      ]
    ],
    [
      "ident",
      "Microsoft Entra ID",
      "users · workloads",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Entra Agent ID",
      "blueprints",
      [
        "A2",
        "A3",
        "A4",
        "A6"
      ]
    ],
    [
      "ident",
      "Conditional Access",
      "adaptive",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Key Vault",
      "secrets",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Purview",
      "catalog · DLP",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Citadel Hub",
      "policy-as-code",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Microsoft Agent 365",
      "control plane · cross-cloud (G14)",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "ident",
      "Agent Governance Toolkit",
      "open-source · agent-level",
      [
        "A2",
        "A3",
        "A4",
        "A6"
      ]
    ],
    [
      "obs",
      "App Insights",
      "traces",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "obs",
      "Foundry traces",
      "agent runs",
      [
        "A2",
        "A3",
        "A4",
        "A5",
        "A6"
      ]
    ],
    [
      "obs",
      "Evaluations",
      "gate deploy (G10)",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "obs",
      "Cost Management",
      "token metering",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "obs",
      "Microsoft Sentinel",
      "SIEM / SOAR",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "obs",
      "Defender for Cloud",
      "posture · workload protection",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "Landing zone",
      "CAF AI Ready",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "Networking",
      "private endpoints · firewall",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "Compute hosts",
      "Foundry · ACA · AKS",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "WAF AI pillars",
      "5 pillars",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "AAC baselines",
      "Foundry Chat · Agentic",
      [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8"
      ]
    ],
    [
      "plat",
      "Windows 365 for Agents",
      "sandboxed agent runtime VM",
      [
        "A4",
        "A5",
        "A6"
      ]
    ]
  ],
  "columns": {
    "exp": 5,
    "gw": 4,
    "cog": 4,
    "knw": 2,
    "mod": 1,
    "too": 2,
    "data": 5,
    "ext": 5,
    "ident": 1,
    "obs": 1,
    "plat": 5
  },
  "detail": {
    "": {
      "title": "All archetypes",
      "purpose": "The diagram shows the full canonical composition. The enterprise scaffolding — gateway, identity, governance, observability, networking, landing zone — is shared by every archetype; only the Cognitive plane and the tools/sources it calls vary. Pick an archetype to dim everything except what it activates.",
      "baseline": "Pair the relevant slice with the matching Azure Architecture Center baseline — Basic / Baseline Foundry Chat, Baseline in a Landing Zone, or Baseline Agentic AI Systems.",
      "srcs": [
        "S20",
        "S21",
        "S22",
        "S23"
      ],
      "guards": [
        "G01",
        "G02",
        "G03",
        "G04",
        "G05",
        "G06",
        "G07",
        "G08",
        "G09",
        "G10"
      ],
      "decisions": [
        "Run M2 (decision tree) to route the use case to one archetype before reading its slice here."
      ],
      "evidence": "Each archetype carries its own evidence trail — select one to see it."
    },
    "A1": {
      "title": "A1 · Assistive Q&A Agent",
      "purpose": "Grounded question answering over a defined corpus with citations and no side effects.",
      "baseline": "AAC Baseline Microsoft Foundry Chat; regulated workloads use the Landing-Zone variant; opinionated one-click via a Citadel spoke.",
      "srcs": [
        "S21",
        "S22",
        "S24"
      ],
      "guards": [
        "G01",
        "G06",
        "G10"
      ],
      "decisions": [
        "Corpus boundary (which SharePoint / OneLake paths)",
        "Refusal policy when retrieval < k results",
        "Citation form (inline vs footnote)",
        "Audience — employee-only by default"
      ],
      "evidence": "Foundry IQ logs (sub-query, source, score, doc-id); Purview access audit; Entra sign-in trail."
    },
    "A2": {
      "title": "A2 · Task Execution Agent",
      "purpose": "Validate a natural-language request against business rules and execute a bounded transaction in a system of record, with human approval on the trust-sensitive step.",
      "baseline": "Baseline Foundry Chat or a Citadel spoke for runtime enforcement via the AI Gateway.",
      "srcs": [
        "S21",
        "S24",
        "S25"
      ],
      "guards": [
        "G01",
        "G02",
        "G03",
        "G07",
        "G08",
        "G09",
        "G10"
      ],
      "decisions": [
        "Build surface (Copilot Studio engine vs Foundry workflow agent)",
        "Identity model (user-delegated vs Entra Agent ID)",
        "Skill granularity — default fine-grained (G02)",
        "Approval threshold — default confirm any record mutation (G09)"
      ],
      "evidence": "Agent Framework step/tool trace; Power Automate run history; Dataverse audit log; Entra agent-identity log."
    },
    "A3": {
      "title": "A3 · Workflow Orchestration Agent",
      "purpose": "Execute a declarative graph of steps with branching and human-in-the-loop, often realised through Power Automate flows.",
      "baseline": "Foundry workflow agent or Citadel spoke; Power-Automate-heavy flows inherit the CAF AI Ready / landing-zone perimeter.",
      "srcs": [
        "S3",
        "S18",
        "S19"
      ],
      "guards": [
        "G01",
        "G02",
        "G07",
        "G08",
        "G09",
        "G10"
      ],
      "decisions": [
        "Graph topology and HITL placement",
        "Identity model for background steps (Entra Agent ID)",
        "Per-step idempotency (WAF Reliability)",
        "Approval at every regulated state transition"
      ],
      "evidence": "Agent Framework / Foundry workflow trace; Power Automate run history; Dataverse audit; Entra log."
    },
    "A4": {
      "title": "A4 · Multi-Agent Coordinator",
      "purpose": "Decompose a goal across specialised agents and orchestrate them (sequential / concurrent / handoff / group-chat, incl. Magentic-One). CONCEPTUAL: a coordinator plus N specialist agents sharing a common world-model. LOGICAL: coordinator (A4) + research/analytic observers (A5) + workflow actuator (A3) and/or continuous monitor (A8), each with its own identity, budget and telemetry. PHYSICAL: Microsoft Agent Framework on Foundry hosted agents.",
      "baseline": "AAC Baseline Agentic AI Systems Architecture — hosted on Azure Container Apps or AKS.",
      "srcs": [
        "S6",
        "S23"
      ],
      "guards": [
        "G01",
        "G04",
        "G07",
        "G08",
        "G10"
      ],
      "decisions": [
        "Orchestration topology (handoff vs group-chat)",
        "Per-agent step + tool budget (G08)",
        "Inter-agent / A2A trust boundary (G07)",
        "Which sub-agents hold their own Entra Agent ID",
        "Composition recorded explicitly (not collapsed to one archetype)"
      ],
      "evidence": "Agent Framework handoff/group-chat telemetry with intent + payload logging."
    },
    "A5": {
      "title": "A5 · Research / Analytic Agent",
      "purpose": "Multi-hop retrieval and synthesis across federated heterogeneous sources, producing a cited answer.",
      "baseline": "AAC Baseline Agentic AI Systems (container-hosted) or Baseline Foundry Chat.",
      "srcs": [
        "S23",
        "S21"
      ],
      "guards": [
        "G01",
        "G02",
        "G04",
        "G06",
        "G08",
        "G10"
      ],
      "decisions": [
        "Sources in scope (each adds latency, cost, permission surface)",
        "Concept-level (Fabric IQ ontology) vs document-level reasoning",
        "Answer composition (brief + citations vs report)",
        "Refusal posture — surface disagreement when sources conflict"
      ],
      "evidence": "Foundry IQ sub-query log; Fabric IQ ontology query log; Agent Framework reasoning trace."
    },
    "A6": {
      "title": "A6 · Autonomous Operations Agent",
      "purpose": "Event/signal-triggered agent that runs without per-turn user prompts, authenticating with its own identity.",
      "baseline": "Foundry hosted agent + Entra Agent ID + Managed Identity, deployed as a Citadel spoke.",
      "srcs": [
        "S3",
        "S5",
        "S24"
      ],
      "guards": [
        "G01",
        "G02",
        "G03",
        "G05",
        "G08",
        "G10"
      ],
      "decisions": [
        "Trigger source (Event Grid / Service Bus / schedule)",
        "Autonomy bound and circuit breaker (G08)",
        "Code-execution sandbox scope (G05)",
        "Identity = Entra Agent ID, never a user token (G03)"
      ],
      "evidence": "Foundry agent traces; Entra agent-identity sign-in; Microsoft Sentinel correlation."
    },
    "A7": {
      "title": "A7 · Embedded Copilot Extension",
      "purpose": "Adds skills/knowledge to the host Copilot inside an M365 app surface (Word, Excel, Outlook, Teams).",
      "baseline": "Declarative agent inside Microsoft 365 Copilot — Microsoft-hosted, no separate runtime.",
      "srcs": [
        "S1"
      ],
      "guards": [
        "G01",
        "G06",
        "G10"
      ],
      "decisions": [
        "Host surface(s)",
        "Knowledge scope (declared corpus)",
        "Whether to graduate to a custom engine agent later"
      ],
      "evidence": "Microsoft 365 Copilot audit; Purview access audit."
    },
    "A8": {
      "title": "A8 · Continuous Monitor (Sentinel)",
      "purpose": "Always-on standing watch: senses and assesses continuously, emits advisories to a boundary channel, and never acts autonomously. Autonomy is decomposed — autonomous sensing/assessment, zero autonomous action. CONCEPTUAL: observe → fuse → assess → advise loop over a rolling world-model. LOGICAL: always-on agent grounded on real-time-pull + federated Knowledge, emitting to a boundary interface. PHYSICAL: Foundry hosted agent (always-on) + Agent Framework; Foundry IQ federated/MCP grounding.",
      "baseline": "Foundry hosted agent (always-on) + Agent Framework; real-time-pull grounding via Foundry IQ federated/MCP; advisory delivery via a traditional boundary interface (not an M4 component — see §9.3).",
      "srcs": [
        "S3",
        "S5",
        "S9"
      ],
      "guards": [
        "G01",
        "G08",
        "G10",
        "G11",
        "G12",
        "G13"
      ],
      "decisions": [
        "Trigger cadence / event source",
        "Corroboration threshold before raising tier (G13)",
        "Boundary interface for advisory delivery (traditional)",
        "Absence-as-state / liveness handling (G11)"
      ],
      "evidence": "Foundry agent traces; Foundry IQ real-time-pull logs; corroboration log; Entra agent-identity sign-in."
    }
  },
  "topologies": {
    "T1": {
      "name": "T1 · Inline",
      "desc": "The calling surface owns control flow. A single request and response, with no plan. Choose when the workflow is one step, or a few with no branching.",
      "base": "Baseline: AAC Basic Chat / production chat reference.",
      "families": "F2 inference, F6 identity, F7 control plane, F8 evaluation; F1 where the step retrieves.",
      "note": "Modifiers commonly: interactive trigger, human in-loop."
    },
    "T2": {
      "name": "T2 · Agent-orchestrated",
      "desc": "The agent owns a plan graph and calls tools. Choose when the workflow exists only because this agent runs it and nothing outside the AI estate would execute the graph.",
      "base": "Baseline: AAC Baseline Agentic AI Systems.",
      "families": "F1 (federated where sources exceed one), F2, F3 where concepts are named, F4 and F5 where a step commits, plus F6, F7, F8; F9 where influence reaches 2.",
      "note": "This is where budgets and circuit breakers (G08) sit, because the agent owns the plan."
    },
    "T3": {
      "name": "T3 · Platform-orchestrated",
      "desc": "A non-AI orchestrator outside CAFÉ's AI scope owns the workflow graph and invokes inference per step. The common case in an estate with an existing process portfolio.",
      "base": "Baseline: the incumbent platform's own release and deployment model.",
      "families": "F1, F2, F3, F9, F11, F12 in the AI estate; F4, F5, F10 and F13 resolve to the platform as declared boundary interfaces.",
      "note": "The canvas below is drawn agent-centric and cannot render this inversion — the highlight shows only the AI-estate components. Control flow, commits and outcome monitoring sit outside the frame."
    },
    "T4": {
      "name": "T4 · Delegated",
      "desc": "An agent routes to other agents, each owning its own sub-graph. Choose on ownership — different tool surfaces, data boundaries or owning teams — never merely because the graph is large.",
      "base": "Baseline: AAC Baseline Agentic AI Systems with an A2A channel.",
      "families": "F14 delegation plus the union of the families each sub-agent requires.",
      "note": "Carries G07: inter-agent channels are authenticated and handoffs logged with intent and payload."
    }
  },
  "topology_archetypes": {
    "T1": [
      "A1",
      "A7"
    ],
    "T2": [
      "A2",
      "A3",
      "A5"
    ],
    "T3": [
      "A8",
      "A2"
    ],
    "T4": [
      "A4"
    ]
  },
  "guardrail_origin": {
    "G01": "ASI01",
    "G02": "ASI02",
    "G03": "ASI03",
    "G04": "ASI04",
    "G05": "ASI05",
    "G06": "ASI06",
    "G07": "ASI07",
    "G08": "ASI08",
    "G09": "ASI09",
    "G10": "ASI10",
    "G11": "CAFÉ-AI",
    "G12": "CAFÉ-AI",
    "G13": "CAFÉ-AI"
  }
}
