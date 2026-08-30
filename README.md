# local-agent-lab

A local prototyping lab for **enterprise agentic solutions targeting Azure**, running entirely on an
M1 MacBook with 8 GB of RAM. It reproduces the *governance shape* of the target platform (AI Foundry +
Agent 365, Entra ID, APIM, Purview, Defender) with open-source and free-tier parts, so that every
prototype agent authenticates, egresses through a gateway, is metered, PII-scanned and traced — exactly
as it will in production. **Pattern parity, not feature parity.** Design: `Local-Agentic-Prototyping-Platform.docx`.

## What runs

| Local component | Stands in for | Role |
|---|---|---|
| LiteLLM gateway (`/v1`, `/mcp`) on Neon Postgres + Redis | APIM / AI Hub Gateway, Agent 365 | Single governance plane: teams, virtual keys, budgets, rate limits, per-team tool ACLs, skill registries |
| Ollama Cloud (no local models) | AI Foundry models | Cloud-only inference (`gpt-oss:120b`, `glm-5.3-flash`) |
| `adoit-mcp` (FastMCP, :9100) | APIM-fronted MCP tool | ArchiMate engine + ADOIT:CE facade; **gated write path** (request → human approval → status) |
| `semantic-mcp` (FastMCP, :9200) | shared knowledge tool | Semantic layer: vocabularies as data (ArchiMate 3.1 metamodel + exact relationship matrix; BA Guild capability reference models as SKOS), classification, legality, SPARQL, traceability questions |
| Architecture review app (Streamlit, :8501) + Telegram channel (plumbing) | approval workflow | Human-in-the-loop over Redis Streams events: approve / request changes / decline |
| Jaeger v2 (native binary, :16686) + OpenTelemetry | Foundry observability / audit trail | One trace per workflow run across agent → gateway → MCP servers |
| `archimate-adoit` skill (`.claude/skills/`) | agent capability | Deterministic ArchiMate layout engine (orthogonal parallel routing, layer bands, per-type notation) → ADOIT-importable Model Exchange XML; registered in LiteLLM's skill store and Skill Hub |

## Quick start

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install "litellm[proxy]" fastmcp prisma rdflib owlrl openpyxl streamlit \
  opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-instrumentation-asgi opentelemetry-instrumentation-urllib
cp .env.example .env            # then fill in the keys (see below)
./lab.sh up                     # redis, jaeger, adoit-mcp, semantic-mcp, gateway, review app
./lab.sh status | down | review
```

`.env` keys: `OLLAMA_API_KEY`, `ADOIT_USERNAME`/`ADOIT_PASSWORD`/`ADOIT_BASE_URL`/`ADOIT_REPO_ID`,
`LITELLM_MASTER_KEY`, `DATABASE_URL` (Neon), `REDIS_HOST`/`REDIS_PORT`, `OTEL_*`, `EA_AGENT_KEY`
(minted by `gateway/bootstrap_registry.py`), `ARCHIMATE_SKILL_ID` (set by `gateway/register_skill.sh`).
Jaeger: download the `jaeger-2.x-darwin-arm64` release into `tools/jaeger/`. Services are launched with
`env -u ANTHROPIC_API_KEY` — ambient shell credentials never reach the governance plane.

- Registry UI: http://127.0.0.1:4000/ui (user `admin`, password = master key)
- Traces: http://127.0.0.1:16686 · Review app: http://127.0.0.1:8501

## The end-to-end agent path

```bash
.venv/bin/python architecture/lab_model.py          # author the lab's own architecture (85 elements, 11 views)
.venv/bin/python architecture/run_via_gateway.py    # agent key -> gateway -> semantic validate/load/ask ->
                                                    # render (XML + SVG) -> approval request
.venv/bin/python architecture/export_capabilities.py healthcare-provider-v2.0 "Patient Management" 3
                                                    # reference capability subtree -> ADOIT-ready model -> approval
```

Every run is one trace (`process-ea-modelling` → `litellm-gateway` → `adoit-mcp` / `semantic-mcp`),
metered against the agent's virtual key and rolled up to its team, and ends in the review app where a
human approves the write into the EA repository (ADOIT:CE imports via its UI; a full tenant will use REST).

## Repository layout

```
.claude/skills/archimate-adoit/   the skill: engine, notation, references (method, layout rules, ADOIT import)
semantic/                         semantic layer: ontology core, ArchiMate vocabulary, SKOS schemes, RDF, questions
mcp/adoit_mcp, mcp/semantic_mcp   the two MCP servers
gateway/                          litellm-config.yaml, registry bootstrap, skill registration
shared/approvals.py               Redis Streams approval events (+ CLI channel)
review/app.py, channels/          approval channels (Streamlit; Telegram plumbing)
architecture/                     lab model generator, gateway clients, generated out/ (git-ignored)
lab.sh                            up | down | status | review
CLAUDE.md                         the operating rules and invariants (read this first)
```

## Architectural invariants

All traffic through the gateway · one team per business process, one virtual key per agent · every MCP
server and skill registered in LiteLLM · no unredacted PII past the egress boundary · cloud-only inference
· destructive/write tools require human approval · every process has its own OTel service name ·
models validated against the full ArchiMate relationship matrix before they reach a reviewer.

## Status

Scaffolded and working end to end (Aug 2026): governance plane with real keys/budgets/ACLs, both MCP
servers, skill registries, approvals, observability, semantic layer with two reference models. Not yet:
Presidio PII middleware, guardrails, Entra app registrations, Agent Framework workflow hosts, A2A.
