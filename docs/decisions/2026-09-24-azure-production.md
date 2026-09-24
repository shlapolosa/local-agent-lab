# Azure as production, Railway as development (24 Sep 2026)

Status: ACCEPTED 24 Sep 2026 — Phase 0 in progress.

## Decisions taken (user, 24 Sep 2026)

| Question | Decision |
|---|---|
| Environments | **Railway = development, Azure = production.** Both deployed by GitHub CI/CD from the SAME image tag. |
| Gateway | **Two phases.** Phase 1: LiteLLM stays the gateway, on Container Apps, Foundry added as a model provider. Phase 2: APIM in front; `custom_auth.py`'s role table becomes inbound policy. |
| Region | **UAE North only** (compute, data, models). No Claude in production. |
| State | Dev's Postgres is a Railway **container** (pgvector pg16), not Neon. Prod: **Azure Database for PostgreSQL Flexible (B1ms, pg16, pgvector)** — a container on Container Apps would sit on SMB Azure Files, which Postgres cannot use. Redis stays a container. Same Postgres, so it is a `DATABASE_URL` change, not code. |
| Budget | **~$150/month** for production. Budget alert `lab-monthly` (currently $50) to be raised to match. |

Billing substrate already in place: subscription `lab-foundry` (`7ee78ad6-d5bb-484c-8ec9-1673b6553b2a`) in the
socratesbusiness tenant, providers registered, Power Platform PAYG plan `laboratory` linked.

## OPEN — residency means less than "UAE North" suggests (measured 24 Sep 2026)

`az cognitiveservices model list -l uaenorth` on this subscription:

| Deployment type in UAE North | Models | Where inference runs |
|---|---|---|
| **Standard** (PAYG, regional) | text-embedding-3-large/-small, ada-002, whisper | **in UAE North** |
| **GlobalStandard** (PAYG) | every chat model: gpt-5.x, gpt-5.4-mini, Kimi-K2.6, Kimi-K2.7-Code, DeepSeek-V4, Mistral-Large-3 | **any Azure region** — data at rest in UAE, processing global |
| **ProvisionedManaged** (PTU, reserved) | gpt-4.1, gpt-5-mini, gpt-5.1, o4-mini … | in UAE North — **thousands $/month minimum**, incompatible with the budget |
| DeveloperTier | gpt-4.1-mini, gpt-oss-120b … | evaluation tier, no SLA — not production |

So on a $150 budget "UAE North only" delivers: **compute, storage, identity, embeddings and speech in-region;
chat inference GlobalStandard from a UAE North resource**, stated as an exception exactly like the three
egress exceptions in CLAUDE.md. This is the same finding CLAUDE.md records for Azure OpenAI in UAE North,
now measured per SKU. The alternative is PTU for one chat model when a real workload justifies it.
**DECIDED (user, 24 Sep 2026): GlobalStandard, stated as a named exception**; PTU only when a real workload requires strict in-region inference.

## Model mapping (production)

Workload code names gateway MODEL GROUPS, not vendors, so the mapping lives in the gateway config and
aliases, never in workload code (same mechanism as `claude/kimi-k3` → `kimi-k3` today).

**Production is GPT-5.x only** (user, 24 Sep 2026: no Kimi — any coding model will do). Quota on the new
subscription, measured the same day: **only `gpt-5-mini` has GlobalStandard quota (500k TPM)**; every other
GPT-5.x is 0/0. So production STARTS with one chat deployment behind every chat name, and each name moves
to its target when the quota request is granted — a gateway-config change, no workload change.

| Gateway name (unchanged) | Dev (Railway) upstream | Prod now | Prod target (after quota) | Note |
|---|---|---|---|---|
| `kimi-k3` (5 call sites) | Ollama Cloud kimi-k3 | gpt-5-mini | **gpt-5.5** | model change — evals must be re-run |
| `kimi-k2.7-code` | Ollama Cloud | gpt-5-mini | **gpt-5.3-codex** | |
| `gpt-5.4-mini`, `gpt-5.4-mini-think` | OpenAI | gpt-5-mini | **gpt-5.4-mini** | same model once granted |
| `gpt-4.1` | OpenAI | gpt-5-mini | gpt-5-mini | gpt-4.1 is Legacy; not requested |
| `glm-flash`, `auto` classifier | Ollama Cloud | gpt-5-mini | **gpt-5.4-nano** | auto-router classifier target changes |
| `gpt-oss-120b` | Ollama Cloud | gpt-5-mini | gpt-5-mini | |
| `claude-sonnet-5`, `claude-haiku-4-5` | Anthropic | gpt-5-mini | **gpt-5.5** | Claude is not in UAE North; evals' adjudicator stays on dev |
| `text-embedding-3-large` | OpenAI | **text-embedding-3-large Standard — in-region** | same model and space: the corpus index carries over |
| `nomic-embed-text` | embedder container | not deployed in prod | no `embedder` service in prod |

## Phase 0 — production foundations (no workload traffic yet)

1. **Resource group** `rg-lab-prod` (uaenorth). Everything prod lives in it; `down` = scale to zero, not delete.
2. **Observability**: Log Analytics workspace + Application Insights. OTLP from every role goes to App
   Insights (the Foundry-observability analogue CLAUDE.md names); Jaeger stays dev-only.
3. **Key Vault** `kv-lab-prod`: the production secrets. **GitHub holds NO production secret** — unlike dev's
   `LAB_ENV`. A human writes secrets (`deploy/aca.py secrets sync` from a local `.env.prod`); Container
   Apps read them as Key Vault references through a user-assigned managed identity, scoped per role by the
   existing `ROLE_ENV` table (README already calls it "the Key-Vault-reference scope per Container App").
4. **Foundry**: one AIServices resource + project in UAE North; the deployments in the table above.
5. **Container Apps environment** (Consumption profile, uaenorth), internal VNet not required in Phase 1.
6. **CI identity**: Entra app `lab-deployer` with a **federated credential** for
   `repo:shlapolosa/local-agent-lab:environment:production` (OIDC — no client secret anywhere), Contributor
   on `rg-lab-prod` only.
7. **Prod state = a one-time COPY of dev (user, 24 Sep 2026)** — DONE. `psql-lab-prod-i4ov2m` holds `litellm`
   (registry, keys, grants, skills, artifacts, fabric embeddings; spend logs and health checks excluded) and
   `reference` (the signed corpus). Roles `lab_reference_{svc,pub,reader,publisher}` were recreated with their
   password HASHES, so every existing DSN keeps working with only the host changed. Verified: every table's row
   count equals dev's (75 + 10 tables); `lab_reference_svc` logs in, reads 3,954 records, may INSERT consumption
   and may NOT update records. Consequence, accepted: dev and prod share virtual keys and role passwords until a
   later rotation. Firewall: `AllowAzureServices` + a temporary `operator-0` rule (remove after bootstrap).

## Phase 1 — lift to Container Apps (LiteLLM remains the gateway)

- **One topology, two deploy targets** (DRY/Open-Closed, per CLAUDE.md): `SUBSTRATE`, `WORKLOADS`,
  `CHANNELS` and `ROLE_ENV` move out of `deploy/railway.py` into a platform-neutral `deploy/topology.py`;
  `railway.py` and a new `deploy/aca.py` are adapters that render it. Same commands on both:
  `substrate up|status|images|versions`, `workload <n> up`, `release`. Tests pin the topology once.
- **Ingress**: external — `gateway`, `review` (Container Apps Entra auth replaces `REVIEW_APP_PASSWORD`),
  `graph-mcp` (Graph change notifications). Everything else internal.
- **Fitting $150** — the lever is scale-to-zero, not fewer roles:
  - every **workload consumer** gets a KEDA **redis-streams** scale rule on `workflow:requests` for its
    consumer group, `minReplicas: 0` — a 600-1000 s run wakes its host; idle costs nothing. This is the
    Container-Apps-native form of "replicas of a stateless host".
  - the **stream-driven substrate roles** (notifiers, projector, reconciler, continuations, channels) get
    the same rule on their own streams.
  - **MCP servers and the gateway** stay `minReplicas: 1` at 0.25 vCPU / 0.5 GiB (a cold start is longer
    than the gateway's tool timeout).
  - Redis: one container, min 1, Azure Files volume for `/data`.
- **Rough cost** (to verify against the pricing calculator in Phase 0): ~12 always-on small replicas ≈
  $60-80; scale-to-zero consumers ≈ usage; App Insights within free ingestion; Foundry tokens at demo
  volume ≈ $10-30; Key Vault/Log Analytics ≈ $5. APIM (Phase 2) must fit the remainder.
- **External callers re-pointed to prod**: Copilot Studio connectors (a prod connection per agent),
  Graph subscriptions' notification URL, Power Automate webhooks, `PUBLIC_GATEWAY_URL`.
- **Exit test**: `scripts/e2e_smoke.py` against the prod gateway (every contract tool exposed),
  `aca.py substrate versions` (asked tag == running `LAB_BUILD_SHA`), one use-case chain end to end.

### Phase 1 as built — rules the design review (24 Sep 2026) turned into code

- **Production computes its coordinates.** `aca.network(target)` sets REDIS_URL, the OTLP endpoints and
  every public URL; `.env.azure` cannot point a production app at dev by omission, and `assert_production`
  refuses to render while ANY app would receive a value containing `railway` or `ollama.com`. Production
  DENIES dev's vendor keys (`OLLAMA_API_KEY` would otherwise let the `auto` router's classifier send
  prompts to Ollama Cloud), the bucket, Railway's plane; Railway denies `AZURE_FOUNDRY_*`.
- **A public server is reached at its own https edge**, an internal one at `http://<app>` — an external
  ingress refuses plain http, and a redirected POST is a failed call.
- **Secrets are decided by provenance, not by look**: a coordinate is plain, a declared COPY
  (`topology.COPIES`) references its source, a profile value references itself. `LAB_CONFIG_DIGEST`
  makes a changed value change the template, so it rolls — a Key Vault reference alone would not.
- **Configuration is not a code release**: `substrate up` / `workload up` keep an existing app's image;
  only `release` (CD, behind the reviewer) moves it. `substrate up` publishes the secrets first.
- **Released means serving**: `release` waits for each app's newest revision to be its READY one and
  fails when nothing was rolled; `images` compares what each READY revision serves with the release;
  `versions` reads each process's own `build=` start line from Log Analytics.
- **Replica churn cannot lose or duplicate a run** (shared consumer code, so Railway too): a running
  consumer HOLDS its entry with a heartbeat, a reclaimed entry whose run already started is failed not
  re-run, and a workload replica gets the maximum 600 s grace to finish.
- **The quiet gate's credential is an identity, not a secret**: `lab-deployer` holds the `Workflow.Submit`
  role and asks `/api/runs/open` with an Entra token. It still needs a virtual-key mapping in the prod
  registry (custom_auth maps app -> key) — minted with the prod identities (separation item 1). Until
  then the gate reports it cannot ask and proceeds.
- **The deploy identity's federated subject is GitHub's IMMUTABLE-ID form** —
  `repo:shlapolosa@6398826/local-agent-lab@1351618494:environment:production` — not the name-only
  `repo:shlapolosa/local-agent-lab:environment:production` the Microsoft docs still show. GitHub presents the
  id form, and the first CD run failed `AADSTS700213` against a name-only credential (24 Sep 2026). The id
  form is also the safer one: a deleted-and-recreated repo of the same name cannot present it.
- **First deploy, measured** (24 Sep 2026): the gateway restart-looped at 2 GiB (exit 137, 16 s into every
  boot) — the dev gateway peaks at 2.52 GB, so it runs at 3 GiB; every size comes from Railway's measured
  peaks; ARM lists apps 20 to a page (a one-page `release` skipped every workload and reported success); a
  new app is refused on an image tag the registry lacks. Smoke through the public gateway: `kimi-k3` answered
  from Foundry gpt-5-mini, embeddings 3072-d in-region, 117 MCP tools from 9 servers.
- **Known and accepted for now**: Redis persists to the replica's own disk (the Azure Files RDB spike is
  open — approvals do not survive a Redis restart until it lands); every submit wakes every workload host
  (each group has lag on the shared request stream — ~$0.08 per submit, per-process streams later);
  the substrate stream consumers run one always-on replica rather than scaling to zero.

## Phase 2 — APIM IS production's gateway (decided 24 Sep 2026)

**Production runs on APIM only, dev on LiteLLM only — "never shall the two meet"** (user). This is the lab's
founding claim put to the test: LiteLLM is the local stand-in for APIM, so production should need
configuration and adapters, not a rewrite. Tier: **Developer** ($48/mo, UAE North; no SLA and no path to v2 —
every API and policy lives in Bicep/rendered files so a Basic v2 move is a redeploy). Budget alert → $200.

Decisions (user, 24 Sep 2026):
- **MCP — the client aggregates.** APIM exposes each MCP server at `/mcp/<server>` (its native "expose an
  existing MCP server"); `lab.platform.mcp_client` connects to each configured server and applies the same
  `<server>-<tool>` naming, so contracts, preflight and REQUIRED_TOOLS are unchanged. Dev keeps LiteLLM's
  single `/mcp`; the adapter is chosen by configuration.
- **Authorisation — Entra app roles, enforced by APIM.** Each LiteLLM team grant becomes an app role on
  `lab-gateway-prod` (per MCP server and tool set, the /api roles, model use), assigned to the `-prod` apps;
  APIM's `validate-jwt` checks it per API/operation/tool. Budgets become per-client `llm-token-limit`, spend
  becomes `llm-emit-token-metric` in App Insights.
- **Key-holding callers — APIM subscription keys** (the virtual key's documented analogue): the fabric
  curator, the embedder, the Copilot connectors, the deploy gate.
- **PII — ported to an APIM policy fragment**: the patterns the lab uses replace matches with `[TYPE#n]`
  inbound and restore them outbound, for every caller (streaming stays unrestored, as today).
- Dropped in prod: `auto` routing (no workload uses it), Claude aliases (no Claude in UAE North), JIT
  developer keys, the skills registry and agent cards (dev-only registries).

Reachability: APIM Developer is outside the Container Apps environment and the servers' ingress is internal,
so each server APIM routes to gets external ingress restricted by `ipSecurityRestrictions` to APIM's outbound
IP, still behind `MCP_SHARED_SECRET` (which APIM injects). A VNet would mean recreating the environment.

Build order: models API (Foundry via APIM's managed identity, alias map, token limit/metric) → /api from the
apipolicy table (generated, parity-tested) → MCP APIs + the client aggregation adapter → app roles mirrored
from the prod registry's team grants → subscriptions for key callers → PII fragment → vector-store routes →
cutover (workloads' GATEWAY_URL to APIM, the LiteLLM app removed from prod, CI's registry steps dev-only).

## Phase 2 as first planned (superseded above): APIM as the governance plane

- Tier chosen to fit the budget (Consumption or Developer; Basic v2 does not fit $150 alongside Phase 1)
  — verify at the time which AI-gateway policies each tier supports.
- **Generated, not hand-written, policy**: `lab.substrate.apipolicy`'s `(method, path) → role` table
  renders the inbound `validate-jwt` + `<required-claims>` policy; a parity test keeps them equal (the
  table stays the single source of truth).
- Token limits / token metrics policies on the model APIs; MCP servers exposed through APIM.
- `custom_auth.py` retired on the prod path once APIM carries every rule it enforced.

## Where things run: Container Apps vs Foundry hosted agents

Foundry **hosted agents** (GA Jul/Aug 2026, available in UAE North) run agent code as a container in a
per-SESSION, VM-isolated sandbox. They are request-driven (Responses / Invocations / A2A endpoints), scale to
zero after an idle timeout of 2-60 min, get an Entra agent identity automatically, and bridge to Teams.
They host AGENTS. Most of this lab is not agents:

| Component | Runs on | Why |
|---|---|---|
| gateway, the MCP servers, review app, Redis, notifiers/projector/reconciler/continuations, channels | **Container Apps** | Long-lived servers and stream consumers. A per-session agent sandbox has no place for them. |
| workload hosts (a workflow that CONTAINS agents, consuming `workflow:requests`) | **Container Apps in Phase 1**; candidate for hosted agents later | They PULL from a stream. A hosted agent is PUSHED a request. Moving one means the front door invokes an Invocations endpoint (background mode) instead of an XADD. That is a contract change, and it is worth a spike on one workload first. |
| models | **Foundry** (deployments above) | |
| project: evals, traces, agent catalogue | **Foundry** | App Insights is shared with the project. |

**Invariant to protect if hosted agents are adopted**: a hosted agent calls models through its PROJECT
endpoint by default, which bypasses the gateway and so breaks "all traffic through the gateway". Its model
and tool calls must be pointed at the gateway (LiteLLM in Phase 1, APIM in Phase 2) before any workload moves.

## Separating dev from prod beyond URLs and state

URLs and state are separate (own gateway, own Postgres copy, own Redis). Three things are still SHARED
and each is its own work item — the copy of dev's registry made them shared, it did not make them right:

1. **Identities — DONE 24 Sep 2026** (`scripts/mirror_identities_to_prod.py`, dry-run by default): 25 Entra
   apps mirrored as `<name>-prod` with their own secrets and dev's GRANTED roles (a `lab-gateway` role
   became the same role on the new **`lab-gateway-prod`** audience; Graph grants stay Graph grants; SSO
   redirects point at production); all 26 registry keys re-minted with identical settings and the copies
   deleted; `lab-deployer` mapped to a zero-tool key; the master key rotated with the old one kept as
   `LITELLM_SALT_KEY` so LiteLLM's stored config still decrypts. Verified at the prod gateway: the new master
   key 200 and the old 401; a prod agent 200; a DEV agent 401 on its own audience, on prod's, and by its
   virtual key — while dev's gateway still accepts dev's. Found on the way: the ten use-case SPECIALIST
   identities never reached the cloud workloads (allowlist admitted only USECASE_AGENT_*), so all ten ran on
   the shared key; now admitted, parity-tested against `PREFIX_FOR`.
   Was: Prod's `litellm` database is a copy, so every virtual key, the master key and the
   `ENTRA_CLIENT_TO_KEY` mapping are valid on BOTH gateways, and the Entra agent app registrations (one per
   agent) and their client secrets are the same objects. Target: prod-only app registrations per agent
   (`<agent>-prod`), minted prod virtual keys, a prod master key, and the dev keys revoked in the prod
   registry. The `lab-gateway` audience/app roles may stay shared (roles are vocabulary, not grants) or be
   split into `lab-gateway-prod` — decide before minting.
2. **The Copilot Studio environment — DECIDED 24 Sep 2026: production agents live in the DEFAULT environment
   (UAE), as separate "(Prod)" agents with production connections.** A new environment was tried via the BAP
   API and refused `MacroRegionRequired`: since Sep 2026 Power Platform places a NEW environment only by MACRO
   region unless every Microsoft 365 seat has Advanced Data Residency (ADR), and the UAE's macro region is
   "Europe, UK, Middle East, Africa" — the datacenter could be any of eleven countries, and the first choice
   becomes the tenant's affinity. Default predates that and is UAE-resident. Residency outranked environment
   separation; ADR (paid, per seat, all seats) is the way back to a separate UAE environment.
   **DONE 24 Sep 2026, entirely through APIs** (Power Apps + Dataverse): "Documentation Fabric (Prod)" and
   "Use Case Desk (Prod)" — each a cloned custom connector whose backend is the PROD gateway, a connection
   holding the prod key (FABRIC_BOT_KEY / USECASE_SUBMITTER_KEY), a connection reference, and the bot with
   its components. Both tested green in Copilot Studio. What a Dataverse-created clone needs that the portal
   does silently — each one cost a failure: `PvaProvision` before `PvaPublish` (else 409); the bot's
   CONFIGURATION names components by schema (`gPTSettings.defaultSchemaName` → the instructions) and must be
   re-prefixed (else empty instructions); a tool resolves its connection through the
   `botcomponent_connectionreference` RELATIONSHIP, not the YAML name (else "1 missing connection
   reference"); and a reference name can EMBED the connector name, so the connector id is replaced only on
   its own `connectorId:` line. Web search is OFF on both prod agents (`agentSettings.web.enableWebSearch`,
   and the Conversational-boosting fallback deactivated) — they answer from their tools or say they cannot.
   Superseded plan: a separate `prod` environment linked to the `laboratory` billing plan, the agents promoted
   into it as a SOLUTION (export dev, import prod), with their connectors pointed at the prod gateway and a prod
   connection identity. Default stays dev.
   Original text: **The Copilot Studio environment.** The tenant has ONE Power Platform environment (Default), holding both
   agents and the PAYG plan. Target: a separate `prod` environment linked to the `laboratory` billing plan,
   the agents promoted into it as a SOLUTION (export dev, import prod), with their connectors pointed at the
   prod gateway and a prod connection identity. Default stays dev.
3. **Tenant-side scopes — DONE 24 Sep 2026, through APIs.** Team `Lab Production` (created via Graph — a
   team made in the Teams desktop client never reached the directory), channel `Approvals`, site
   `sites/LabProduction_8b59e8` with a `Fabric Wiki` folder; prod FABRIC_ALLOWLIST / FABRIC_WIKI_FOLDER point
   at that library; a prod Graph subscription watches it and delivers to prod graph-mcp (Graph validated the
   endpoint on creation); the approvals and meeting-notifier flows cloned as "(Prod)" flows on the existing
   Teams connection, their trigger URLs written straight to `.env.azure`; approvals verified end to end
   (webhook 202, flow run Succeeded). Dev's pilot library, channel and flows are untouched.
   Original text: **Tenant-side scopes.** Graph change-notification subscriptions (point at dev `graph-mcp`), the fabric's
   SharePoint allow-list and wiki folders, the Teams/Power Automate webhooks (approvals channel, meeting
   notifier, use-case notifier), and the Graph app permissions of `lab-collab-reader`. Target: prod gets its
   own subscriptions to its own `graph-mcp`, its own folders/libraries (or an explicit decision to share the
   pilot library read-only), its own webhooks, and its own collab app registration so dev can never write
   into prod's scope.

## CI/CD (GitHub)

```
push main → test → build (ghcr sha-<short>) → deploy-dev (Railway, as today) → smoke dev
          → deploy-prod  [environment: production, required reviewer]
               azure/login (OIDC) → deploy/aca.py release  (SAME sha tag — promotion, never a rebuild)
               → substrate images + versions → e2e_smoke against prod
```

- Promotion is by immutable tag: what reached prod is exactly what ran on dev.
- The same deploy gate as dev: wait for a quiet run board (`/api/runs/open`) before rolling the gateway.
- Prod config is NOT in GitHub: Key Vault, written by a human. CD ships code; prod configuration stays a
  deliberate act.
