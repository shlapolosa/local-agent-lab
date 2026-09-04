# local-agent-lab

A local prototyping lab for **enterprise agentic solutions targeting Azure**, running entirely on an
M1 MacBook with 8 GB of RAM. It reproduces the *governance shape* of the target platform (AI Foundry +
Agent 365, Entra ID, APIM, Purview, Defender) with open-source and free-tier parts, so that every
prototype agent authenticates, egresses through a gateway, is metered, PII-scanned and traced — exactly
as it will in production. **Pattern parity, not feature parity.** Design: `docs/Local-Agentic-Prototyping-Platform.docx`.

## What runs

| Local component | Stands in for | Role |
|---|---|---|
| LiteLLM gateway (`/v1`, `/mcp`) on Neon Postgres + Redis | APIM / AI Hub Gateway, Agent 365 | Single governance plane: teams, virtual keys, budgets, rate limits, per-team tool ACLs, skill registries |
| Ollama Cloud (no local models) | AI Foundry models | Cloud-only inference (`gpt-oss:120b`, `glm-5.3-flash`) |
| `adoit-mcp` (FastMCP, :9100) | APIM-fronted MCP tool | ArchiMate engine + ADOIT:CE facade; **gated write path** (request → human approval → status) |
| `semantic-mcp` (FastMCP, :9200) | shared knowledge tool | Semantic layer: vocabularies as data (ArchiMate 3.1 metamodel + exact relationship matrix; BA Guild capability reference models as SKOS), classification, legality, SPARQL, traceability questions |
| Architecture review app (Streamlit, :8501) + Telegram channel (plumbing) | approval workflow | Human-in-the-loop over Redis Streams events: approve / request changes / decline |
| Jaeger v2 (native binary, :16686) + OpenTelemetry | Foundry observability / audit trail | One trace per workflow run across agent → gateway → MCP servers |
| `archimate-adoit` skill (`skills/`) | agent capability | Deterministic ArchiMate layout engine (orthogonal parallel routing, layer bands, per-type notation) → ADOIT-importable Model Exchange XML; registered in LiteLLM's skill store and Skill Hub |
| Developer model serving + Entra identity (`config/clients/`, `src/lab/substrate/gateway/custom_auth.py`) | APIM + Developer Portal | Both API standards (OpenAI `/v1`, Anthropic `/v1/messages`), full catalogue + `auto` router, reversible-PII guardrail; sign-in with Entra as a short-lived JWT (`az`, → APIM `validate-jwt`) or a durable self-serve key (browser SSO, → APIM subscription key); per-developer keys and spend |

## Quick start

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r deploy/requirements.txt -e . -r deploy/requirements-dev.txt   # runtime + the lab package + pytest
cp .env.example .env            # then fill in the keys (see below)
./lab.sh up                     # redis, jaeger, adoit-mcp, semantic-mcp, gateway, review app
./lab.sh status | down | review
```

`.env` keys: `OLLAMA_API_KEY`, `ADOIT_USERNAME`/`ADOIT_PASSWORD`/`ADOIT_BASE_URL`/`ADOIT_REPO_ID`,
`LITELLM_MASTER_KEY`, `DATABASE_URL` (Neon), `REDIS_HOST`/`REDIS_PORT`, `OTEL_*`, `EA_AGENT_KEY`
(minted by `scripts/bootstrap_registry.py`), `ARCHIMATE_SKILL_ID` (set by `scripts/register_skill.sh`).
Jaeger: download the `jaeger-2.x-darwin-arm64` release into `var/tools/jaeger/`. Services are launched with
`env -u ANTHROPIC_API_KEY` — ambient shell credentials never reach the governance plane.

- Registry UI: http://127.0.0.1:4000/ui (user `admin`, password = master key)
- Traces: http://127.0.0.1:16686 · Review app: http://127.0.0.1:8501

## The end-to-end agent path

```bash
.venv/bin/python scripts/lab_model.py          # author the lab's own architecture (85 elements, 11 views)
.venv/bin/python scripts/run_via_gateway.py    # agent key -> gateway -> semantic validate/load/ask ->
                                                    # render (XML + SVG) -> approval request
.venv/bin/python scripts/export_capabilities.py healthcare-provider-v2.0 "Patient Management" 3
                                                    # reference capability subtree -> ADOIT-ready model -> approval
```

Every run is one trace (`process-ea-modelling` → `litellm-gateway` → `adoit-mcp` / `semantic-mcp`),
metered against the agent's virtual key and rolled up to its team, and ends in the review app where a
human approves the write into the EA repository (ADOIT:CE imports via its UI; a full tenant will use REST).

## Repository layout

```
src/lab/core/          domain: archimate/ (layout engine, notation, relation repair, XSD), semantic/ (vocabularies, SKOS, RDF, questions), visio/ parsers, canon
src/lab/platform/      kernel shared by every tier: config, DI container, otel, redis_client, runlog, workflows, docparse, locks
src/lab/substrate/     the shared plane: gateway hooks, mcp/{adoit,semantic,storage} servers, review app + uploads, channels, approvals, artifacts
src/lab/workloads/     business-process hosts (visio_to_archimate: host, consumer, DevUI, workflow, agents), identity, accumulators
skills/                the skills (SKILL.md, references, thin script wrappers over lab.core); .claude/skills/<n> symlink here
config/                litellm-config.yaml, clients/ templates, jaeger-railway.yaml
scripts/               provisioning, registry bootstrap, register_skill.sh, architecture generators, e2e smoke, spikes/
deploy/                Dockerfile, railway.py, requirements, substrate + workload compose files
tests/                 unit/<mirror of src/lab> · integration/ · governance/ · deploy/ · fixtures/   (tests/run.sh [--cov])
var/  (git-ignored)    logs, pids, artifacts, outputs, inputs, tools, coverage, licensed reference sources
lab.sh                 up | down | status | review | consumer | channels | clients
CLAUDE.md              the operating rules and invariants (read this first)
```

Tier rule: `core` ← `platform` ← {`substrate` | `workloads`}; workloads never import the substrate (they reach it over
the network only — the Container Apps → APIM seam), enforced by `tests/governance/test_import_boundaries.py`.

## Architectural invariants

All traffic through the gateway · one team per business process, one virtual key per agent · every MCP
server and skill registered in LiteLLM · no unredacted PII past the egress boundary · cloud-only inference
· destructive/write tools require human approval · every process has its own OTel service name ·
models validated against the full ArchiMate relationship matrix before they reach a reviewer.

## Client support & limitations

Any client reaches the gateway with an Entra credential — see `config/clients/`. Two shapes, both
portable to APIM (`validate-jwt` / subscription key):

| Client | How it authenticates | Notes |
|---|---|---|
| Claude Code CLI, Claude **VS Code** extension | Entra JWT via `az` (apiKeyHelper) or a durable key | `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` lists the full catalogue in `/model`; non-Claude models are best-effort for agentic tool-use, first-class for chat |
| Paste-only IDEs — Windsurf, Cline, Continue, JetBrains AI | durable key from browser SSO (`<gateway>/ui`) | no CLI, no `az`, no refresh |
| OpenAI-standard tools (Cursor, Continue, SDKs), curl, CI | JWT or durable key | `OPENAI_BASE_URL=<gateway>/v1` |

**Not supported:**
- **Claude Desktop and Claude on the web (claude.ai)** cannot be pointed at a custom gateway —
  they talk only to Anthropic's own endpoints, so they can't be routed through LiteLLM/APIM,
  metered per developer, or PII-guarded. Use the Claude Code CLI/VS Code extension or an
  OpenAI/Anthropic-compatible client instead.
- Claude Code's `/login` cannot target a third-party OIDC provider; Entra login is via the
  credential shapes above, not the `/login` menu.

## Status

Working end to end (Aug 2026): governance plane with real keys/budgets/ACLs on Neon + Redis Cloud;
both MCP servers; skill registries; approvals; observability (Jaeger on Railway); semantic layer with
two reference models; **Entra identity** (app registrations, agents via MSAL client-credentials,
developers via JWT/`az` and durable self-serve SSO keys, gateway JWT validation = APIM `validate-jwt`);
**reversible PII pseudonymization** guardrail on both API standards; `auto` intent router.

Not yet: LLM-judge output guardrails (Defender analogue), Presidio NER tier (names/free-text clinical
PII, beyond the regex tier), Agent Framework workflow hosts, A2A, and the containerised cloud/APIM
deployment (`deploy/`).
