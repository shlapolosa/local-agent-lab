# Foundry UAE North tracker coverage

**Artifact:** foundry_coverage
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| tab | foundry_capability | stage | uae_north_status | level | l3_ids |
|---|---|---|---|---|---|
| Build Surfaces & Dev Tools | Foundry portal | GA | Yes | green | COG.27 |
| Build Surfaces & Dev Tools | Playgrounds | GA | Yes | green | COG.27 |
| Build Surfaces & Dev Tools | Microsoft Foundry SDKs | GA | Yes | green | COG.03 |
| Build Surfaces & Dev Tools | Azure Developer CLI (azd) extensions | GA | Yes | green | COG.03 |
| Build Surfaces & Dev Tools | Visual Studio Code extension | GA | Yes | green | COG.03 |
| Build Surfaces & Dev Tools | Foundry Agent Canvas | GA | Yes | green | COG.27 |
| Build Surfaces & Dev Tools | Coding agent integration (MCP) | GA | Yes | green | COG.17 |
| Build Surfaces & Dev Tools | Templates and samples | GA | Yes — not region-bound (tooling, works from any region) | green | XCT.08 |
| Build Surfaces & Dev Tools | LangChain and LangGraph integration | GA | Yes — not region-bound (tooling, works from any region) | green | COG.03 |
| Models | Foundry Models catalog | GA | Yes — see UAE North Models tab | green | MOD.01; COG.13 |
| Models | Model deployment | GA | Yes | green | MOD.06 |
| Models | Deployment types (Standard/Global/Data Zone/PTU/Batch/Priority) | GA (mixed by type) | Yes — uneven, see UAE North Models tab | amber | MOD.06; COG.14 |
| Models | Managed compute | Preview | Partial — public preview, Global deployment scope only (GlobalManagedCompute SKU). GPU inference is not pinned to UAE North even when the Foundry project is; Data Zone and additional region scopes are described as rolling out but are not live yet. | amber | COG.14 |
| Models | Instant access models | Preview | Preview — regional availability not separately published by Microsoft; confirm current status with your Microsoft account team. | amber | COG.13 |
| Models | Model router | GA | Follows Global Standard availability | amber | COG.23 |
| Models | Model benchmarks and leaderboards | GA | Yes — not region-bound (portal feature, works from any region) | green | MOD.01 |
| Models | Fine-tuning | GA/Preview (mixed) | Not available in UAE North — see Gaps tab | red | MOD.03; MOD.02 |
| Models | Model versions and lifecycle | GA | Yes | green | MOD.08; MOD.05 |
| Models | Healthcare AI models | Preview | Preview — regional availability not separately published; healthcare AI models typically ship to a narrower region set. Confirm with your Microsoft account team. | amber | MOD.01 |
| Models | Hugging Face models | GA | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | COG.14 |
| Models | Quotas and region availability | GA | Yes — reference doc itself | green | MOD.06 |
| Models | Fireworks on Foundry (preview) | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | COG.13 |
| Agents | Foundry Agent Service | GA | Yes — GA in UAE North | green | COG.02 |
| Agents | Prompt agents | GA | Yes | green | COG.02 |
| Agents | Hosted agents | GA | Yes | green | COG.02; TEC.07 |
| Agents | Agent development lifecycle | GA | Yes (process, not regional) | green | COG.28 |
| Agents | Agent identity | GA | Yes (Entra is global) | green | COG.06 |
| Agents | Workflows | GA | Yes | green | COG.04 |
| Agents | Routines | GA | Yes | green | BUS.03 |
| Agents | Agent-to-agent (A2A) | GA (v1.0) / Preview (v0.3) | Yes | green | COG.18; BND.03 |
| Agents | Responses API | GA | Yes | green | COG.05 |
| Agents | Voice agents | Preview | Partial — Voice Live is now listed for uaenorth, but only with cascaded text models (gpt-4o, gpt-4.1, gpt-5.x family) on Global Standard. No native speech-to-speech realtime models (azure-realtime, gpt-realtime*) and Foundry Agent support is not marked for uaenorth. Global Standard means inference can run outside the UAE. For full realtime + agent support, nearest regions are Sweden Central, West Europe, East US 2, Southeast Asia. | amber | COG.15 |
| Agents | Microsoft Agent 365 integration | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | COG.07 |
| Agents | CI/CD for agents | GA | Yes (pipeline, not regional) | green | COG.28 |
| Agents | Agent debugging tools (Inspector) | GA | Yes | green | COG.28 |
| Tools | Tool catalog | GA | Yes | green | TEC.16 |
| Tools | Function calling | GA | Yes | green | APP.08 |
| Tools | Code interpreter | GA | Yes | green | TEC.13 |
| Tools | File search | GA | Yes | green | KNW.04 |
| Tools | Web search and Grounding with Bing | GA | Yes — UAE North on Bing Grounding region list | green | KNW.14 |
| Tools | Browser automation | Preview | Available — confirmed on the Foundry Agent Service regional tool matrix (Browser Automation = yes for UAE North). | amber | APP.05 |
| Tools | Computer use | Preview | Not available — confirmed via Agent Service regional tool matrix (Computer Use is 'no' for UAE North specifically; only available in a handful of regions like Canada Central, Central US, East US 2, Japan West, South India, Sweden Central, Switzerland West, West Central US, West Europe). | red | APP.04 |
| Tools | Image generation | Preview | Yes — image models listed in UAE North Global Standard | amber | COG.22 |
| Tools | OpenAPI tool | GA | Yes | green | APP.08; KNW.05 |
| Tools | Model Context Protocol (MCP) | GA | Yes | green | KNW.06; BND.01 |
| Tools | Azure Functions | GA | Yes | green | APP.08 |
| Tools | SharePoint and Fabric connectors | Preview | Available — the Fabric Data Agent and SharePoint tools both show yes for UAE North on the Foundry Agent Service regional tool matrix. | amber | KNW.04; KNW.07 |
| Tools | Toolbox | GA | Yes | green | TEC.16 |
| Tools | Skills | Preview | Preview — portal/SDK packaging feature for existing tools; not separately region-gated. | amber | BUS.03; BND.02 |
| Tools | Foundry Tools: Speech, Language, Translator | GA | Yes (Azure AI Services regional) | green | COG.16; COG.21; KNW.11 |
| Knowledge & Retrieval | Retrieval-augmented generation (RAG) | GA | Yes | green | KNW.01 |
| Knowledge & Retrieval | Azure AI Search integration | GA | Yes — full feature parity in UAE North | green | KNW.03; KNW.09 |
| Knowledge & Retrieval | Vector stores | GA | Yes | green | KNW.03 |
| Knowledge & Retrieval | Foundry IQ | GA/Preview (mixed) | Yes (rides on AI Search) | amber | KNW.01 |
| Knowledge & Retrieval | Fabric IQ | Preview | Likely available — rides on the Fabric Data Agent tool, which is available in UAE North. Fabric IQ itself is still preview; confirm with your Microsoft account team before committing. | amber | SEM.01; KNW.10 |
| Knowledge & Retrieval | Work IQ | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | KNW.02 |
| Knowledge & Retrieval | Memory | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | DAT.06 |
| Observability | Foundry Observability | GA | Yes | green | TEC.10 |
| Observability | Tracing | GA | Yes | green | TEC.10 |
| Observability | Agent monitoring dashboard | GA | Yes | green | TEC.10 |
| Observability | Model deployment monitoring | GA | Yes | green | MOD.07 |
| Observability | End-user feedback logging | GA | Yes | green | COG.32 |
| Observability | Notification Center | GA | Yes (portal feature) | green | TEC.10 |
| Observability | External agent registration | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | XCT.06 |
| Observability | Diagnostic logging | GA | Yes (Azure Monitor is region-ubiquitous) | green | DAT.08 |
| Evaluation & Optimization | Evaluations | GA | Yes — UAE North explicitly listed for evaluation API | green | COG.12 |
| Evaluation & Optimization | Built-in evaluators | GA | Yes | green | COG.12 |
| Evaluation & Optimization | Custom evaluators | GA | Yes | green | COG.12; XCT.20 |
| Evaluation & Optimization | Agent evaluation | GA | Partial — core agent trace evaluation via the Evaluation API works in-region, but 'Agent playground evaluations' specifically are not on the UAE North region list (only ~15 US/EU regions). | amber | COG.12 |
| Evaluation & Optimization | Continuous evaluation | GA | Yes | green | COG.26 |
| Evaluation & Optimization | Evaluation datasets | GA | Yes | green | DAT.09 |
| Evaluation & Optimization | Human evaluation | GA | Yes | green | COG.31 |
| Evaluation & Optimization | Prompt optimizer | GA | Yes | green | COG.33 |
| Evaluation & Optimization | Agent optimizer | Preview | Preview — regional availability not separately published; confirm current status with your Microsoft account team. | amber | COG.33 |
| Evaluation & Optimization | AI red teaming | GA | Not available — only East US 2 and North Central US support AI red teaming; must run cross-region. | red | COG.19 |
| Evaluation & Optimization | Evaluations in CI/CD | GA | Yes (pipeline, not regional) | green | COG.12; COG.28 |
| Trust & Safety | Guardrails and controls | GA (mixed) | Partial — see Gaps tab (no Groundedness/Multimodal in UAE North) | amber | COG.20 |
| Trust & Safety | Custom filtering | GA (mixed) | Partial — Custom Category (standard) not in UAE North | amber | COG.20 |
| Trust & Safety | Task adherence | GA | Yes — available via Global, US-Datazone, or EU-Datazone routing (not purely in-region), per the Guardrails region table. | amber | COG.30 |
| Trust & Safety | Guided Guardrail | Preview | Yes (portal setup experience for Guardrails; not separately region-gated). | amber | COG.20 |
| Trust & Safety | Third-party guardrail integrations | GA | Preview — regional availability depends on the specific partner integration; confirm with your Microsoft account team. | amber | COG.10 |
| Trust & Safety | Responsible AI transparency notes | GA | Yes (documentation) | green | XCT.14; RCV.05 |
| Trust & Safety | Customer Copyright Commitment | GA | Yes (contractual, not regional) | green | RCV.05 |
| Manage, Secure & Govern | Foundry resources and projects | GA | Yes | green | XCT.05 |
| Manage, Secure & Govern | Foundry control plane | GA | Yes | green | COG.07; XCT.05 |
| Manage, Secure & Govern | Fleet monitoring | GA | Yes | green | COG.07 |
| Manage, Secure & Govern | Token limit enforcement | GA | Yes | green | TEC.02; DAT.05 |
| Manage, Secure & Govern | AI gateway integration (APIM) | GA/Preview (mixed) | Partial — only APIM Basic v2/Standard v2 in UAE North, no Premium v2 | amber | TEC.02 |
| Manage, Secure & Govern | Role-based access control (RBAC) | GA | Yes (Entra RBAC is global) | green | TEC.09 |
| Manage, Secure & Govern | Keyless authentication | GA | Yes | green | TEC.09 |
| Manage, Secure & Govern | Network isolation | GA | Yes | green | TEC.04 |
| Manage, Secure & Govern | Customer-managed keys | GA | Yes | green | TEC.18 |
| Manage, Secure & Govern | Azure Policy support | GA | Yes | green | TEC.19 |
| Manage, Secure & Govern | Cost management | GA | Yes | green | TEC.21 |
| Manage, Secure & Govern | High availability and disaster recovery | GA | Partial — UAE North has no paired region for AZ-level DR; verify design | amber | TEC.22 |
| Manage, Secure & Govern | Infrastructure as code | GA | Yes | green | XCT.04 |
| Manage, Secure & Govern | Azure Government support | GA | No — Azure Government is a separate US sovereign cloud (US Gov Virginia / US Gov Arizona); not applicable to UAE North, which is commercial cloud. | red | XCT.16 |
| APIs & SDKs | Foundry API reference | GA | Yes (documentation) | green | COG.03 |
| APIs & SDKs | Foundry Models endpoints | GA | Yes | green | COG.13 |
| APIs & SDKs | Foundry v1 REST API | GA | Yes (fine-tuning ops themselves not regional to UAE North) | green | COG.13; MOD.03 |
| APIs & SDKs | Resource management API | GA | Yes | green | XCT.04 |
| Voice & Speech | Real-time transcription |  | Available | green | COG.16 |
| Voice & Speech | Batch transcription |  | Available | green | COG.16 |
| Voice & Speech | Fast transcription |  | Not available | red | COG.16 |
| Voice & Speech | Whisper (via batch transcription or Azure OpenAI) |  | Not available | red | COG.16 |
| Voice & Speech | Custom speech training |  | Partial | amber | MOD.03 |
| Voice & Speech | Post-stream refinement (mono / multilingual) |  | Not available | red | COG.16 |
| Voice & Speech | LLM speech (transcribe / translate, MAI-Transcribe) |  | Not available | red | COG.16 |
| Voice & Speech | Neural text to speech (standard voices) |  | Available | green | COG.16 |
| Voice & Speech | Batch synthesis API |  | Available | green | COG.16 |
| Voice & Speech | HD voices |  | Not available | red | COG.16 |
| Voice & Speech | MAI voices |  | Not available | red | COG.16 |
| Voice & Speech | Azure OpenAI voices |  | Not available | red | COG.16 |
| Voice & Speech | Custom voice (professional) — hosting |  | Partial | amber | COG.16; MOD.03 |
| Voice & Speech | Personal voice |  | Not available | red | MOD.03 |
| Voice & Speech | Voice conversion |  | Not available | red | COG.16 |
| Voice & Speech | Text to speech avatar (real-time and batch) |  | Not available | red | COG.22 |
| Voice & Speech | Custom avatar (video / photo) and voice sync |  | Not available | red | COG.22 |
| Voice & Speech | Real-time speech translation |  | Available | green | COG.21 |
| Voice & Speech | Video translation |  | Not available | red | COG.21 |
| Voice & Speech | Live interpreter |  | Not available | red | COG.21 |
| Voice & Speech | Voice Live — cascaded models (GPT-4o, 4.1, 5.x) |  | Partial | amber | COG.15 |
| Voice & Speech | Voice Live — native realtime models (azure-realtime, gpt-realtime*) |  | Not available | red | COG.15 |
| Voice & Speech | Voice Live — Foundry Agent support |  | Not available | red | COG.15 |
| Voice & Speech | Speech MCP server (agent tool) |  | Available | green | COG.16 |
| Voice & Speech | Keyword recognition (advanced models / verification) |  | Not available | red | COG.16 |
