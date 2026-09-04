# Local Agentic Prototyping Platform — Business Analysis & Solution Description

**Document type:** Business Analysis / Solution Description
**Solution:** `local-agent-lab` — Local Agentic Prototyping Platform
**Authoritative design:** `docs/Local-Agentic-Prototyping-Platform.docx` (DOH Abu Dhabi EA, Draft v0.3)
**Status:** Reference business process live; existing-architecture-aware modelling Phase 1 complete
**Audience:** Enterprise architects, DOH Abu Dhabi EA stakeholders, platform engineers

> Sources: this document is grounded in the repository. Where a claim traces to a specific file it is
> cited inline (e.g. `config/litellm-config.yaml`). The authoritative `.docx` design was not parsed
> for this write-up; its intent is taken from `CLAUDE.md`, which distils it, and from the live code.

---

## 1. Executive Summary

The Local Agentic Prototyping Platform is a **governance-faithful sandbox for enterprise AI agents**.
It lets a team build agentic solutions on a laptop (an 8 GB M1 MacBook) and on a small cloud tier,
while reproducing the **exact governance shape** those solutions will run under in Microsoft Azure —
identity, a single egress gateway, metering, PII scanning, human approval and end-to-end tracing.

The guiding principle is **pattern parity with Azure, not feature parity**. Every prototype agent
authenticates, egresses through one gateway, is metered, is PII-scanned and is traced — precisely as
it would in production. Application code is written against the **Microsoft Agent Framework**, so a
solution migrates to Azure (Container Apps + APIM + AI Foundry) **without rework**: the same
`(base_url, credential)` client contract, the same typed workflow graphs, the same trace spans.

The platform runs **cloud-first for inference** (Ollama Cloud) so the 8 GB memory budget is spent on
governance plumbing, not model weights. Local components are each kept in the ~100–300 MB range.

The first end-to-end business process — **Visio/diagram → ArchiMate → ADOIT** — is live and
demonstrates the whole operating model: two identity-bearing agents, tool calls by reference through
the gateway, a typed hand-off contract, human approval before any repository write, and one trace per
run that doubles as the audit record.

---

## 2. Business Context & Goals

**The problem.** Enterprises want to prototype AI agents quickly, but "quick" prototypes usually
bypass the controls production demands (identity, data-loss prevention, cost control, auditability).
The result is a rewrite when the prototype is promoted — or, worse, an ungoverned agent reaching
production. For a regulated environment (health data, DOH Abu Dhabi) that gap is unacceptable.

**The goal.** Provide a place to build agentic solutions where the governance is present *from the
first line of code*, and where the local components are deliberate **stand-ins** for named Azure
services — so promotion to Azure is a configuration change, not a re-architecture.

**Pattern parity, not feature parity.** The lab does not attempt to reproduce every Azure feature. It
reproduces the **patterns** that matter for governance and portability:

- a single, policy-enforcing **egress gateway** (LiteLLM ≈ APIM / AI Hub Gateway);
- **per-agent identity** issued by a real Entra ID tenant;
- **metering and budgets** per agent and per business process;
- **PII pseudonymisation** before any data leaves the trust boundary;
- **human approval** before any change to a system of record;
- **one distributed trace per run** as the audit trail.

Because these patterns are identical to the Azure targets, the migration story is credible and
demonstrable rather than aspirational.

---

## 3. Stakeholders & Personas

| Persona | Needs | How the platform serves them |
|---|---|---|
| **Developer consuming governed models** | Use LLMs from their own tools (Claude Code, IDE plugins, OpenAI-standard clients) without holding raw provider keys, and stay within budget/policy. | The gateway serves **both** OpenAI-style (`/v1/chat/completions`) and Anthropic-style (`/v1/messages`) APIs, PII-guarded and metered. Credentials are a short-lived Entra JWT or a durable virtual key; client config is always `(base_url, credential)`. |
| **Agent / workflow (non-human principal)** | An identity, scoped tool access, and a spend account of its own. | One Entra app registration ↔ one virtual key ↔ one agent; the agent egresses only through the gateway and never holds tool/store credentials. |
| **EA reviewer / approver** | See what an agent proposes to write to the EA repository, and approve/decline/request-changes, with the supporting trace. | The **approval gate** (Redis Streams) plus the **review app** (Streamlit) shows the model, the views, NEW-vs-UPDATE context and a trace link before any write. |
| **Platform administrator** | Mint teams/keys, set budgets and tool ACLs, watch spend, register tools and skills. | The gateway **registry** (LiteLLM on Neon Postgres) with an admin UI; master key is admin-plane only. |
| **Enterprise architect / DOH stakeholder** | Confidence that prototypes will migrate to Azure with the same controls. | The explicit local→Azure service mapping (§5) and the portable client/identity/trace contracts. |

---

## 4. Scope

**In scope**

- A single governance gateway for all LLM, tool (MCP) and (future) agent-to-agent traffic.
- Per-agent Entra identity, virtual keys, budgets, rate limits and per-tool ACLs.
- Reversible PII/secret pseudonymisation at egress (regex tier, live).
- Governed MCP tool servers: EA repository facade (`adoit-mcp`), src/lab/core/semantic/vocabulary service
  (`semantic-mcp`), read-only upload store (`storage-mcp`).
- Human-in-the-loop approval for any write to a system of record.
- End-to-end tracing (OpenTelemetry → Jaeger) as the audit trail.
- One reference business process end to end (Visio/diagram → ArchiMate → ADOIT), existing-
  architecture-aware.
- A two-tier deployment: fully local by default, and a small managed cloud tier (Railway substrate +
  workload) with the same env contract.

**Out of scope (today)**

- Local model inference — inference is **cloud-only** (Ollama Cloud); the 8 GB budget depends on it.
- The NER PII tier (Microsoft Presidio, for names / free-text clinical PII) — designed, not yet built;
  the live tier is regex-based.
- **In-place REST writes to the current ADOIT tenant** — the hosted Community Edition blocks REST
  writes at its edge (see §8); the write path is human-gated file-import.
- A production identity-aware proxy in front of the review app / Jaeger (lab uses a password gate;
  Azure would front these with Container Apps Entra auth).
- Agent-to-agent (A2A) as separate hosts — the reference process mediates via one in-host workflow;
  A2A-through-the-gateway is the noted future upgrade.

---

## 5. Solution Overview / Architecture

The platform is a **single governance plane** with governed workers around it. Nothing talks
point-to-point: LLM calls, MCP tool calls and (future) A2A calls all route through the gateway, and
workers never hold upstream credentials.

```
   Developers (Claude Code, IDEs)          Agent workloads (Agent Framework hosts)
              │  (base_url, credential)                │  (per-agent Entra JWT / virtual key)
              └───────────────┬────────────────────────┘
                              ▼
                 ┌──────────────────────────┐
                 │   LiteLLM Gateway          │  ≈ APIM / AI Hub Gateway
                 │   /v1  /messages  /mcp     │  virtual keys · budgets · rate limits · tool ACLs
                 │   PII guardrail (egress)   │  metering · OTel spans · JWT validation
                 └───────┬───────────┬────────┘
        LLM (cloud)      │           │  MCP tool calls (governed, metered, traced)
                         ▼           ▼
                  Ollama Cloud   ┌─────────────┬───────────────┬──────────────┐
                  (AI Foundry    │ adoit-mcp    │ semantic-mcp   │ storage-mcp   │
                   analogue)     │ (EA repo     │ (vocabularies, │ (read-only    │
                                 │  facade)     │  SPARQL,       │  upload store)│
                                 │              │  validation)   │              │
                                 └─────┬────────┴───────┬────────┴──────┬───────┘
                                       ▼                ▼               ▼
                                    ADOIT           rdflib graph    Bucket / Postgres
                                  (EA repository)   (in-process)     (art:// refs)

              Human approval (Redis Streams) ── Review app / Telegram / CLI
              Trace per run (OpenTelemetry) ──▶ Jaeger  (Foundry observability analogue)
```

**Component roles and Azure mapping** (from `CLAUDE.md`):

| Local component | Stands in for (Azure) | Role |
|---|---|---|
| LiteLLM Proxy (`/v1`, `/mcp`, A2A) | APIM / AI Hub Gateway | Single governance plane: virtual keys, budgets, rate limits, tool ACLs |
| Ollama Cloud (primary) | AI Foundry models | Cloud-first inference |
| One Python host per workflow | Azure Container Apps | Agent hosting (~100 MB per idle async host) |
| LiteLLM teams/keys + Entra app registrations + A2A agent cards | Agent 365 | Agent registry & governance |
| Entra ID free tenant (real, via MSAL) | Entra ID | Identity; one app registration per agent |
| Presidio middleware + OTel trace audit | Purview | PII detect/redact on prompts, tool args, results |
| Guardrails middleware + cloud LLM-judge | Defender for AI | Prompt-injection & output scanning |
| OpenTelemetry → Jaeger | Foundry observability | Trace tree per workflow run; doubles as audit trail |

**Runtime model.** Business processes are Agent Framework **Workflows** — typed graphs of ChatAgents
and deterministic functions (sequential/concurrent/handoff, checkpointing, human-in-the-loop pauses).
A shared services layer provides the workflow engine, the middleware chain (PII → approval gate → OTel
emission) and MCP/A2A client integration. Each host sets a **distinct OTel service name** so
concurrent processes are traced and audited independently.

**Model catalogue** (`config/litellm-config.yaml`): Ollama Cloud `gpt-oss-120b`, `kimi-k3`,
`kimi-k2.7-code`, `glm-flash`; real Anthropic `claude-sonnet-5`, `claude-haiku-4-5`; and `auto` — an
LLM-classified intent router that maps a prompt to `code | reasoning | simple`.

---

## 6. Reference Business Process — Visio/Diagram → ArchiMate → ADOIT

The first live process (`src/lab/workloads/visio_to_archimate/`) turns a **system diagram** (a Visio `.vsdx`
or an image) plus optional **requirements documents** into a formal **ArchiMate** model, staged for
**human approval** and import into the **ADOIT** enterprise-architecture repository. It exercises the
entire operating model end to end.

**The graph** (`workflow.py`):

```
ba ──▶ resolve_existing ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
(reads   (search ADOIT:        (BA desc + matches   (spec ->   (agent validates    (human-gated
 inputs   NEW vs UPDATE,        -> engine spec,      art://ref   + renders BY REF)   import, decision
 via gw   match existing ids)   reuse ids, folder)   sem-mcp)                        shown)
 storage)
```

**1. Business Analyst agent (`ba`).** Reads its inputs *by reference*, only through the gateway's
read-only `storage-mcp`. Three input kinds, three deterministic mechanisms (never conflated):

- a **`.vsdx`** is structured OOXML — parsed deterministically (`storage_read_vsdx`); vision would
  only degrade it;
- a **diagram image** (png/jpg) is fetched (`storage_get`), normalised server-side (≤1600 px, PNG/JPEG,
  decorations dropped — `src/lab/platform/docparse.py`) and attached inline for the model's **vision**;
- a **requirements document** (docx/pdf/md/txt) is read as text (`storage_read_document`) and its
  **embedded figures** are extracted (`storage_extract_figures`) and attached too.

Requirements are treated as **evidence, not new boxes**: a requirements-only element is added only if
plainly part of *this* system (tagged `source: requirements`), otherwise it becomes an `openQuestion`.
The BA emits schema-validated JSON (`schemas/ba_output.schema.json`).

**2. Existing-architecture resolution (`resolve_existing`).** Before any design, the workflow searches
the **live EA repository** (`ea_search`, through the gateway) for objects related to the described
system. A Resolver agent (`prompts/resolve.md`) decides **NEW vs UPDATE**, picks the target **domain**,
and matches BA elements to **existing repository object ids**. If the repository is unreachable the run
degrades gracefully to **NEW** with a warning.

**3. Architect agent (`architect_design` / `architect_finalize`).** Formalises the BA description into
an ArchiMate spec. For matched elements it **reuses the real ADOIT object id verbatim** (so the
repository is updated, not duplicated), tags every element with its domain **folder**, and gives
relations **stable hashed ids**. It then validates and renders **by reference**: a deterministic node
stores the spec via `semantic_store_spec` (getting an `art://` ref), and the Architect calls
`semantic_validate_model` + `archimate_render` by `spec_ref`.

**Why by reference (the crux).** Small-argument tool calls are reliable; a large nested spec passed
*inline* as a tool argument is emitted only stochastically (Agent Framework #2747). So the platform
**never passes a spec inline — it passes the ref**. A **deterministic fallback** (`_call_tools` by
ref) guarantees the pipeline completes even if a model skips a call on a given run.

**4. Typed hand-off, not agent-to-agent.** Agents never call each other directly — the workflow
mediates. The BA's schema-validated JSON passes a **deterministic completeness gate** (with one BA
retry that re-sends the diagram) before the Architect sees it.

**5. Human approval + import (`stage_import`).** The model is handed to the EA repository by
reference for a human decision (`ea_stage_import` → decision → `ea_import_status`); nothing is written
without approval. `ea_stage_import` produces whatever THAT repository needs a human to import and
returns those artifacts — the workload never assumes a particular file exists (on hosted ADOIT:CE it is
the ArchiMate views XML + an Excel object file; a write-capable tenant would return none and write over
REST after the approval). The review app shows the model, views, the NEW/UPDATE banner and a trace link.

**Identity.** `ba-agent` (role `EA.Model`) and `architect-agent` (`EA.Model` + `Tools.ADOIT`) each hold
one Entra app registration ↔ one virtual key, both in team `visio-conversion` (granted `ea_mcp` +
`semantic_mcp` + `storage_mcp`). LLM calls bill each agent's own key; tool nodes use the identity that
holds the grant.

**Triggering & durability.** A person uploads on the review app's **Submit** page → files land in the
upload store (`art://` refs) → an explicit **Run** publishes a durable `workflow:requests` event (Redis
Streams) → the long-lived `wf-visio` consumer runs the graph and writes status/trace/approval back.

---

## 7. Governance & Non-Functional Requirements (the Architectural Invariants)

These invariants define the lab and are treated as binding requirements (`CLAUDE.md` §Architectural
Invariants):

- **G1 — All traffic through the gateway.** LLM, MCP and A2A calls route through the one LiteLLM proxy;
  never point-to-point. Agents never hold tool credentials — the gateway injects upstream credentials.
- **G2 — One team per business process; one virtual key per agent.** Each key pairs 1:1 with an Entra
  app registration (and an A2A agent card).
- **G3 — No unredacted PII crosses the egress boundary.** PII/secret scanning runs before anything
  leaves the machine (regex tier live; NER tier designed).
- **G4 — Cloud-only inference.** No local models; the memory budget depends on it.
- **G5 — Shared tools are governed MCP servers** over streamable HTTP, registered with the gateway.
  Stdio MCP servers are dev-only sandboxes and must never migrate.
- **G6 — Destructive/write tools require human approval** via the approval gate.
- **G7 — Workloads hold no store credentials.** Inputs arrive as `art://` refs, read only through
  `storage-mcp`; bucket/DB credentials are stripped from every workload (`deploy/railway.py
  configure_workload()`).
- **G8 — One distinct OTel service name per host**, so concurrent processes trace independently.
- **G9 — Everything is registered in the gateway.** Every MCP server is in `litellm-config.yaml` and
  granted per team; every skill is registered in both LiteLLM skill registries. A tool that exists only
  on disk is ungoverned and invisible.
- **G10 — One trace per run** joins process → gateway → MCP, the audit record.

**PII / secret guardrail (live, regex tier).** `src/lab/substrate/gateway/pii_guardrail.py` on LiteLLM's prebuilt
pattern library, `default_on` for every credential and both API standards. Policy is **reversible
pseudonymisation, no blocking**: each match is replaced by `[TYPE#n]` before egress (the model sees only
the placeholder) and the gateway restores originals in the response. Patterns include UAE Emirates ID,
UAE phone, street address, cards, IBAN, email, US SSN, IPv4 and API keys.

**Metering & budgets.** Ollama Cloud is flat-rate; the config carries nominal per-token prices so every
call returns `x-litellm-response-cost` and spend rolls up key → team. The reference agent team runs at
2 USD / 30 days, 30 rpm, 60k tpm.

**Semantic correctness.** The `semantic-mcp` service holds ArchiMate 3.1 as **data** (a taxonomy +
Archi's complete relationship matrix, 62 concepts / 3,844 pairs) and answers SPARQL; the modelling
engine validates relations exactly against it, enforcing strict ArchiMate semantics (e.g. interfaces
as the access point of a service).

---

## 8. ADOIT Integration & Write Paths (current findings)

The ADOIT integration is an **own-built MCP facade** (`src/lab/substrate/mcp/adoit/`) over the ADOIT REST API,
because the tenant has no built-in MCP. It is the **ADAPTER** behind the lab's **vendor-neutral
EA-repository PORT** (gateway alias `ea_mcp`, catalogue `lab.platform.contracts.EATools`): read tools
(`ea_search`, `ea_object`, `ea_repositories`), the validate/render engine tools, and the human-gated
write path (`ea_stage_import`, `ea_import_status`, `ea_import_instructions`). No tool names the vendor
and none leaks an ADOIT limitation, so swapping ADOIT for another EA tool is a different server
registering the same tools under the same alias — no workload change. ADOIT credentials
(`ADOIT_BASE_URL`, `ADOIT_USERNAME`, `ADOIT_PASSWORD`, `ADOIT_REPO_ID`) live in `.env` and are injected
server-side — **agents never hold them**.

### 8.1 Tenant reality: hosted Community Edition, reads yes / writes edge-blocked

The current tenant is **BOC-hosted ADOIT Community Edition** (`adoit-ce.boc-cloud.com`). Live probing
established a precise read/write asymmetry:

- **REST reads work.** Object **search** (`GET /rest/2.0/repos/{repo}/search?query=…`, non-empty filter
  required) and **object detail** (`GET …/objects/{id}` → attributes + relation slots) both return data.
  These power the existing-architecture-aware step (§6) directly, against the real ~134-object
  landscape.
- **REST writes are blocked at the edge.** `POST /objects` (create), `PATCH /objects/{id}` (update) and
  `DELETE /objects/{id}` return a **BOC edge-proxy HTML page — "URL not available on this server"** —
  even though the application's `OPTIONS` advertises those verbs (`Allow: POST` / `PATCH,DELETE`). The
  same credentials and IP read fine, so this is **not** authentication (401), **not** an IP allowlist,
  and **not** the request body — it is a **hosting policy at the CE edge** that refuses write verbs.

> Correction note: earlier internal notes (and `CLAUDE.md`) recorded the tenant as "full ADOIT 18 with
> working REST CRUD". That is **correct for reads and wrong for writes on this hosted CE tenant**. The
> corrected position: **CE REST is read-only at the edge.**

### 8.2 The governed write path today: human-gated file-import

Because direct REST writes are unavailable, the write path is **file-import through the ADOIT UI**,
always behind human approval:

- **ArchiMate Model Exchange XML** — the rendered model imports **views + object creation**. This is
  the established path (`ea_import_instructions`).
- **ADOIT Excel object import** — ADOIT's native Excel interface **imports *or updates*** objects and
  their attributes/relations (create + update). This is the mechanism intended to carry **object-level
  updates** on CE, complementing the ArchiMate view file. (The Excel template structure is
  configuration-specific and downloaded from the ADOIT UI, so a generated file must match the tenant's
  template.) Both files are produced INSIDE `ea_stage_import` — that a spreadsheet is needed at all is an
  ADOIT:CE limitation, so it is a private detail of this adapter, not a tool of the port.

### 8.3 Object vs view model (verified) — why writes are high-stakes

ADOIT distinguishes two kinds of artefact, and it matters for governance:

- **Repository objects** — the shared, canonical **Object Catalogue** entries. They are **versioned**
  natively (`A_OBJECT_VERSION`, version history, lifecycle state, valid-from/until) and **shared across
  views**. Editing an object's name/attributes/relations propagates to **every** view that places it;
  only **geometry is per-diagram**. Deleting an object removes it from all views. → **high blast
  radius.**
- **Views** — diagrams (`artefactType=DIAGRAM`) that place **MODINST** instances of objects. A view
  write is **scoped** to one diagram.

This is why the reference process **reuses existing object ids** (no duplicates), organises by domain,
and surfaces NEW-vs-UPDATE and cross-view impact at the approval gate.

### 8.4 REST write facade: built, grounded, and dormant behind a toggle

A granular **REST write facade** is implemented and grounded — `create_object`, `patch_object`,
`delete_object`, `create_relation` (and a read-only `object_impact` blast-radius probe) in
`src/lab/substrate/mcp/adoit/adoit_rest.py`. The request bodies were verified against the **tenant's own OpenAPI**
and BOC's official developer examples (e.g. create object `{name, metaName:C_*, attributes:[{metaName:
A_*, value}]}`; create relation `POST …/relations/{direction}/{RC_*}` body `{toId}`; relation classes
map 1:1 to the tenant metamodel, `RC_<UPPER_SNAKE>`).

It is kept **dormant behind an `.env` toggle**, `ADOIT_REST_WRITE` (default **false** on CE;
`src/lab/platform/config.py`). On CE the write path stays file-import; the facade activates only against a
**full/licensed ADOIT** tenant or the **Azure/Foundry** target, where the same code performs true
in-place updates. The approval tool (`ea_import_status`) already reports which write path is active.

---

## 9. Requirements Traceability

| ID | Requirement (type) | How the solution satisfies it | Azure migration target |
|---|---|---|---|
| BR-01 | Prototype agents must migrate to Azure without rework (business) | Microsoft Agent Framework workflows; portable `(base_url, credential)` client contract; identical trace spans | Container Apps + APIM + AI Foundry |
| BR-02 | Governance present from the first line of code (business) | Every call routes through the gateway; identity, metering, PII, approval, tracing wired into the shared layer | APIM policies + Foundry |
| NFR-01 | Run within an 8 GB M1 budget (NFR) | Cloud-only inference (Ollama Cloud); local components ~100–300 MB each | N/A (cloud compute) |
| INV-G1 | All LLM/tool/A2A traffic through one gateway (NFR/security) | LiteLLM proxy `/v1`, `/messages`, `/mcp`; no point-to-point; upstream creds injected by gateway | APIM / AI Hub Gateway |
| INV-G2 | One team per process, one key per agent (security) | `scripts/bootstrap_registry.py` teams/keys; key ↔ Entra app 1:1; MCP grants per team | APIM subscriptions + Agent 365 |
| INV-G3 | No unredacted PII crosses egress (security/compliance) | `src/lab/substrate/gateway/pii_guardrail.py` reversible pseudonymisation, `default_on`, both API standards | Microsoft Purview |
| INV-G3b | Names / free-text clinical PII (compliance) | Presidio NER middleware in workflow hosts — **designed, not yet built** | Purview |
| INV-G4 | Cloud-only inference (NFR) | Ollama Cloud only; native Ollama client is off-limits (bypasses gateway) | AI Foundry models |
| INV-G5 | Shared tools are governed MCP servers (security) | `adoit-mcp`, `semantic-mcp`, `storage-mcp` over streamable HTTP, registered in `litellm-config.yaml`, granted per team | APIM-fronted tool/MCP endpoints |
| INV-G6 | Destructive/write tools require human approval (governance) | Approval gate (Redis Streams) + `ea_stage_import` → decision → `ea_import_status`; no write without a decision | Human-in-the-loop + Foundry |
| INV-G7 | Workloads hold no store credentials (security) | Inputs are `art://` refs read only via `storage-mcp`; `configure_workload()` strips bucket/DB creds | Managed identity + Container Apps |
| INV-G8 | Per-host distinct OTel service name (observability) | e.g. `process-visio-to-archimate`; one service name per business process | App Insights cloud roles |
| INV-G9 | Everything registered in the gateway registry (governance) | MCP servers in `litellm-config.yaml`; skills in both LiteLLM registries via `register_skill.sh` | Agent 365 registry |
| INV-G10 | One trace per run = audit trail (observability/audit) | W3C `traceparent` joins process → gateway → MCP; ~200–400 spans/run | App Insights / Foundry observability |
| ID-01 | Per-agent identity from a real IdP (security) | Entra tenant `socratesbusiness`; app registration per agent; MSAL client-credentials (`src/lab/workloads/identity.py`) | Entra ID |
| ID-02 | Gateway validates JWTs; portable credential shapes (security) | `src/lab/substrate/gateway/custom_auth.py` (Entra JWKS/audience/issuer); JWT **or** durable virtual key | APIM `validate-jwt` |
| ID-03 | Developer self-serve keys without raw provider keys (usability) | Entra SSO on the LiteLLM UI; JIT keys on first JWT use; `az`-acquired tokens | APIM Developer Portal |
| FR-01 | Convert a diagram (+requirements) to an ArchiMate model (functional) | `visio_to_archimate` workflow: BA (vision/parse) → Architect (ArchiMate) → render | Same on Container Apps |
| FR-02 | Read inputs by reference, governed (functional/security) | `storage-mcp` read-only tools; images normalised in `src/lab/platform/docparse.py` | Managed storage + MCP |
| FR-03 | Reliable tool calls (functional) | Tool calls **by reference** (small args) + deterministic fallback (AF #2747/#3313) | Same |
| FR-04 | Typed BA→Architect hand-off with completeness gate (functional) | `schemas/ba_output.schema.json` + deterministic gate + one retry | Same |
| FR-05 | Existing-architecture-aware: NEW vs UPDATE, reuse ids, folder by domain (functional) | `resolve_existing` + `ea_search`; Architect reuses object ids; `<organizations>` foldering | Same (REST write on full tenant) |
| FR-06 | Human review with model, views, NEW/UPDATE context, trace (functional) | Review app (Streamlit) + approval gate; Telegram/CLI channels | Container Apps + Entra auth |
| FR-07 | Object CRUD into ADOIT via file-import on CE (functional) | ArchiMate XML (views/creates) + Excel object import (create/update); human-gated | REST write facade on full tenant |
| FR-08 | True in-place REST writes when tenant allows (functional) | Facade built (`adoit_rest.py`), gated by `ADOIT_REST_WRITE` (default false on CE) | Full ADOIT / Foundry |
| FR-09 | Semantic validation of ArchiMate (functional/quality) | `semantic-mcp` taxonomy + relationship matrix; exact `validate_relations()` | Same |
| FR-10 | Serve both OpenAI- and Anthropic-style APIs, metered/guarded (functional) | Gateway `/v1/chat/completions` + `/v1/messages`; PII + metering on both | APIM |
| NFR-02 | Cost visibility per agent/process (NFR) | Nominal token pricing → `x-litellm-response-cost` → key/team spend rollup | APIM analytics |
| NFR-03 | Deployable off-laptop with same env contract (NFR) | Railway two-tier substrate + workload via `deploy/railway.py`; `src/lab/platform/config.py` env vars | Container Apps |
| CON-01 | ADOIT credentials never reach agents (security) | Injected server-side in `adoit-mcp`; stripped from workloads | Managed identity |

---

## 10. Assumptions, Constraints & Known Limitations

- **8 GB memory budget** — feasible only because inference is cloud-only; local components must stay
  small (~100–300 MB each).
- **Cloud dependencies are external by nature** — Ollama Cloud, ADOIT (CE), Entra and GitHub have no
  local equivalent; Neon Postgres (keys/spend/artifacts) stays cloud.
- **ADOIT CE blocks REST writes at the edge** — the single biggest constraint on the EA write path.
  The governed write path is human-gated **file-import** (ArchiMate XML + Excel object import). The REST
  write facade is built and grounded but dormant behind `ADOIT_REST_WRITE` until a full/licensed ADOIT
  or the Azure target is available.
- **PII coverage is the regex tier only (live)** — it cannot catch names or free-text clinical PII;
  the Presidio NER tier is designed but not yet built. Do not treat the current guardrail as sufficient
  for real clinical data.
- **Streaming responses keep PII placeholders** (safe but unrestored); some models refuse to echo
  card-like placeholders (their own safety).
- **Review app and Jaeger are behind a password gate only** — acceptable for a lab with PII-free spans;
  front with identity-aware proxy / Entra auth before real data flows.
- **Responses API forced stateless** (`store=False`) because Ollama Cloud's `/v1/responses` store is
  non-persistent; flip `AGENT_RESPONSES_STORE=true` only against a Responses-stateful backend (Azure).
- **A2A is in-host today** — the reference process mediates via one workflow; A2A-through-the-gateway is
  a future upgrade.
- **Element ids are stable on purpose** — changing an id duplicates objects on ADOIT re-import; the
  existing-architecture-aware step reuses real ADOIT ids to avoid duplication.

---

## 11. Roadmap / Build Order

**Delivered**

- Gateway governance plane (identity, keys/teams, budgets, PII guardrail, metering, both API standards).
- Governed MCP servers: `adoit-mcp`, `semantic-mcp`, `storage-mcp`, all registered and ACL'd.
- Semantic layer (ArchiMate 3.1 as data; SPARQL; exact relation validation) + reference capability
  models (BA Guild) as SKOS.
- Reference business process **Visio/diagram → ArchiMate → ADOIT**, end to end, with human approval and
  one-trace-per-run; verified on the cloud tier.
- **Existing-architecture-aware modelling — Phase 1 (done):** `ea_search`/`ea_object` reads;
  `resolve_existing` NEW-vs-UPDATE; object-id reuse; `<organizations>` domain foldering; approval
  surfacing.
- Two-tier cloud deployment (Railway substrate + `wf-visio` workload) with the same env contract.
- ADOIT **REST write facade built and grounded**, gated behind `ADOIT_REST_WRITE` (default false).

**Planned**

1. **Object CRUD via file-import on CE** — generate an ADOIT **Excel object-import file** (create +
   update) alongside the ArchiMate view file, so object-level updates land on CE without REST writes
   (requires the tenant's Excel template).
2. **Existing-architecture-aware — Phase 2 (REST write facade)** — split into **object** tools
   (create/patch/impact/delete, high blast radius, human-gated, cross-view impact shown) and **view**
   tools (scoped diagram placements), orchestrated by a per-object **changeset**
   (`reference | PATCH | POST | delete/unlink`). Activates on a full/licensed ADOIT or Azure via the
   toggle.
3. **PII NER tier (Presidio)** — in-process middleware in the workflow hosts for names / free-text
   clinical PII (the Purview analogue's second layer).
4. **A2A-through-the-gateway** — as processes split into separate hosts.
5. **Second pilot business process** — demonstrate concurrent runs with per-process traces and spend
   rollups.

---

*End of document.*
