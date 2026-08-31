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

## Cloud Shape (no same-machine assumptions)

Everything stateful is managed: Neon (keys, spend, skills, **artifact store**), Redis Cloud
(limiter state, approval streams), Ollama Cloud, ADOIT, GitHub. The five Python processes are
stateless and address each other only through `shared/config.py` env vars:
`GATEWAY_URL`, `ADOIT_MCP_URL`, `SEMANTIC_MCP_URL`, `REVIEW_APP_URL`, `JAEGER_UI_URL`,
`BIND_HOST` (0.0.0.0 in containers), `REDIS_URL`, `ARTIFACTS_URL`.
- **Trust**: `MCP_SHARED_SECRET` — both MCP servers enforce `Authorization: Bearer` via
  `shared/mcpauth.py`; the gateway sends it (`auth_type: bearer_token`). Never run with
  `BIND_HOST=0.0.0.0` and no secret. The review app has a `REVIEW_APP_PASSWORD` gate; on Azure
  put Container Apps Entra auth in front instead.
- **Artifacts by reference, never by path**: `shared/artifacts.py` stores export specs, XML and
  SVGs in a Postgres `lab_artifacts` table and hands out `art://<id>/<name>` refs. Tool contract:
  `semantic_export_archimate` → `spec_ref`; `archimate_render(spec|spec_ref)` → `xml_ref`,
  `svg_refs`; `adoit_request_import(xml_ref, svg_refs)`; the review app reads refs. `outdir` /
  `spec_path` remain as local-dev conveniences only.
- `deploy/Dockerfile` (one image, role by command), `deploy/docker-compose.yml` (the cloud
  topology on any Docker host — unbuilt here: no daemon), `deploy/README.md` (Azure Container
  Apps mapping). `lab.sh` stays the single-machine runner with the same env contract.

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

## Identity (Entra ID — real tenant, per the design doc)

Tenant `socratesbusiness.onmicrosoft.com` (`ENTRA_TENANT_ID` in `.env`). Provisioned by
`gateway/entra_provision.py` (Microsoft Graph; idempotent by display name; get a Graph token
via device-code sign-in when re-running): app **lab-gateway** exposes `api://…`
(`ENTRA_GATEWAY_AUDIENCE`) with app roles `EA.Model`, `Tools.ADOIT`; app **ea-modeling-agent**
holds a client secret and is granted both roles (appRoleAssignment = admin consent). One app
registration per agent, paired 1:1 with its virtual key (key metadata + `ENTRA_CLIENT_TO_KEY`
in `.env` — JSON, must be single-quoted or `.env` sourcing breaks).

- **Agents authenticate with MSAL** (`shared/identity.py: agent_headers()`), client-credentials
  against `<audience>/.default`; falls back to the static virtual key when no client id is set.
- **The gateway validates JWTs** in `gateway/custom_auth.py` (`general_settings.custom_auth`,
  module resolved relative to the config file). **Contract: return None** (not a lab JWT →
  normal key auth) **or a virtual-key string** (LiteLLM then runs its full key auth on it —
  budgets/ACLs/spend intact). NEVER call the built-in `user_api_key_auth` from the hook: it
  re-enters the hook (infinite recursion, 500s on every route).
- **Gateway restarts must go through `lab.sh`** (or have the `ADOIT_MCP_URL`/`SEMANTIC_MCP_URL`
  defaults now in `.env`): the config's `os.environ/` references resolve from the process env,
  and a bare `source .env` restart once left the MCP URLs unresolved — symptom: 0 tools, no
  requests reaching the servers.
- Migration: this is the docx pattern verbatim — swap tenant + client ids to the corporate
  tenant; APIM `validate-jwt` replaces `custom_auth.py`.

## Serving Models to Developers

Both API standards on the one gateway, PII-guarded and metered: OpenAI-style
(`/v1/chat/completions`) and Anthropic-style (`/v1/messages` — point Claude Code at
`ANTHROPIC_BASE_URL=http://127.0.0.1:4000`). Models: Ollama Cloud (`gpt-oss-120b`,
`glm-flash`, `kimi-k3`), real Anthropic (`claude-sonnet-5`, `claude-haiku-4-5` — upstream
key `ANTHROPIC_UPSTREAM_API_KEY` injected by the gateway, a deliberate configured
credential, unlike the ambient key we strip), and `auto`.

- **Developer login is Entra**: `gateway/dev_login.py` (device code, public client
  `lab-developers`, delegated scope `access_as_user` on lab-gateway, pre-authorized — no
  consent prompt). It prints `OPENAI_*` / `ANTHROPIC_*` exports; the token IS the API key.
- **JIT keys**: `gateway/custom_auth.py` recognises user tokens (`scp` contains
  `access_as_user`) and provisions a personal virtual key on first login (team `developers`,
  $10/30d, oid→key mapping in Redis) — so `/model` (GET `/v1/models`) shows that person's
  allowlist and spend is attributed per developer. Agents (client-credentials, `roles` claim)
  keep their static mapping.
- **`auto` routing** (`gateway/auto_router.py`): **LLM-classified** — glm-flash (called
  directly at Ollama Cloud, not via the proxy: no recursion, ~100 tokens, 2.5 s timeout) labels
  each prompt `code | reasoning | simple` → `kimi-k2.7-code | claude-sonnet-5 | glm-flash`.
  Regex heuristics are the fallback when the classifier errs — `auto` never fails because
  routing failed. Caller hint `metadata.x-auto-route` wins; decision + method recorded in
  request metadata; verify via the spend log's resolved-model column. (LiteLLM's native
  embedding-based router stays unavailable: cloud-badged embedding models don't exist on
  Ollama Cloud yet — github.com/ollama/ollama/issues/14496; the classifier calls are direct
  SDK calls, so they appear in traces but not the proxy spend ledger — flat-rate anyway.)

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
- **Redis** backs limiter/budget/router state (via `litellm_settings.cache` with
  `supported_call_types: []` — LLM responses are never cached) and the approval streams.
  **Since Aug 30 2026 it is Redis Cloud (Azure East US)** — `REDIS_URL/HOST/PORT/PASSWORD` in
  `.env`; `lab.sh` checks it instead of starting brew redis when `REDIS_URL` is set. Measured
  cost from the UAE: ~180 ms RTT × ~20 sequential gateway Redis calls ≈ **+3.8 s per gateway
  request** (4.75 s vs 0.95 s direct). That is geography, not Redis: it vanishes once the gateway
  itself runs in the same Azure region. Until then, the local brew redis is a one-line fallback
  (comment in `.env`) or a hybrid (approvals on cloud, gateway state local). Verify with
  `redis-cli -u "$REDIS_URL" --scan` (keys `spend:team:*`, `{api_key:...}:window`) and `GET /cache/ping`.
- **Registry UI**: http://127.0.0.1:4000/ui (user `admin`, password = master key) — teams,
  keys, spend, models, MCP servers. API: `/team/info`, `/key/info`, `/key/list`.

- **MCP tool-call timeout**: `LITELLM_MCP_CLIENT_TIMEOUT=300` in `.env` (LiteLLM default 60 s
  kills long renders such as the full capability map; per-server `timeout` in `mcp_servers`
  also works).
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

## PII / Secret Guardrails (regex tier — LIVE; Purview/Defender analogue, first layer)

Versioned in `gateway/litellm-config.yaml` `guardrails:` — built on LiteLLM's local
`litellm_content_filter` (prebuilt regex patterns, ~1 ms, no external service), `default_on`
so it fires for EVERY credential and BOTH API standards (OpenAI `/v1/chat/completions` and
Anthropic `/v1/messages`) — covering the two use cases: developers consuming models (e.g.
Claude Code via the gateway) and the agentic solutions.
- **Policy: REVERSIBLE PSEUDONYMIZATION, no blocking** (`gateway/pii_guardrail.py`, a custom
  guardrail on LiteLLM's prebuilt pattern library): outbound text has every match replaced by
  `[TYPE#n]` before egress — verified the model receives only the placeholder — and the gateway
  restores originals in the response (mapping lives only in request metadata on this gateway).
  Patterns: `uae_emirates_id`, `uae_phone`, `street_address`, cards, IBAN, email, `us_ssn`,
  ipv4, AWS/GitHub/Slack/generic API keys. 82 prebuilt patterns available — extend
  `DEFAULT_PATTERNS` / config, not the UI, so policy stays reviewable.
- Known gaps: STREAMING responses keep placeholders (safe, just unrestored); models may refuse
  to repeat card-like placeholders (their own safety, not ours); the metadata key differs per
  route (`metadata` vs `litellm_metadata`) — the guardrail parks the map in both.
- **Boundary**: regex cannot catch names or free-text clinical PII — that is the second,
  NER tier: Presidio in-process middleware in the workflow hosts (docx §6), still to build.

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

**Jaeger v2 runs on Railway** (project `elegant-peace`, service `local-agent-lab`, image
`jaegertracing/jaeger:2.20.0`, deployed via the Railway GraphQL API with the project token in
`.env` — note Railway's API needs a browser User-Agent and the `Project-Access-Token` header).
UI: `https://local-agent-lab-production.up.railway.app` (`JAEGER_UI_URL`, domain targetPort
16686); OTLP/HTTP ingest over HTTPS on a second service domain
`https://local-agent-lab-production-522c.up.railway.app` (targetPort 4318 — Railway's TCP proxy
resets HTTP, so domains-with-targetPort is the pattern). The stock image binds receivers to
localhost, so `deploy/jaeger-railway.yaml` (0.0.0.0 receivers, memstore) is injected as the
`JAEGER_CONFIG` variable with start command `/cmd/jaeger/jaeger-linux --config env:JAEGER_CONFIG`
(Railway replaces the entrypoint; the binary path comes from the image config). In-memory
storage. **Both endpoints are public and unauthenticated** — acceptable for a lab whose spans
carry no PII, not for anything else; front them with auth before workflow hosts emit real data.
The native binary in `tools/jaeger/` is the local fallback: `lab.sh` starts it only when
`OTEL_EXPORTER_OTLP_ENDPOINT` points at localhost. **Railway is metered (trial credit): stop it
when not in use** — `lab.sh down` removes the Railway deployment and `lab.sh up` redeploys it
whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is remote and `RAILWAY_TOKEN` is set (spans sent while
it is down are simply dropped by the exporters; nothing else breaks). Topology view: Jaeger → System Architecture
(from traces); on Azure, Application Insights → Application Map from the same spans.

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
