# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A local prototyping lab for enterprise agentic solutions targeting Azure, run entirely on an M1 MacBook with 8 GB RAM. The authoritative design is `docs/Local-Agentic-Prototyping-Platform.docx` (DOH Abu Dhabi EA, Draft v0.3) — read it before making architectural changes.

The goal is **pattern parity with Azure, not feature parity**: every prototype agent authenticates, egresses through a gateway, is metered, is PII-scanned, and is traced — exactly as in production. Application code uses the **Microsoft Agent Framework** so solutions migrate to Azure (Container Apps + APIM + AI Foundry) without rework.

## Debugging & Error Resolution (methodology — follow on ANY error or failure)

Resolve every error or failure by **root-cause analysis, never by guessing** — this is a principle,
not a last resort. Read the actual error, logs, and state; form a specific hypothesis about *why*;
confirm it against evidence **before** changing anything. Never pattern-match a fix and hope. Then
escalate through these steps in order, stopping the moment the cause is found:

1. **Clear error → fix it.** If the message names the cause unambiguously, apply the fix.
2. **Not immediately obvious → verify correct component usage via docs.** Pull the component's
   documentation through **context7** (`resolve-library-id` → `query-docs`) and check you are using
   it correctly. If the component — or its specific version — is **not in context7**, web-search for
   the official docs.
3. **Using it correctly but still failing → search for others' reports.** Web-search the exact
   error/symptom for similar issues faced by others and their resolutions (GitHub issues, forums).
4. **No similar findings → read the source.** If the component's source is available, read it to
   understand how it is actually meant to work and what triggers the failure.
5. **Spike locally for fast turnaround.** Whenever possible, reproduce and fix in a fast local loop
   before touching the slow/remote path — e.g. build+run the container locally (~70 s boot) before
   redeploying to Railway (~5 min build cycle). A local spike that isolates the cause is worth more
   than repeated remote guesses. (Reference: the Railway gateway 502 was solved this way — root-caused
   from deploy logs to an IPv4-edge-vs-IPv6-healthcheck bind mismatch, not guessed; see
   `deploy/railway.py` comments.)

## Code Quality Standards & Design Review (the ENTIRE codebase + all new code)

These goals apply to the whole repository, not just new work: a **baseline review of the entire codebase**
(three reviewers — today's new modules, the platform layer, the domain layer) is recorded under
`docs/reviews/`, its findings are implemented in priority order, and every new or changed piece of code
is written to, and reviewed against, the same bar — a standing standard, not a later cleanup:
- **DRY** — one home per piece of logic (shared helpers in `src/lab/platform/`; never re-derive a Redis/store/LLM
  client or a normaliser in a second module).
- **SOLID** — single responsibility per module/function; **open for extension**: adding an ArchiMate
  type, an input source/parser, a write path, an observability sink, or an agent step/mode must be a
  one-place change (registries/strategies), not edits across core files; depend on injected
  abstractions, not concrete env/Redis/HTTP/LLM clients.
- **YAGNI** — no speculative flags, params, or abstractions without a caller; smallest code for the need.
- **GoF patterns only where they simplify** — Strategy (mode/path selection), Factory (agents/tools/
  clients), Template Method (shared skeletons), Adapter/Facade (external systems), Observer (run-log),
  Registry (parsers/types). Never pattern-for-pattern's-sake.
- **Dependency injection** — configuration and clients enter through constructors/parameters or a
  single composition root; no `os.environ.get` buried in logic, no module-level clients, no `sys.path`
  hacks inside functions. **The framework is `dependency-injector`** (user decision Sep 3 2026):
  two composition roots and nowhere else declare `providers.*`: `lab.platform.container.Container`
  (config, redis, tracer — what a workload host gets; `build(service_name)` feeds it from `lab.platform.config`)
  and `lab.substrate.container.SubstrateContainer` (extends it with the artifact store — MCP servers, review
  app). Tests swap adapters with `container.<provider>.override(fake)`; the Azure move swaps adapters there or
  in `.env`, never in domain code. Guarded by `tests/governance/test_di_boundaries.py`
  (no platform name such as "railway" in production code; env reads confined to `config` + composition
  roots + a shrinking ratchet) and `tests/unit/platform/test_container.py`.
- **No dead code** — unused imports/params/paths and stale comments are removed in the same change.
- **Testability + TDD for production code** — pure logic separated from I/O; seams to fake
  Redis/LLM/store/HTTP; tests live in the repo (`tests/`), run offline without the gateway/LLM;
  deterministic `[D]` steps get unit tests, agent `[A]` steps get schema/contract tests. **Production
  code is developed test-first**: for anything imported by a running service or workflow (everything under
  `src/lab/` — core, platform, substrate, workloads — plus `deploy/railway.py`) write the failing test for the new
  or changed behaviour, make it pass, refactor — a production change without a test is incomplete.
  **Coverage target: ≥ 95 % line+branch per production file** (`tests/run.sh --cov`; today 99 %).
  **Exempt: spikes, experiments, one-off scripts and probes** (`scripts/` generators, scratchpad
  spikes, `scripts/e2e_smoke.py`-style probes) — but a spike that graduates into production code brings
  its tests with it when it graduates.
- **Abstraction layer -> adapters -> DI seam (the system's shape; user decision Sep 4 2026).** Every
  external dependency is reached through a PORT; a concrete realisation is an ADAPTER; the composition
  root wires them. Two KINDS, and the difference decides how much work an adapter is:
  - **Infrastructure ports** (generic, no domain meaning): ArtifactStore/UploadStore, Cache (Redis),
    Observability (tracer/exporter), Queue + Lock (streams), and — already satisfied by the gateway —
    Inference (`(base_url, credential)` + model name). Their adapters are usually **configuration, not
    code**: a URL scheme picks the store (`file://` | `s3://` | postgres), a URL picks Redis, an
    endpoint picks the OTLP target. Adding one (Azure Blob) = one class + one line in the ONE dispatch.
  - **Domain ports** (speak the ubiquitous language): EARepository, DocumentParser, DiagramRenderer,
    AgentIdentity. Their adapters need a **MAPPER** between the external model and ours (ADOIT
    `C_APPLICATION_COMPONENT` <-> ArchiMate `ApplicationComponent`; a `.vsdx` page <-> Source/Shape).
    The mapper is where correctness lives, so it is tested on its own, apart from any transport.
  **Placement follows the tiers**: a domain port is declared in `lab.core` (the domain states what it
  needs, imports nothing), an infrastructure port in `lab.platform`; ADAPTERS live where their
  credentials do (`lab.substrate`, or `lab.platform` when pure); only a composition root
  (`lab.platform.container` / `lab.substrate.container`) names an adapter. **DI is the seam** — tests
  swap any port with `container.<provider>.override(fake)`; the Azure move swaps adapters there or in
  `.env`, never in domain code.
  Everything else DDD stays as before: cohesive typed objects (dataclasses) that enforce their own
  invariants instead of shared mutable dicts + helper bags; a **ubiquitous language** (Workload, Source,
  Representation, Element, Relation, View, Domain/Folder, Approval, Repository object, canonical name)
  used identically in code, prompts and schemas; explicit **bounded contexts** (Ingestion/Reading ·
  Modelling · EA-repository write · Governance · Observability) with translation at the edges; the
  **domain core** (ArchiMate model + legality, canonicalisation, accumulators, repair) never imports
  Redis/LiteLLM/ADOIT/LibreOffice/Streamlit. **Not layers for their own sake**: a port earns its place
  only where it changes on Azure migration, needs faking in tests, or already has two implementations.
  **Status (measured Sep 4 2026)**: infrastructure is DONE — store adapter by URL (verified
  file/s3/postgres), Redis by URL, tracer by endpoint, inference by gateway config, and a workload
  container structurally cannot hold a store credential. **Domain ports are the gap**: `adoit_rest` is
  imported concretely (no EARepository port — the highest-value one, since it is the dependency that
  would actually change), `msal` is constructed directly in identity, parsers are concrete.
- **Scale & migration readiness** — the lab exists for **pattern parity with the Microsoft/Azure
  ecosystem** (Container Apps, APIM, AI Foundry, Entra, App Insights, Blob/Redis/Cosmos, Microsoft Agent
  Framework). Keep local specifics (LiteLLM-only calls, Redis key shapes, Railway/brew/LibreOffice host
  assumptions, local paths) behind seams so the move is configuration, not code; prefer Agent Framework
  primitives over bespoke orchestration where they exist.

**The `code-reviewer` agent** (`.claude/agents/code-reviewer.md`, read-only, reports ranked actionable
findings) enforces this. Run it: after each batch of new modules lands (e.g. a parallel-builder wave),
**before wiring new modules into core**, before a commit, and on request — `Agent(subagent_type=
"code-reviewer", prompt="review <files/scope>")`. Its findings on new code are implemented, not filed.

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
- **Workloads hold no store credentials.** Inputs reach a workload as `art://` refs and are read
  ONLY through the gateway's read-only **storage-mcp**; its own spec goes to `semantic_store_spec`.
  Bucket/DB credentials live in the substrate (storage-mcp, the review app that uploads) and
  `deploy/railway.py configure_workload()` strips them from every workload service.
- **Every workflow host sets a distinct OTel service name** (e.g. `process-1-intake`) so concurrent processes can be traced and audited independently.
- **Every MCP server lives in the SUBSTRATE; workloads are MCP CLIENTS only.** Five servers today:
  `adoit-mcp` (:9100), `semantic-mcp` (:9200), `storage-mcp` (:9300), `workflow-mcp` (:9400). A domain
  dependency's ADAPTER is its MCP server and the PORT is its tool contract (`lab.platform.contracts`) —
  swapping ADOIT for another EA tool means a different server satisfying the same tools, re-registered;
  no workload changes. The EA-repository port is **vendor-neutral**: alias `ea_mcp`, tools
  `ea_search|ea_object|ea_repositories|ea_stage_import|ea_import_status|ea_import_instructions`
  (catalogue `lab.platform.contracts.EATools`), guarded by
  `tests/governance/test_contracts_match_servers.py::test_no_tool_or_alias_names_a_vendor`.
  `archimate_validate`/`archimate_render` keep their names — they are domain ENGINE services, not
  repository operations. The vendor lives only in the SERVICE (`adoit-mcp`, `ADOIT_MCP_URL`, its
  credentials). `ea_stage_import` takes the model BY REF and returns the artifacts THAT repository
  needs a human to import plus the instructions — so ADOIT:CE's spreadsheet is a private adapter
  detail and a REST-capable tenant returns `artifacts: {}`. The APPROVAL is opaque too: kind `ea-import`, payload =
  the staged model (`xml_ref`/`svg_refs`) plus **`import_artifacts`** (`[{ref, label, note, media_type}]`,
  the typed `contracts.ImportArtifact`) and the adapter's own `instructions`. The review app RENDERS
  them — a download per artifact with its label and note — and knows nothing about spreadsheets; the
  adapter supplies the meaning, while filename/mime derive from the ref so it cannot mislabel its own
  file. Guarded by `test_nothing_downstream_of_the_ea_port_names_a_vendor_or_its_file_format`, which
  scans CODE (docstrings stripped, so prose may still explain the history) for a vendor OR a file
  format. Approvals staged before the change still open: nothing dispatches on `kind`, and legacy
  `*_ref` payload fields render as filename-labelled downloads.
- **A workload's EXTERNAL contract is an MCP server registered in the gateway, not an agent façade.**
  A workload is a deterministic workflow that CONTAINS agents; containment is not an interface.
  `<process>_submit(...)` enqueues and returns a `request_id` (runs take 600-1000 s — sync is
  impossible), `<process>_status/_result` query it. That keeps the typed contract (`Workflow.as_agent()`
  would coerce the typed start input to `list[Message]`) and reuses the ONE governed discovery
  mechanism: gateway MCP registry + per-team grants + metering + tracing. A2A stays BETWEEN agents
  (card ↔ virtual key ↔ Entra app); a workload-level A2A façade and a REST 202-enqueue surface are
  additive adapters over the same task contract, added when an orchestrator or a web/mobile client
  actually needs them. See `docs/decisions/2026-09-04-workload-external-contract.md`.
- **Every MCP server and every skill is registered in LiteLLM — no exceptions.** An MCP server
  goes into `config/litellm-config.yaml` `mcp_servers` (and is granted to teams via
  `object_permission.mcp_servers`); a skill goes into BOTH LiteLLM skill registries via
  `scripts/register_skill.sh <team_id>` — the runtime store (`/v1/skills`, agents consume it
  via `container.skills`) and the Skill Hub (UI → Skills / `claude-code/marketplace.json`,
  discovery). A tool or skill that exists only on disk is ungoverned and invisible to the
  registry; register it in the same change that creates it, and re-register after edits.

## Runtime Model

Business processes are Agent Framework **Workflows** — typed graphs orchestrating ChatAgents and deterministic functions (sequential, concurrent, handoff patterns; checkpointing; human-in-the-loop pauses). A shared services layer provides the workflow engine, the middleware chain (Presidio → approval gates → OTel emission), and MCP/A2A client integrations.

## Business Processes (`src/lab/workloads/`) — Agent Framework Workflows

**Adding a business process = ONE `ProcessSpec` in `lab.platform.contracts.PROCESSES`** (name, consumer
group, typed inputs, declared outputs). From that entry `workflow-mcp` GENERATES the three governed
tools `<process>_submit|_status|_result` with their JSON schemas, and `spec.validate()` is the single
input validator every external surface should use. `_submit` is enqueue-and-acknowledge — it publishes
one `workflow:requests` event and returns a `request_id` IMMEDIATELY (runs take 600-1000 s, so no tool
call may block on one). It takes an optional **`idempotency_key`**: the same key returns the same
`request_id` with `duplicate: true` instead of queueing a second 10-20 minute run. De-duplication lives
in `lab.platform.workflows.submit()` (`SET NX EX` on `workflow:idem:<process>:<key>`, **24 h**), so every
producer gets it by passing the argument, and the claim is taken atomically WITH the write. After the
TTL the same key queues a NEW run — it is a retry window, not a uniqueness constraint. A submit with
**no key is never de-duplicated by content**: re-running the same diagram is legitimate work, and
silently refusing what a human asked for is worse than a run they can see. Still manual per process: its consumer group in `workflows.GROUPS`, a consumer
host, `deploy/railway.py WORKLOADS`, and the LiteLLM team grant. `workflow_mcp` is granted to the teams
that TRIGGER processes (an orchestrator agent, a Copilot Studio connector) — never to a workload's own
agents.

Each business process is one host under `src/lab/workloads/<name>/` with a distinct OTel service name.
The first, `src/lab/workloads/visio_to_archimate/` (see its README), is the reference:

- **Runtime = a Microsoft Agent Framework `WorkflowBuilder` graph** (`agent-framework` on PyPI,
  package `agent_framework`; `OpenAIChatClient(base_url=<gw>/v1, api_key=<agent credential>)` +
  `Agent(...)`). Typed `@executor` nodes, `add_chain`, `wf.run(input)` → `get_outputs()`. One host
  process (`host.py`), root span, credential wiring; `agents.py`/`workflow.py` hold the agents/graph.
- **Client = `OpenAIChatClient` (the modern OpenAI *Responses* API, `/responses`, per AF ADR 0021)
  but forced STATELESS via `default_options=ChatOptions(store=False)`** (toggle `AGENT_RESPONSES_STORE`
  in `.env`, default false). Why: the gateway's Ollama Cloud upstream implements only the
  NON-stateful flavor of `/v1/responses` (verified — `store`/`previous_response_id`/`conversation`
  are inert), so AF's default stateful turn (previous_response_id + delta) makes the post-tool
  message come back EMPTY; `store=False` resends full context each turn and works. `base_url` ends
  in `/v1/`. Set `AGENT_RESPONSES_STORE=true` only against a Responses-stateful backend
  (Azure/Foundry). (`OpenAIChatCompletionClient` — Chat Completions — is the stateless alternative
  and also works; the native `agent_framework.ollama.OllamaChatClient` bypasses the gateway, off-limits.)
- **Agents ARE agentic — they call governed tools, but BY REFERENCE (small args).** BA calls a
  `read_vsdx(path)` tool; the Architect emits its spec as structured output, a deterministic node
  stores it (`art://` ref), and the Architect calls the gateway-MCP `semantic_validate_model` +
  `archimate_render` **by `spec_ref`**. This is the crux: small-arg tool calls are reliable
  (measured 5/5), but a large nested object passed INLINE as a tool argument is emitted only
  stochastically (AF #2747 flattens nested MCP params to bare `{"type":"object"}`), so never pass
  a spec inline — pass the ref. MCP results arrive as JSON strings and can be incomplete (AF #3313);
  a **deterministic fallback** (`_call_tools` by ref) guarantees the pipeline completes if a model
  skips a call on a given run. Both `archimate_render` and `semantic_validate_model` accept
  `spec`|`spec_ref` (and coerce a JSON-string spec → dict). Model: **kimi-k3**.
- **BA inputs = a diagram + optional requirements documents, BY REFERENCE, read ONLY through the
  gateway.** A person submits them on the review app's **Submit** mode (or `python -m
  lab.substrate.review.uploads upload <files>`): files land in the **upload store**
  (`UPLOADS_URL` — a Railway Bucket in the cloud, the Postgres artifact store locally; refs are
  `art://<id>/<name>`) and an explicit **Run** publishes a durable `workflow:requests` event
  (`src/lab/platform/workflows.py`, Redis Streams) that the long-lived `wf-visio` host
  (`src/lab/workloads/visio_to_archimate/consumer.py`) consumes, writing status/trace/approval back.
  **A workload holds NO object-store credentials**: refs are read through the gateway's
  **storage-mcp** (`src/lab/substrate/mcp/storage/server.py`, read-only: `storage_read_vsdx`,
  `storage_read_document`, `storage_get`, `storage_extract_figures`, `storage_list/info`), granted
  per team and metered/traced like any tool; the BA's spec is stored via `semantic_store_spec`.
  **Three input KINDS, and for a `.vsdx` TWO representations** — do not conflate them. A **`.vsdx`** is
  structured OOXML parsed deterministically AND (when the host can render) rasterised to a page image,
  so the BA RECONCILES structure with vision: the parse wins on element identity/text/native
  connectors, vision wins on grouping/containment and missing connectors, conflicts become
  `openQuestions`. Rendering is an OPTIONAL capability (`storage_render_vsdx`, LibreOffice + a
  rasteriser on the storage-mcp host, `SOFFICE_BIN` in `.env`): absent, the run degrades to
  structure-only AND SAYS SO in the BA message — it never fails. Only the rendered page carries an
  image, and the message names which page that is.
  **A Lucidchart export has NO `<Connects>` section at all** (verified on the real file — the old
  "empty instance geometry" note was a library limitation, not the file), but every
  `com.lucidchart.Line.*` shape carries `BeginX/Y`–`EndX/Y` in page coordinates. `lab.core.visio.geometry`
  recovers `from`/`to` by matching each endpoint to the nearest element bounding box: tolerance is
  **1.0 × the median element min-edge** (pages are inches at an arbitrary author scale, so an absolute
  length is meaningless), group offsets folded in, and rotated/flipped subtrees are SKIPPED and counted
  — a mis-placed relation survives the approval gate looking plausible, a missing one does not.
  Recovered links carry `recovered: "geometry"` + `match_distance`, and the parse carries a `recovery`
  block counting lines that yielded nothing, which the BA must raise in `openQuestions`. Measured:
  Sahatna **0 → 44 connectors, 244 → 214 shapes**; Malaffi native output byte-identical.
  A **diagram IMAGE** (png/jpg —
  no XML) is fetched by the deterministic BA node via `storage_get` and attached inline to the
  BA's message, read with vision (kimi-k3 / kimi-k2.7-code / glm-flash declare `vision` on Ollama
  Cloud; image parts pass through the gateway both as message content and as MCP ImageContent —
  verified; `supports_vision` is set in `litellm-config.yaml`); a **requirements document**
  (docx/pdf/md/txt) becomes text via `storage_read_document`, and its **embedded figures** are
  extracted server-side (`storage_extract_figures`) and attached as "figure N embedded in <doc>".
  Image sizing is enforced in ONE place (`src/lab/platform/docparse.py`): **≤1600 px** for images and
  document figures, **≤2400 px for a whole rendered page** (1600 px on a 16-inch page is ~100 dpi —
  captions unreadable, defeating the point); PNG/JPEG, <2 KB / <64 px decorations dropped, ≤8 figures/doc and documented in the `visio-reader` skill. Local
  paths still work for dev (parsed by the same helpers). Gotcha: fastmcp derives an outputSchema
  from a tool's return annotation — image-returning tools must have NONE, or clients fail with
  "outputSchema defined but no structured output returned". Requirements are evidence, not new
  boxes: a requirements-only element is added only if plainly part of THIS system (marked
  `source: requirements`), otherwise it is an `openQuestion`. Per-element **`provenance`
  `{source, representation}` is REQUIRED** by `ba_output.schema.json` and by the `[D]` gate (which
  expands the bare-string shorthand to the object form; both BA modes share one normaliser).
- **Agents never call each other directly — the workflow mediates via a typed contract.** The BA
  emits schema-validated JSON (`jsonschema`); a **deterministic gate rejects incomplete output**
  (one BA retry) before the Architect sees it. A2A-through-the-gateway is the future upgrade when
  processes split into separate hosts.
- **Identity per agent (docx model):** one Entra app registration ↔ one virtual key ↔ one agent,
  all in one team per process. `scripts/provision_visio_agents.py` is the pattern (extends
  `entra_provision.py` + `bootstrap_registry.py`, auto-refreshes `var/run/graph_token.json`, patches
  `.env` incl. the single-quoted `ENTRA_CLIENT_TO_KEY`). Agents authenticate with
  `lab.workloads.identity.agent_headers("<PREFIX>")` — MSAL client-credentials JWT (gateway maps it to the
  key), else the durable key. LLM calls use each agent's own credential (spend attributes per key);
  tool nodes use the identity that holds the MCP grants (here the Architect: `Tools.ADOIT`).
- **One trace per run** joins process→gateway→MCP: `propagate.inject(headers)` under the root span,
  the traceparent passed as the fastmcp `Client` headers AND as the ChatAgent `default_headers`
  (so gateway LLM spans join too). Verified: ~400 spans in one trace across
  `process-visio-to-archimate` + `litellm-gateway` + `semantic-mcp` + `adoit-mcp`.
- **Skills are consumed by composing the local `SKILL.md` into the system prompt** (the same file
  registered in LiteLLM — single source of truth) rather than gateway `container.skills` injection,
  because injection is team-scoped and these agents need no in-agent tool execution. Registration in
  LiteLLM is still mandatory (governance/discoverability) — `scripts/register_skill.sh <team_id>
  [skill] [env_var]` is now generalized (default `archimate-adoit`; also registers `visio-reader`).

## ADOIT MCP Server (own-built)

The ADOIT EA integration wraps the ADOIT REST API (Community Edition has no built-in MCP), built on the existing internal Python ArchiMate library (61 element types, role-based architect agents). FastMCP exposes typed create/read/update tools; validation runs against the library before any repository write. Read/query tools may be shared across processes; write tools are ACL-restricted to a dedicated EA Modeling Agent. ADOIT credentials live in `.env` (`ADOIT_USERNAME`/`ADOIT_PASSWORD`, plus `ADOIT_BASE_URL` and `ADOIT_REPO_ID`), alongside `OLLAMA_API_KEY`.

**The tenant runs ADOIT 18 (`GET /rest/2.0/version` → `productVersion 18.0.0`) but is BOC's hosted
Community Edition (`adoit-ce.boc-cloud.com`). REST *reads* work; REST *writes* are BLOCKED at the CE
edge (verified live Sep 3 2026).** Search and object read over REST work fully and power the
existing-architecture-aware step. But `POST/PATCH/DELETE /objects` return a BOC edge **block page**
("URL not available on this server") even though `OPTIONS` advertises the verbs and the same
credentials/IP read fine — it is a hosted-CE edge policy, not auth, not IP allowlist, not the request
body. So **true in-place REST writes are not available on this tenant**; the write path is human-gated
**file-import** (below). The granular REST write facade (`adoit_rest.create_object/patch_object/
delete_object/create_relation`, bodies verified against the tenant OpenAPI + BOC examples) is built but
**dormant behind `.env` `ADOIT_REST_WRITE`** (default false) — flip it only on a full/licensed ADOIT or
the Azure/Foundry target. The verified read surface (`src/lab/substrate/mcp/adoit/adoit_rest.py`):
- **Search** — `GET /rest/2.0/repos/{repo}/search?query=<url-encoded JSON>` (Basic auth). Query =
  `{"filters":[{"className":"C_APPLICATION_COMPONENT"} | {"attrName":"NAME","op":"OP_LIKE","value":"x"}],
   "scope":{"repoObjects":true,"models":true,"modObjects":true}}` — **a non-empty filter is required**
  (empty → 400). Items: `{id,name,type,artefactType(REPOSITORY_OBJECT|DIAGRAM|MODINST),metaName(C_*),
  groupId,modelId,modelName}`. Exposed as the read-only tool **`ea_search(name_like, class_name, scope, limit)`**.
- **Object detail** — `GET /rest/2.0/repos/{repo}/objects/{objId}` → attributes + relation slots
  (`{name, metaName(RC_*), targets:[{id,name,metaName,direction}]}`). Tool **`ea_object(object_id)`**.
- **Write (edge-blocked on CE)** — `OPTIONS` advertises `POST /objects` and `PATCH,DELETE /objects/{id}`,
  but the actual verbs return the CE edge block page. className/relclass maps are deterministic
  (CamelCase ↔ `C_UPPER_SNAKE`; relation ↔ `RC_UPPER_SNAKE`). The facade is ready for a write-capable tenant.

**Write path = human-gated file-import, TWO files, TWO purposes** (`ea_import_instructions`):
- **OBJECTS → Excel object-import** (the adapter's PRIVATE object-import file → `.xlsx`, `src/lab/substrate/mcp/adoit/adoit_excel.py`,
  bundled ENGLISH tenant template in `src/lab/substrate/mcp/adoit/templates/`). ADOIT's "Import objects from Excel"
  both **creates and updates** objects, matching each row on its **NAME** (found once → UPDATE in place,
  absent → CREATE, found twice → error). One sheet per element type; the generator fills the tenant's
  own template. **Relationships** are written on the source object's row in the `<Relation> (->TargetSheet)`
  column, value = target name (`;`-joined for several); ADOIT-specific roles (RACI/Vendor/Predecessor)
  are left unset. Both maps are **derived from the template at runtime** by normalized name-match
  (`_norm`) — the EN template's sheet names ARE the ArchiMate types ("Application Component", "Course of
  Action") and its relation labels ARE the ArchiMate relation names — so there is no hardcoded map to
  drift (swapping locales re-derives the sheet map; only non-English relation *labels* need `REL_ALIAS`).
  This is why object **names must stay unique** — the existing-aware step's job.
- **VIEWS → ArchiMate Model Exchange XML** (`archimate_render` → `.archimate.xml`). Imports the
  diagram/geometry. NOTE: ArchiMate import **always creates** objects in a new group — it does NOT
  match on identifier (verified: even with the native `id_<uuid>` identifier it duplicated). So it is
  the *views* path; the Excel file is what keeps objects de-duplicated and updatable. (The engine
  still emits ADOIT-native `id_<uuid>` identifiers — `_ident()` in `archimate_engine.py` — for valid
  XML and forward-compat with a tenant that does match on identifier.)

The repo already holds a real ~134-object landscape. The workflow is **existing-architecture-aware**:
a `resolve_existing` node searches ADOIT, an agent decides NEW vs UPDATE + matches BA elements to
existing object ids, the Architect **reuses those ids** (no duplicates) and folders by domain, and
the reviewer confirms update-vs-new at the approval gate; the run stages BOTH the Excel object file
and the ArchiMate views file for import.

## Local-first vs cloud toggles

The stack runs **fully local by default** except where the design forbids it. Each dependency is
one `.env` switch (cloud values kept as `# CLOUD:` comments for flip-back):
- **Redis** — local Homebrew (`REDIS_URL=redis://127.0.0.1:6379/0`, no password) or a managed
  instance (set `REDIS_URL`/`REDIS_PASSWORD`; `lab.sh` checks it instead of starting brew redis).
- **Tracing/Jaeger** — local native binary (`OTEL_* → 127.0.0.1:4318`, `JAEGER_UI_URL → :16686`;
  `lab.sh` starts `var/tools/jaeger`) or remote (Railway/App Insights: point `OTEL_*` at it; `lab.sh`
  skips the local binary and manages the Railway deployment if `RAILWAY_*` are set).
- **Postgres** — Neon (serverless, free-tier) stays cloud: no local server is installed and the
  key/team/spend data lives there. Going fully offline would need `brew install postgresql`, a
  `prisma db push`, and re-running `scripts/bootstrap_registry.py`.
- **Ollama Cloud, ADOIT:CE, Entra, GitHub** — external by nature; no local equivalent.

## Cloud Shape (no same-machine assumptions)

Everything stateful is managed: Neon (keys, spend, skills, **artifact store**), Redis Cloud
(limiter state, approval streams), Ollama Cloud, ADOIT, GitHub. The five Python processes are
stateless and address each other only through `src/lab/platform/config.py` env vars:
`GATEWAY_URL`, `ADOIT_MCP_URL`, `SEMANTIC_MCP_URL`, `REVIEW_APP_URL`, `JAEGER_UI_URL`,
`BIND_HOST` (0.0.0.0 in containers), `REDIS_URL`, `ARTIFACTS_URL`.
- **Trust**: `MCP_SHARED_SECRET` — both MCP servers enforce `Authorization: Bearer` via
  `src/lab/substrate/mcpauth.py`; the gateway sends it (`auth_type: bearer_token`). Never run with
  `BIND_HOST=0.0.0.0` and no secret. The review app has a `REVIEW_APP_PASSWORD` gate; on Azure
  put Container Apps Entra auth in front instead.
- **Artifacts by reference, never by path**: `src/lab/substrate/artifacts.py` stores export specs, XML and
  SVGs in a Postgres `lab_artifacts` table and hands out `art://<id>/<name>` refs. Tool contract:
  `semantic_export_archimate` → `spec_ref`; `archimate_render(spec|spec_ref)` → `xml_ref`,
  `svg_refs`; `ea_stage_import(xml_ref, svg_refs)`; the review app reads refs. `outdir` /
  `spec_path` remain as local-dev conveniences only.
- `deploy/Dockerfile` (one image, role by command), `deploy/substrate/compose.yml` (the cloud
  topology on any Docker host — unbuilt here: no daemon), `deploy/README.md` (Azure Container
  Apps mapping). `lab.sh` stays the single-machine runner with the same env contract.
- **Railway is the live cloud host (Hobby plan), two tiers, each deployed/torn down on its own**
  via `deploy/railway.py` (reads `.env`, `# CLOUD:` lines win, `$VAR` refs expanded):
  `substrate up|down|status` (redis → semantic-mcp, adoit-mcp, **storage-mcp**, gateway, review,
  + Jaeger), `bucket up|status` (the upload store: a Railway **Bucket**, S3-compatible; creates it
  once and writes `# CLOUD: S3_*` + `UPLOADS_URL` — which `configure()` hands ONLY to review +
  storage-mcp), `workload visio up|down|status` (service `wf-visio`, the long-lived consumer of
  `workflow:requests`, `restart=ALWAYS`) and `workload visio-job …` (the one-shot job). A workload
  references the substrate ONLY via the gateway's PUBLIC domain + Redis + tracing; it gets NO
  `DATABASE_URL/ARTIFACTS_URL/UPLOADS_URL/S3_*/STORAGE_MCP_URL`. Railway job gotchas, all verified:
  (1) a Dockerfile start command is exec'd WITHOUT a shell — `a && b` runs only `a`, so chains
  must be `sh -c '…'`; (2) a `restartPolicyType=NEVER` job reports SUCCESS whether it finished
  or crashed — `workload status` reads the run's log markers instead; (3) no volume mounts, so
  git-ignored generated inputs (`var/out/architecture/lab_model.json`, the `.vsdx` fixture) are generated
  at start; (4) the gateway must bind `0.0.0.0` with NO healthcheck (public edge is IPv4, the
  healthcheck probe is IPv6) and needs `DISABLE_SCHEMA_UPDATE=true`; (5) it's metered — the
  substrate 24/7 is ~$20–25/mo, so `substrate down` between demos.
- **ONE image, built once in CI, pulled by every service (Sep 4 2026).** `.github/workflows/image.yml`
  builds `deploy/Dockerfile` on push to `main` and pushes `ghcr.io/<repo>:main` + `:sha-<short>`;
  `deploy/railway.py` defaults to **image mode** (`BUILD_MODE`, override `LAB_BUILD=repo`), so every
  substrate role AND every workload is an IMAGE service pulling that same immutable tag and differing
  only in start command + env. Railway builds nothing: a deploy is N pulls, not N identical builds,
  and every role provably runs the same bits. Pin/roll back with `LAB_IMAGE_TAG=sha-<short>`; the GHCR
  package must be PUBLIC (or give the services a registry credential). Dockerfile speed rules, all
  measured: `python:3.12-slim` (not the full image — ~20 s of every build was export/push); node+npm
  COPYed from `node:22-bookworm-slim` because **prisma resolves BOTH `node` and `npm` globally and
  silently falls back to downloading its own nodeenv when either is missing** (that fallback fails
  with npm exit 127 — verified locally), while Debian's `npm` package pulls ~250 node-* packages;
  `uv` for the dependency layer; BuildKit cache mounts for apt+uv (a Railway REPO build needs
  cache-mount ids of the form `s/<serviceId>-<name>`, which one shared Dockerfile cannot satisfy —
  another reason image mode is the default); `prisma generate` ABOVE the source COPY (it depends only
  on litellm_proxy_extras, so a source edit no longer re-runs it); COPY order least-changing first.
  **A local Docker daemon IS available on this machine** — build and smoke-test the image locally
  (`docker build -f deploy/Dockerfile .`, then import every role's module) before pushing; that is how
  the prisma/npm defect was found instead of failing a cloud build.

## Architecture Modelling

Use the project skill `archimate-adoit` (`skills/archimate-adoit/`) for all ArchiMate
modelling and ADOIT export: it bundles a deterministic layout engine (orthogonal parallel
routing, layer bands, interfaces as icons), the ArchiMate 3.1 vocabulary, and the ADOIT:CE
import procedure. Keep generator scripts under `scripts/` so views are regenerable.
The engine originates from `~/Development/health-service-idp` (archi_layout.py / drawio_c4.py).

## Repository Layout & Tiers (restructured Sep 4 2026 — `src/lab` package, four tiers)

Source lives in ONE installable package (`pyproject.toml`, `pip install -r deploy/requirements.txt -e .`);
everything else at the root is configuration, deployment, docs, scripts or git-ignored runtime state:

```
src/lab/core/        domain: archimate/{engine,notation,relrepair,xsd}, semantic/ (vocabularies, SKOS, SPARQL), visio/ parsers, canon (names)
src/lab/platform/    kernel shared by every tier: config, container (DI root: config/redis/tracer), otel, redis_client,
                     runlog, workflows, docparse, filetypes, locks, staged_registry
src/lab/substrate/   the shared plane: gateway hooks (custom_auth, pii_guardrail, auto_router), mcp/{adoit,semantic,storage}
                     servers, review app (+ uploads), channels/telegram, approvals, artifacts, mcpauth, mcpserver, specref,
                     container (DI root extending the platform one with the artifact store)
src/lab/workloads/   business-process hosts: visio_to_archimate/{host,consumer,devui_entry,workflow,agents,…}, identity,
                     accumulator, ids, workflowviz
skills/              the REAL skill dirs (SKILL.md, references/, thin scripts/ wrappers over lab.core); .claude/skills/<n> symlink here
config/              litellm-config.yaml, clients/ (client templates), jaeger-railway.yaml
scripts/             provisioning, registry bootstrap, register_skill.sh, architecture generators, e2e_smoke, spikes/
deploy/              Dockerfile, railway.py, requirements(.txt|-dev.txt), substrate/compose.yml, workloads/<name>/compose.yml
docs/                the design docx, workload READMEs, reviews/
tests/               unit/<tier mirror of src/lab> · integration/ (local Redis) · governance/ · deploy/ · fixtures/ · conftest.py
var/   (git-ignored) logs/ run/ artifacts/ out/ inputs/<process>/ tools/ coverage/ reference-sources/ — `config.VAR_DIR` (env LAB_VAR_DIR)
```

**Import rules between tiers** (enforced offline by `tests/governance/test_import_boundaries.py`, ast-based):
`core` imports only `core`; `platform` imports `platform` + `core`; `substrate` and `workloads` import anything
below them; **`workloads` never import `substrate`** (a workload reaches the substrate only over the network:
gateway URL, Redis, tracing — the same seam as Azure Container Apps → APIM) and `substrate` never imports
`workloads`. A module's tier is decided by who imports it (a helper used by both tiers is `platform`; one
used by one tier lives in that tier) — no catch-all "shared". The exception ratchet in the test is EMPTY; keep it so.

**Tests mirror the code**: a change to `src/lab/<tier>/<path>.py` has its tests in `tests/unit/<tier>/<path>/`
(`test_<module>.py`, `test_<module>_more.py`); shared doubles live in `tests/fixtures/` (`fakes.FakeRedis`,
`patched_client`, …); tests that need the local Redis go under `tests/integration/` and skip themselves when
it is unreachable. `tests/run.sh [--cov]` is the authoritative run — **ONE pytest process** (`pytest tests`, 563 tests,
99 % coverage, `fail_under = 95`). It used to be one process per file because 11 modules pinned
`os.environ`/config at IMPORT time; they now pin it in fixtures, and `tests/conftest.py` closes the
process-global seams for everyone: `os.environ` and the OTel tracer provider are snapshotted and
restored around EVERY test, and — the root cause nobody had named — **`import litellm` calls
`load_dotenv()`**, which poured the real `.env` (Entra client secrets, the Neon `DATABASE_URL`, the
cloud `REDIS_URL`) into the suite and made a "unit" test fetch a LIVE MSAL token; that import is now
done and undone once before collection. Pin env with `monkeypatch`/fixtures, never at import.
`tests/run.sh --per-file` is the diagnostic fallback: a test that passes there but fails in the single
process is leaking process-global state.

## Commands

Everything runs from the project venv (Python 3.12 — litellm needs ≥3.11; never pip install --user):

```bash
.venv/bin/pip install -r deploy/requirements.txt -e . -r deploy/requirements-dev.txt   # once per venv (lab package + pytest)
tests/run.sh [--cov]                             # the whole suite (per-file pytest processes); --cov = branch coverage report
./lab.sh up | down | status                      # THE way to run the stack: redis, adoit-mcp, gateway
                                                 # (waits for health, strips ambient creds, var/logs/ + var/run/ pids)
# individual pieces, if ever needed:
set -a && source .env && set +a                  # all services need the env
.venv/bin/python -m lab.substrate.mcp.adoit.server         # adoit-mcp (port 9100, /mcp)
.venv/bin/python -m lab.substrate.mcp.semantic.server      # semantic-mcp (port 9200, /mcp)
.venv/bin/python -m lab.substrate.mcp.storage.server       # storage-mcp (port 9300, /mcp) — read-only upload store
.venv/bin/python -m lab.substrate.mcp.workflow.server      # workflow-mcp (port 9400, /mcp) — the workload front door
./lab.sh channels                                # restart just the CONFIGURED approval channels (teams / telegram)
.venv/bin/python -m lab.substrate.review.uploads upload <files>   # stage inputs in the upload store -> art:// refs
./lab.sh consumer                                # wf-visio: long-lived host consuming workflow:requests (Submit -> run)
.venv/bin/python -m lab.platform.workflows list        # run requests + status (request <process> <refs…> to publish one)
env -u ANTHROPIC_API_KEY .venv/bin/litellm --config config/litellm-config.yaml --port 4000   # gateway (no ambient creds)
.venv/bin/python scripts/lab_model.py       # regenerate lab_model.json spec
.venv/bin/python scripts/run_via_gateway.py # agent path: validate+render via gateway
```

Outputs land in `var/out/architecture/` (`lab-architecture.archimate.xml` + one SVG per view).
Element ids in `lab_model.py` are stable on purpose — changing them duplicates objects on
ADOIT re-import.

## Identity (Entra ID — real tenant, per the design doc)

Tenant `socratesbusiness.onmicrosoft.com` (`ENTRA_TENANT_ID` in `.env`). Provisioned by
`scripts/entra_provision.py` (Microsoft Graph; idempotent by display name; get a Graph token
via device-code sign-in when re-running): app **lab-gateway** exposes `api://…`
(`ENTRA_GATEWAY_AUDIENCE`) with app roles `EA.Model`, `Tools.ADOIT`; app **ea-modeling-agent**
holds a client secret and is granted both roles (appRoleAssignment = admin consent). One app
registration per agent, paired 1:1 with its virtual key (key metadata + `ENTRA_CLIENT_TO_KEY`
in `.env` — JSON, must be single-quoted or `.env` sourcing breaks).

- **Agents authenticate with MSAL** (`src/lab/workloads/identity.py: agent_headers()`), client-credentials
  against `<audience>/.default`; falls back to the static virtual key when no client id is set.
- **The gateway validates JWTs** in `src/lab/substrate/gateway/custom_auth.py` (`general_settings.custom_auth`,
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

- **Two portable credential shapes** (both map 1:1 to APIM, so client config never changes on
  migration): a **short-lived Entra JWT** (validated by `src/lab/substrate/gateway/custom_auth.py` via Entra
  JWKS/audience/issuer — the APIM `validate-jwt` equivalent) or a **durable per-user key**
  (LiteLLM virtual key ↔ APIM subscription key). Client contract is always `(base_url, credential)`.
- **JWT acquisition is Microsoft-standard `az`, no bespoke script**: `az login --tenant < id>`
  once (browser), then `az account get-access-token --resource $ENTRA_GATEWAY_AUDIENCE`. The
  Azure CLI public client is pre-authorized on lab-gateway for `access_as_user` (Graph). Claude
  Code uses that as its `apiKeyHelper` one-liner; other clients pass the token as a bearer.
  (`gateway/dev_login.py` device-code flow retired — az supersedes it and is APIM-faithful.)
- **JIT keys (JWT path)**: `src/lab/substrate/gateway/custom_auth.py` recognises user JWTs (`scp` contains
  `access_as_user`) and provisions a personal virtual key on first use (team `developers`,
  $10/30d, oid→key in Redis, via the internal `generate_key_helper_fn` — never a self-HTTP call).
- **Durable keys (self-serve SSO — for GUI/paste-only clients without `az`)**: LiteLLM UI SSO is
  Entra (`MICROSOFT_CLIENT_ID/SECRET/TENANT`, `PROXY_BASE_URL` in `.env`; app `lab-gateway-ui`
  registered by `scripts/entra_ui_sso_provision.py`, redirect `<PROXY_BASE_URL>/sso/callback`).
  A developer opens `<gateway>/ui`, signs in with Entra, lands on a NON-admin self-serve view
  (`default_internal_user_params: user_role=internal_user` + developer model allowlist + budget;
  `ui_access_mode: all`), and copies a durable key to paste into any client. The master key stays
  admin. This is the APIM Developer-Portal experience, one version early. Self-serve keys inherit
  the developer model allowlist from `default_internal_user_params` (user-level restriction — a
  new key with no explicit models inherits it and rejects anything off-list, verified); the
  gateway adds SSO users to the `developers` team for spend rollup (team join is per-user today —
  `POST /team/member_add` — Entra group→team mapping is the enterprise upgrade).
- Agents (client-credentials, `roles` claim) unchanged.
- **Any client, swappable harness**: Claude Code, OpenCode/Codex, IDE plugins, browser, OpenAI-
  standard tools all use the same `(base_url, credential)`. **Committed templates + per-client
  setup live in `config/clients/`** (`config/clients/claude-code/settings.json` copies into any project's
  `.claude/settings.json`). Claude Code enumerates the full gateway catalogue in `/model` via
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`; `ANTHROPIC_MODEL=auto` uses the intent router.
  The two per-deployment values live only in `.env` (`GATEWAY_URL`, `ENTRA_GATEWAY_AUDIENCE`);
  `./lab.sh clients` (also run on `up`) renders `config/clients/*/settings.template.json` →
  git-ignored `settings.json` — so moving the gateway to a cloud host or APIM is an `.env` edit,
  never a template change.
- **`auto` routing** (`src/lab/substrate/gateway/auto_router.py`): **LLM-classified** — glm-flash (called
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
- **Team per business process, virtual key per agent** — `scripts/bootstrap_registry.py`
  created team `ea-modelling` and key alias `ea-modeling-agent` (`EA_AGENT_KEY` in `.env`,
  2 USD/30d, 30 rpm, 60k tpm). MCP access is granted per team:
  `POST /team/update {"object_permission":{"mcp_servers":["ea_mcp"]}}` — a key with no grant
  sees zero tools (verified). Per-tool ACLs use `mcp_tool_permissions` on the same object.
- **Metering**: Ollama Cloud is flat-rate, so `litellm-config.yaml` carries nominal per-token
  prices; every call returns `x-litellm-response-cost` and spend rolls up key → team.
- **Redis** backs limiter/budget/router state (via `litellm_settings.cache` with
  `supported_call_types: []` — LLM responses are never cached) and the approval streams.
  **Since Aug 30 2026 it is Redis Cloud (Azure East US)** — `REDIS_URL/HOST/PORT/PASSWORD` in
  `.env`; `lab.sh` checks it instead of starting brew redis when `REDIS_URL` is set. Measured
  cost from the UAE: ~180 ms RTT × ~20 sequential gateway Redis calls ≈ **+3.8 s per gateway
  request** (4.75 s vs 0.95 s direct). That is geography, not Redis: it vanishes once the gateway
  itself runs in the same Azure region. **The cloud tier does exactly that (Sep 2026): Redis runs
  INSIDE the Railway substrate** (`redis:7-alpine` image service + `/data` volume, `# CLOUD:
  REDIS_URL=redis://redis.railway.internal:6379/0` in `.env`) — Redis Cloud's 30-client free-tier
  cap was blown by LiteLLM alone (two 50-connection pools + pub/sub subscribers per gateway; the
  cloud workload's approval publish died with "max number of clients reached"). Redis there must
  bind `0.0.0.0 ::` (Railway private DNS is IPv6-only). Local `lab.sh` still uses brew Redis. Until then, the local brew redis is a one-line fallback
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
  prompt. Re-register after editing the skill: zip `skills/archimate-adoit` and
  `POST /v1/skills?beta=true -F custom_llm_provider=litellm_proxy -F display_title=archimate-adoit -F "files[]=@skill.zip"`
  — **`custom_llm_provider=litellm_proxy` is mandatory**: without it LiteLLM forwards the upload
  to Anthropic's cloud skill store (ids `skill_…` instead of `litellm_skill_…`). Use
  `scripts/register_skill.sh <team_id>` — it also sets ownership to `team:<id>` (the injection
  hook only serves skills whose `created_by` is in the caller's scopes; admin-created skills are
  invisible to agent keys) and updates `.env`. Restart the gateway afterwards (60 s skill cache).
  LiteLLM has TWO skill registries: (a) `/v1/skills` runtime store above — what agents
  consume via `container.skills`; (b) the **Skill Hub** (UI → Skills, served as
  `/claude-code/marketplace.json`, API `/claude-code/plugins`) — discovery for people and
  Claude Code clients. `register_skill.sh` maintains both. The Hub needs a git source with a
  dot-free path, hence the `skills/archimate-adoit -> skills/archimate-adoit` symlink;
  the source is the GitHub remote (`https://github.com/shlapolosa/local-agent-lab.git`,
  derived from `origin` by `register_skill.sh`; local `file://` only when no remote). Clients add
  it with `claude plugin marketplace add http://127.0.0.1:4000/claude-code/marketplace.json`.
- **Ambient credentials**: the user's shell exports `ANTHROPIC_API_KEY`; the gateway must NOT
  inherit it (that is how the skill upload leaked to Anthropic once). Launch services with
  `env -u ANTHROPIC_API_KEY` — only `.env` values are lab credentials.

## PII / Secret Guardrails (regex tier — LIVE; Purview/Defender analogue, first layer)

Versioned in `config/litellm-config.yaml` `guardrails:` — built on LiteLLM's local
`litellm_content_filter` (prebuilt regex patterns, ~1 ms, no external service), `default_on`
so it fires for EVERY credential and BOTH API standards (OpenAI `/v1/chat/completions` and
Anthropic `/v1/messages`) — covering the two use cases: developers consuming models (e.g.
Claude Code via the gateway) and the agentic solutions.
- **Policy: REVERSIBLE PSEUDONYMIZATION, no blocking** (`src/lab/substrate/gateway/pii_guardrail.py`, a custom
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

## Semantic Layer (`src/lab/core/semantic/`, served by `semantic-mcp` :9200)

Vocabularies as **data**, not prose: a `Vocabulary` (classes with layer/aspect facets and
definitions, relation types, the permitted source→relation→target matrix, modelling rules)
renders to RDF; a `Registry` holds many; a `SemanticStore` (rdflib, in-process, named graphs)
holds vocabularies + instance models and answers SPARQL over all of them. ArchiMate 3.1 is the
first vocabulary: `src/lab/core/semantic/archimate/taxonomy.json` (classification, distilled from the cheat
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
  semantics) when `src/lab/core/semantic/` is importable, coarse otherwise; every exported element's
  documentation is prefixed with its `[Layer · aspect — Type]` classification.
- **Interfaces have their strict meaning**: an interface is the access point of a service —
  `Composition owner→interface` plus **`Assignment interface→service`**; a consumed service without
  an assigned interface is a warning. Functions are the decomposition unit (component assigned
  to function, function realizes service); business channels are `BusinessInterface`s realized by
  the `ApplicationInterface` that implements them.
- **Reference models are a second KIND of vocabulary — SKOS concept schemes** (`src/lab/core/semantic/skos.py`,
  `src/lab/core/semantic/reference/baguild.py`): the BA Guild Healthcare Provider v2.0 and Insurance v5.0
  models are loaded from their ORIGIN workbooks (capability map L1–L4 with tiers, value streams,
  and — insurance — organisation, stakeholder and information maps). The workbooks are licensed:
  they live in `var/reference-sources/` (git-ignored) or `REFERENCE_MODELS_DIR`; only derived
  RDF exists at runtime. Same-label top capabilities across schemes are linked by
  `skos:exactMatch` in a mappings graph — schemes are never merged. Stable concept ids are
  hashes of the full label path (the workbooks carry no ids).
- **Writing reference capabilities into ADOIT is a two-server operation**: `semantic-mcp`
  `semantic_export_archimate(scheme, root_label, depth)` projects a subtree to an ArchiMate spec
  (Capability + Composition, an L1 overview view in rows, one nested view per top concept —
  capability maps nest by convention, the one sanctioned use of containers); then `adoit-mcp`
  `archimate_render` + `ea_stage_import` render and stage it for approval like any model.
  `scripts/export_capabilities.py <scheme> [root] [depth]` runs that chain via the gateway.
- **Placement**: `semantic-mcp` is a separate, credential-free, read-only server granted to every
  team; `adoit-mcp` stays the governed EA-repository facade. Both import the same package.

## Approval Gate (human-in-the-loop for EA repository writes)

Event-based over the Redis already running — **Redis Streams**, not pub/sub, because approvals
must be durable and acknowledged. The same mechanism runs the OTHER direction too:
`src/lab/platform/workflows.py` publishes **run requests** (`workflow:requests`, one consumer group per
workload host, hash `workflow:req:<id>` with status pending|running|done|failed + trace/approval
ids written back by the consumer) — what the review app's Submit mode emits and
`src/lab/workloads/visio_to_archimate/consumer.py` consumes. `src/lab/substrate/approvals.py` is the approval API:
`request()` publishes to `approvals:requests` (one consumer group per channel:
`review-app`, `telegram`, `teams` — each channel sees every request); `decide()` appends to
`approvals:decisions` (the audit log) with `approve | decline | update` (= changes requested,
stays open), actor, channel, comment; `status()/await_decision()` for the requester.

- **Write path is two MCP tools**: `ea_stage_import` (publishes the event, returns id,
  writes nothing) → human decision → `ea_import_status` (decision + next step). On
  ADOIT:CE "approve" releases the XML for the UI import; on a full tenant the REST write runs
  inside that tool after approval. The tool never writes without a decision.
- **Channels**: `src/lab/substrate/review/app.py` (Streamlit, `./lab.sh review`, :8501) shows views, model
  contents, trace link, and takes the decision; `src/lab/substrate/channels/telegram.py` is the same contract
  as plumbing only (enabled by `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`; no diagrams — summary
  + link to the review app); **`src/lab/substrate/channels/teams.py` is the Microsoft Teams channel**
  (`TEAMS_WEBHOOK_URL`; unset = disabled) — it posts an **Adaptive Card** with the summary, violations
  flagged in red, and `Action.OpenUrl` buttons to the review app and the Jaeger trace (no diagrams in
  the card). Its inbound has TWO paths: the deep link back to the review app (wired today — a Teams
  incoming webhook is SEND-ONLY, so `Action.Submit` cannot come back without a bot registration), and
  `TeamsChannel.decide(request_id, decision, actor, comment)` for a Copilot Studio connector / Teams
  bot to call with the **signed-in user as `actor`** — a blank actor RAISES, never defaults, because
  "who approved this EA write" is the audit log's whole point. `python -m lab.substrate.approvals
  approve|decline|update <id>` is the CLI channel. Adding a channel = a new consumer group name in
  `CHANNELS` + a consumer (`CHANNELS = ("review-app", "telegram", "teams")`).
  Channels are **started by `lab.sh`** (`up` starts every CONFIGURED one after the review app and skips
  the rest with a line saying which setting is missing; `./lab.sh channels` restarts just them) and
  **deployed by `deploy/railway.py` as OPTIONAL substrate services** (`CHANNELS`, `restart=ALWAYS`, no
  ingress) with a channel-only ROLE_ENV allowlist — its own token, `REDIS_URL`, `REVIEW_APP_URL`,
  tracing; NO Postgres, S3, `MCP_SHARED_SECRET`, gateway/model/ADOIT/Entra credential, and neither
  channel gets the other's token. Adding a channel = one `for_each_channel` line in `lab.sh`, one
  `CHANNELS` row and one `ROLE_ENV` row, kept honest by a parity test that reads `lab.sh`'s own table.
  **The gate is also a governed TOOL surface**: `workflow-mcp` carries `approvals_list` /
  `approvals_get` / `approvals_decide` (`lab.substrate.mcp.workflow.approval_tools`, catalogue
  `contracts.ApprovalTools`), so a channel that authenticates its OWN human — a Copilot Studio agent in
  Teams — decides through the gateway, granted/metered/traced like any tool. It sits on workflow-mcp
  because a run PAUSES for an approval (`<process>_status` returns the `approval_id`): one server, one
  grant, one connector. `approvals_decide` requires the signed-in human as `actor` (blank REFUSED),
  records the channel as `mcp:<channel>` so a relay is never logged as a review-app decision, and is
  granted SEPARATELY from the read tools via `mcp_tool_permissions` (`ApprovalTools.READ` / `.WRITE`).
  **Never grant `workflow_mcp` to a workload's own agents, and never without the tool list** — an agent
  could otherwise approve its own run (ratcheted by
  `test_no_grant_hands_a_team_the_human_approval_write_by_accident`).
  **Every human channel records through `approvals.human_decision`** — identified actor, a decision from
  the contract, request still open, and ONE final answer claimed atomically on `approvals:pending`
  (`SREM`) because there are now several concurrent writers. `approvals.decide` is the raw recorder and
  must not be called from a channel.
  **Stated exception to gateway-only egress**: a channel posts outward DIRECTLY (Telegram API, Teams
  webhook). That is SUBSTRATE egress, never a workload's, to a fixed configured URL, carrying only
  counts, ids and links — no model content. A NEW outbound path either goes through the gateway or is
  added here deliberately.
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
localhost, so `config/jaeger-railway.yaml` (0.0.0.0 receivers, memstore) is injected as the
`JAEGER_CONFIG` variable with start command `/cmd/jaeger/jaeger-linux --config env:JAEGER_CONFIG`
(Railway replaces the entrypoint; the binary path comes from the image config). In-memory
storage. **Both endpoints are public and unauthenticated** — acceptable for a lab whose spans
carry no PII, not for anything else; front them with auth before workflow hosts emit real data.
The native binary in `var/tools/jaeger/` is the local fallback: `lab.sh` starts it only when
`OTEL_EXPORTER_OTLP_ENDPOINT` points at localhost. **Railway is metered (trial credit): stop it
when not in use** — `lab.sh down` removes the Railway deployment and `lab.sh up` redeploys it
whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is remote and `RAILWAY_TOKEN` is set (spans sent while
it is down are simply dropped by the exporters; nothing else breaks). Topology view: Jaeger → System Architecture
(from traces); on Azure, Application Insights → Application Map from the same spans.

Three hops emit into ONE trace per workflow run, joined by W3C `traceparent`:
- A run is closed in exactly ONE place — `runlog.finish_from()` / `runlog.error_text()` — and
  **a `fail` node means the run failed for EVERY host**, not just DevUI. DevUI rows carry the
  approval and artifact refs (the output arrives as an AF `output` event on the stream), so a
  DevUI run is as useful on the Runs board as a CLI one.
- **Workflow/agent process** — root span `ea-modeling-run`, `service.name=process-ea-modelling`
  (`scripts/run_via_gateway.py` is the reference: one distinct service name per business
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
