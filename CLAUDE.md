# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A local prototyping lab for enterprise agentic solutions targeting Azure, run entirely on an M1 MacBook with 8 GB RAM. The authoritative design is `Local-Agentic-Prototyping-Platform.docx` (DOH Abu Dhabi EA, Draft v0.3) — read it before making architectural changes.

The goal is **pattern parity with Azure, not feature parity**: every prototype agent authenticates, egresses through a gateway, is metered, is PII-scanned, and is traced — exactly as in production. Application code uses the **Microsoft Agent Framework** so solutions migrate to Azure (Container Apps + APIM + AI Foundry) without rework.

## Service Mapping (local analogue → Azure target)

| Local component | Stands in for | Role |
|---|---|---|
| LiteLLM Proxy (`/v1`, `/mcp`, A2A) | APIM / AI Hub Gateway | Single governance plane: virtual keys, budgets, rate limits, tool ACLs |
| Ollama Cloud (primary) + ~2B local Ollama (offline fallback) | AI Foundry models | Cloud-first inference |
| One Python host process per workflow | Azure Container Apps | Agent hosting (~100 MB per idle async host) |
| LiteLLM teams/keys + Entra app registrations + A2A agent cards | Agent 365 | Agent registry & governance |
| Entra ID free tenant (real, via MSAL) | Entra ID | Identity; one app registration per agent; no local IdP |
| Microsoft Presidio middleware + OTel trace audit | Purview | PII detect/redact on prompts, tool args, results |
| Guardrails middleware + cloud LLM-judge | Defender for AI | Prompt-injection & output scanning |
| OpenTelemetry → Jaeger (Colima VM) | Foundry observability | Trace tree per workflow run; doubles as audit trail |

## Architectural Invariants

These rules define the lab; do not violate them when adding code:

- **All traffic through the gateway.** LLM calls, MCP tool calls, and agent-to-agent (A2A) calls all route through the single LiteLLM proxy — never point-to-point, and agents never hold tool credentials (the gateway injects upstream credentials).
- **One LiteLLM team per business process; one virtual key per agent.** Each key pairs 1:1 with an Entra app registration and an A2A agent card.
- **No unredacted PII crosses the egress trust boundary.** Presidio middleware scans prompts, tool arguments, and tool results before anything leaves the machine.
- **Cloud-only inference.** All inference goes to Ollama Cloud — no local models at all (decision Aug 2026, superseding the doc's ~2B offline-fallback idea). The 8 GB budget depends on this. Keep local components in the ~100–300 MB range each.
- **Shared tools are MCP servers over streamable HTTP, registered with the gateway.** Stdio MCP servers are allowed only as local dev sandboxes — they bypass governance and must never migrate.
- **Destructive/write tools require human approval** via the workflow engine's approval gate.
- **Every workflow host sets a distinct OTel service name** (e.g. `process-1-intake`) so concurrent processes can be traced and audited independently.
- **Every MCP server and every skill is registered in LiteLLM — no exceptions.** An MCP server
  goes into `gateway/litellm-config.yaml` `mcp_servers` (and is granted to teams via
  `object_permission.mcp_servers`); a skill goes into BOTH LiteLLM skill registries via
  `gateway/register_skill.sh <team_id>` — the runtime store (`/v1/skills`, agents consume it
  via `container.skills`) and the Skill Hub (UI → Skills / `claude-code/marketplace.json`,
  discovery). A tool or skill that exists only on disk is ungoverned and invisible to the
  registry; register it in the same change that creates it, and re-register after edits.

## Runtime Model

Business processes are Agent Framework **Workflows** — typed graphs orchestrating ChatAgents and deterministic functions (sequential, concurrent, handoff patterns; checkpointing; human-in-the-loop pauses). A shared services layer provides the workflow engine, the middleware chain (Presidio → approval gates → OTel emission), and MCP/A2A client integrations.

## ADOIT MCP Server (own-built)

The ADOIT EA integration wraps the ADOIT REST API (Community Edition has no built-in MCP), built on the existing internal Python ArchiMate library (61 element types, role-based architect agents). FastMCP exposes typed create/read/update tools; validation runs against the library before any repository write. Read/query tools may be shared across processes; write tools are ACL-restricted to a dedicated EA Modeling Agent. ADOIT credentials live in `.env` (`ADOIT_USERNAME`/`ADOIT_PASSWORD`, plus `ADOIT_BASE_URL` and `ADOIT_REPO_ID`), alongside `OLLAMA_API_KEY`.

Verified against the live CE tenant (Aug 2026): Basic auth works against `GET {ADOIT_BASE_URL}/rest/2.0/repos` (returns the user's repository), but deeper REST 2.0 endpoints (`/objects` search, `/models`) return 403/"service not present" — the full REST module appears disabled on Community Edition. Expect to work within this limited surface or via the browser-facing API until a full ADOIT 18 tenant is available.

## Architecture Modelling

Use the project skill `archimate-adoit` (`.claude/skills/archimate-adoit/`) for all ArchiMate
modelling and ADOIT export: it bundles a deterministic layout engine (orthogonal parallel
routing, layer bands, interfaces as icons), the ArchiMate 3.1 vocabulary, and the ADOIT:CE
import procedure. Keep generator scripts under `architecture/` so views are regenerable.
The engine originates from `~/Development/health-service-idp` (archi_layout.py / drawio_c4.py).

## Current State & Build Order

The repo is not yet scaffolded. Planned sequence (from the design doc):

1. Scaffold: Colima + Jaeger compose file, LiteLLM config (models, MCP registry, teams/keys), first workflow host with middleware chain wired.
2. Build the ADOIT MCP server: evaluate the `archimate-mcp` PyPI package as the base, extend it with the ADOIT facade and the skill's layout engine; register with the gateway; validate create/update round-trips against ADOIT:CE.
3. Implement two pilot business processes end to end; demonstrate concurrent runs with per-process traces and spend rollups.
4. Evaluate ADOIT 18 built-in MCP (read/query only) if a full tenant is obtained; writes stay on the own-built server.

## Commands

Everything runs from the project venv (Python 3.12 — litellm needs ≥3.11; never pip install --user):

```bash
./lab.sh up | down | status                      # THE way to run the stack: redis, adoit-mcp, gateway
                                                 # (waits for health, strips ambient creds, logs/ + .lab/ pids)
# individual pieces, if ever needed:
set -a && source .env && set +a                  # all services need the env
.venv/bin/python mcp/adoit_mcp/server.py         # adoit-mcp (port 9100, /mcp)
env -u ANTHROPIC_API_KEY .venv/bin/litellm --config gateway/litellm-config.yaml --port 4000   # gateway (no ambient creds)
.venv/bin/python architecture/lab_model.py       # regenerate lab_model.json spec
.venv/bin/python architecture/run_via_gateway.py # agent path: validate+render via gateway
```

Outputs land in `architecture/out/` (`lab-architecture.archimate.xml` + one SVG per view).
Element ids in `lab_model.py` are stable on purpose — changing them duplicates objects on
ADOIT re-import.

## Gateway Registry (Agent 365 analogue)

LiteLLM's key store is **Neon Postgres** (serverless, cloud — no local pg, no Colima container;
`DATABASE_URL` + `NEON_*` in `.env`; dedicated `litellm` database/role inside the shared
`click-stream` project). Prisma client must be generated once per venv:
`PATH=.venv/bin:$PATH .venv/bin/prisma generate --schema .venv/lib/python3.12/site-packages/litellm_proxy_extras/schema.prisma`.

- **Master key** (`LITELLM_MASTER_KEY`) = admin plane only: minting teams/keys, the UI. Never
  used by agents.
- **Team per business process, virtual key per agent** — `gateway/bootstrap_registry.py`
  created team `ea-modelling` and key alias `ea-modeling-agent` (`EA_AGENT_KEY` in `.env`,
  2 USD/30d, 30 rpm, 60k tpm). MCP access is granted per team:
  `POST /team/update {"object_permission":{"mcp_servers":["adoit_mcp"]}}` — a key with no grant
  sees zero tools (verified). Per-tool ACLs use `mcp_tool_permissions` on the same object.
- **Metering**: Ollama Cloud is flat-rate, so `litellm-config.yaml` carries nominal per-token
  prices; every call returns `x-litellm-response-cost` and spend rolls up key → team.
- **Redis** (Homebrew, already resident on `127.0.0.1:6379`, `REDIS_HOST/PORT` in `.env`) backs
  limiter/budget/router state via `litellm_settings.cache` with `supported_call_types: []` —
  LLM responses are never cached. Verify with `redis-cli --scan` (keys `spend:team:*`,
  `{api_key:...}:window`) and `GET /cache/ping`.
- **Registry UI**: http://127.0.0.1:4000/ui (user `admin`, password = master key) — teams,
  keys, spend, models, MCP servers. API: `/team/info`, `/key/info`, `/key/list`.

- **Skill catalogue**: the `archimate-adoit` skill is registered in LiteLLM's skills store
  (`ARCHIMATE_SKILL_ID` in `.env`; UI → Skills). Agents pull it by passing
  `container={"skills":[{"skill_id": ...}]}` — the gateway injects SKILL.md into the system
  prompt. Re-register after editing the skill: zip `.claude/skills/archimate-adoit` and
  `POST /v1/skills?beta=true -F custom_llm_provider=litellm_proxy -F display_title=archimate-adoit -F "files[]=@skill.zip"`
  — **`custom_llm_provider=litellm_proxy` is mandatory**: without it LiteLLM forwards the upload
  to Anthropic's cloud skill store (ids `skill_…` instead of `litellm_skill_…`). Use
  `gateway/register_skill.sh <team_id>` — it also sets ownership to `team:<id>` (the injection
  hook only serves skills whose `created_by` is in the caller's scopes; admin-created skills are
  invisible to agent keys) and updates `.env`. Restart the gateway afterwards (60 s skill cache).
  LiteLLM has TWO skill registries: (a) `/v1/skills` runtime store above — what agents
  consume via `container.skills`; (b) the **Skill Hub** (UI → Skills, served as
  `/claude-code/marketplace.json`, API `/claude-code/plugins`) — discovery for people and
  Claude Code clients. `register_skill.sh` maintains both. The Hub needs a git source with a
  dot-free path, hence the `skills/archimate-adoit -> .claude/skills/archimate-adoit` symlink;
  the source is the GitHub remote (`https://github.com/shlapolosa/local-agent-lab.git`,
  derived from `origin` by `register_skill.sh`; local `file://` only when no remote). Clients add
  it with `claude plugin marketplace add http://127.0.0.1:4000/claude-code/marketplace.json`.
- **Ambient credentials**: the user's shell exports `ANTHROPIC_API_KEY`; the gateway must NOT
  inherit it (that is how the skill upload leaked to Anthropic once). Launch services with
  `env -u ANTHROPIC_API_KEY` — only `.env` values are lab credentials.

## Semantic Layer (`semantic/`, served by `semantic-mcp` :9200)

Vocabularies as **data**, not prose: a `Vocabulary` (classes with layer/aspect facets and
definitions, relation types, the permitted source→relation→target matrix, modelling rules)
renders to RDF; a `Registry` holds many; a `SemanticStore` (rdflib, in-process, named graphs)
holds vocabularies + instance models and answers SPARQL over all of them. ArchiMate 3.1 is the
first vocabulary: `semantic/archimate/taxonomy.json` (classification, distilled from the cheat
sheet) + `archi-relationships.xml` (Archi's machine-readable complete Appendix B matrix, 62
concepts / 3,844 pairs, letter key in `vocab.py`). Add a vocabulary = a JSON/XML data file +
a `build()`; add a question = a SPARQL template in `service.QUESTIONS`.

- **Why not vector search**: the cheat sheet is a taxonomy + a relationship matrix — tables and
  rules, not prose at scale. Deterministic lookup/validation beats retrieval, and Ollama Cloud has
  no embedding models anyway. Vector stores stay reserved for large text corpora later.
- **Derivation** (`model_rdf.py`): structural chains derive the weakest relation; structural
  chain + dependency derives that dependency (`am:derivedRealization`, `am:derivedServing`…).
  This is what makes "which goals are realized by components on node X" answerable.
- **The skill engine uses it**: `validate_relations()` is exact (full matrix + interface-exposure
  semantics) when `semantic/` is importable, coarse otherwise; every exported element's
  documentation is prefixed with its `[Layer · aspect — Type]` classification.
- **Interfaces have their strict meaning**: an interface is the access point of a service —
  `Composition owner→interface` plus **`Assignment interface→service`**; a consumed service without
  an assigned interface is a warning. Functions are the decomposition unit (component assigned
  to function, function realizes service); business channels are `BusinessInterface`s realized by
  the `ApplicationInterface` that implements them.
- **Reference models are a second KIND of vocabulary — SKOS concept schemes** (`semantic/skos.py`,
  `semantic/reference/baguild.py`): the BA Guild Healthcare Provider v2.0 and Insurance v5.0
  models are loaded from their ORIGIN workbooks (capability map L1–L4 with tiers, value streams,
  and — insurance — organisation, stakeholder and information maps). The workbooks are licensed:
  they live in `semantic/reference/sources/` (git-ignored) or `REFERENCE_MODELS_DIR`; only derived
  RDF exists at runtime. Same-label top capabilities across schemes are linked by
  `skos:exactMatch` in a mappings graph — schemes are never merged. Stable concept ids are
  hashes of the full label path (the workbooks carry no ids).
- **Writing reference capabilities into ADOIT is a two-server operation**: `semantic-mcp`
  `semantic_export_archimate(scheme, root_label, depth)` projects a subtree to an ArchiMate spec
  (Capability + Composition, an L1 overview view in rows, one nested view per top concept —
  capability maps nest by convention, the one sanctioned use of containers); then `adoit-mcp`
  `archimate_render` + `adoit_request_import` render and stage it for approval like any model.
  `architecture/export_capabilities.py <scheme> [root] [depth]` runs that chain via the gateway.
- **Placement**: `semantic-mcp` is a separate, credential-free, read-only server granted to every
  team; `adoit-mcp` stays the governed EA-repository facade. Both import the same package.

## Approval Gate (human-in-the-loop for EA repository writes)

Event-based over the Redis already running — **Redis Streams**, not pub/sub, because approvals
must be durable and acknowledged. `shared/approvals.py` is the only API:
`request()` publishes to `approvals:requests` (one consumer group per channel:
`review-app`, `telegram` — each channel sees every request); `decide()` appends to
`approvals:decisions` (the audit log) with `approve | decline | update` (= changes requested,
stays open), actor, channel, comment; `status()/await_decision()` for the requester.

- **Write path is two MCP tools**: `adoit_request_import` (publishes the event, returns id,
  writes nothing) → human decision → `adoit_import_status` (decision + next step). On
  ADOIT:CE "approve" releases the XML for the UI import; on a full tenant the REST write runs
  inside that tool after approval. The tool never writes without a decision.
- **Channels**: `review/app.py` (Streamlit, `./lab.sh review`, :8501) shows views, model
  contents, trace link, and takes the decision; `channels/telegram.py` is the same contract
  as plumbing only (enabled by `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`; no diagrams — summary
  + link to the review app); `python shared/approvals.py approve|decline|update <id>` is the
  CLI channel. Adding a channel = a new consumer group name in `CHANNELS` + a consumer.
- Requests carry the OTel `trace_id` of the run that produced the model, so a reviewer can
  open the exact trace from the review app.

## Observability (Foundry observability analogue; traces double as the audit trail)

**Jaeger v2 runs as a native binary** (`tools/jaeger/jaeger`, downloaded from the GitHub release,
sha-verified, ~50 MB RAM) — NOT in a Colima VM; the docx's 2 GB VM is unnecessary and the 8 GB
budget is better spent elsewhere. Default config: OTLP/HTTP `:4318`, gRPC `:4317`, UI
`http://127.0.0.1:16686`, in-memory storage (traces vanish on restart — fine for a lab; switch
to the badger backend if retention is needed). `lab.sh up` starts it before the gateway.

Three hops emit into ONE trace per workflow run, joined by W3C `traceparent`:
- **Workflow/agent process** — root span `ea-modeling-run`, `service.name=process-ea-modelling`
  (`architecture/run_via_gateway.py` is the reference: one distinct service name per business
  process, `propagate.inject()` into the MCP transport headers). Agent Framework hosts will
  emit natively.
- **Gateway** — `litellm_settings.callbacks: ["otel"]` + `OTEL_EXPORTER=otlp_http`,
  `OTEL_ENDPOINT`, `OTEL_SERVICE_NAME=litellm-gateway` in `.env`; one span per LLM/MCP call
  carrying key/team/model/cost.
- **adoit-mcp** — ASGI middleware (inbound request spans, traceparent extraction) + a span per
  tool with `archimate.*` attributes (elements, relations, views, violations, warnings) +
  auto-instrumented urllib so ADOIT REST calls appear as children. `OTEL_EXPORTER_OTLP_ENDPOINT`
  unset ⇒ no-op tracer, no behaviour change. **Every MCP server entry in `litellm-config.yaml`
  needs `extra_headers: ["traceparent", "tracestate"]`** — without it the gateway drops trace
  context and the server's spans land in a separate trace (verified both ways).

Viewing: http://127.0.0.1:16686 → Search → Service `process-ea-modelling` → Find Traces, or
paste the trace id that `run_via_gateway.py` prints. Verified shape of one run: ~200 spans —
agent root + per-tool spans, gateway auth/redis/postgres/request spans, adoit-mcp request +
tool spans with `archimate.*` attributes and the ADOIT `GET`. Known noise: LiteLLM logs
"OpenTelemetry logging error … standard_logging_object" for `/mcp` routes — a LiteLLM logger
quirk; the spans are still emitted.

LiteLLM's Logs page (`LiteLLM_SpendLogs`) is the *ledger* (who spent what); Jaeger is the
*trace* (what happened, in what order, where time went, including hops outside the gateway).
Keep both; never store prompt/response bodies in the ledger until Presidio redaction is in
front of the gateway (`store_prompts_in_spend_logs` stays off).
