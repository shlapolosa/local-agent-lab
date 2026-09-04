# Consolidated review → implementation plan — 2026-09-03

Sources: `2026-09-03-A-new-modules.md`, `2026-09-03-B-platform.md`, `2026-09-03-C-domain.md` (the `code-reviewer` agent,
lenses per `.claude/agents/code-reviewer.md`). Policy (CLAUDE.md): findings are implemented in priority order, not filed.

## Priority 0 — security / invariant holes (wave 1, now)
- B-H1 PII guardrail + auto-router skip `/v1/responses` (the agents' path) → mask `input`/`instructions` + Responses output.
- B-H2 workloads receive the whole `.env` → per-role allowlist in `deploy/railway.py`.
- B-L2 `mcpauth` logs a token prefix → sha256 fingerprint. B-L4 Neon key in `.claude/settings.local.json` → `.gitignore` + rotate.

## Priority 1 — correctness bugs (wave 1)
- A-F7 temp-file collision in `docparse.vsdx_dict` (concurrent page reads). A-F4 Runs-board node ids from executor ids.
- C-H3 `resolve_existing`: Architect identity + fail-loud (search_failed → approval summary). C-M6 gate `resolve` output on its schema.
- C-H1 `lru_cache` on `_semantic()` (~1.7 s per validate/render). A-F8 + C-L1 contradictory skill docs (stencil = primary
  evidence; `type_hint`; CE REST truth) + re-register skills.

## Priority 2 — DRY consolidation (wave 1, disjoint files)
- A-F1/F2/F3 `src/lab/workloads/accumulator.py` (Template Method), `src/lab/workloads/ids.py` (`rid`), `shared/canon.squash()` (one normaliser).
- B-H4 `src/lab/platform/redis_client.py` (single cached client) used by approvals/workflows/locks/staged_registry/runlog/custom_auth.
- C-M1/M2 `src/lab/platform/otel.py`, `src/lab/substrate/mcpserver.py`, `src/lab/substrate/specref.py` — replace five OTel copies, three server bootstraps, two spec loaders.
- C-H2 one taxonomy file (symlink), engine `_TYPES`/aspect derived from it. C-M3 `REL_STYLE` → `archimate_notation`.
- B-L3 one content-type table. A-F12 `make_cfg()` shared by host + DevUI (adds `run_id` to DevUI). A-F13 runlog retry latch + `client=` seam.

## Priority 3 — dead code + YAGNI (wave 1)
- All three §5 lists. Revert `pymupdf` until `render_vsdx` has a caller (LibreOffice-in-container is a separate decision).
- Decide the REST facade: keep behind the toggle **only** with the gated changeset tool it promises — else delete (kept for now: it is the documented full-tenant path; the changeset tool is the Phase-2 target).
- Delete `deploy/docker-compose.yml`; label `bootstrap_registry.py` historical; confirm/delete OCI scripts; `doc_role.schema.json` parked until its step lands.

## Priority 4 — tests (wave 2, after wave 1 lands so tests target the refactored code)
- Rescue scratchpad tests (canon/locks/staged_registry) **immediately** (done in wave 1 by the coordinator).
- `tests/` + pytest: docparse fragment/kind; adoit_excel.generate; read_lucidchart type_hint (+native negative); semantic
  matrix contract; engine golden render; model_rdf derivation; SKOS projection; workflow pure fns; railway env loader;
  artifacts LocalStore; auto_router rules; pii round-trip + Responses-shaped body; custom_auth claims map; streams.

## Policy adopted 2026-09-03 — TDD for production code
Production code (`src/lab/platform/`, `mcp/`, `src/lab/workloads/`, `gateway/`, `src/lab/core/semantic/`, skill engines) is test-first from now on;
spikes, experiments, one-off scripts and probes are exempt (a spike that graduates brings its tests). Wave-1 builders were
told mid-flight to add tests for the production modules they touch; wave 2 fills the remaining gaps.

## Priority 4a — split `.env` into role-scoped files + sealed secrets (wave 2, after W1b's allowlist lands)
Today `railway.py` only does `variableCollectionUpsert` (no sealing, no `${{shared.}}` refs) and the 90-line `.env`
(19 secret-looking keys) is uploaded to every service. Target: `env/common.env` (addresses only) + one file per role
(`gateway`, `adoit-mcp`, `semantic-mcp`, `storage-mcp`, `workload`, `review`) that IS the least-privilege policy;
`lab.sh` sources common+role per service; `railway.py` uploads the same pair per service and marks secret-classified
keys **sealed** (verify the GraphQL API supports it; the UI does); `.env` shrinks to local overrides. Maps 1:1 onto
Azure Key Vault / Container Apps secret scopes. Builds on B-M4 (`shared/envfile.py`) and W1b's `ROLE_ENV`.

## Priority 4b — OO / DDD / hexagonal quick wins (wave 2, small + safe)
- B-O5 `ArtifactRef` value object (one grammar incl. `#page`; replaces `_split` + `split_fragment` + two prefix literals).
- B-O1 / C-O5 `ArtifactStore` Protocol + `ArtifactInfo` + `BACKENDS` registry (Azure Blob = one leaf adapter).
- C-O4 lift `openpyxl`/glob/`REFERENCE_MODELS_DIR` out of `src/lab/core/semantic/reference/` behind a `ReferenceModelSource` port
  (unblocks offline domain tests; compounds with the `lru_cache`).
- B-O6 approval payloads carry `summary_lines` built by the producer; src/lab/substrate/channels/review render any approval kind.
- Dead: `state["path"]` (written, never read).

## Priority 5 — structural (with / after the multi-request workload refactor)
- **Typed workflow messages** (A-D1 / C-O2): `SystemDescription`/`BaOutput`, `ExistingArchitecture` (+`search_failed`),
  `ModelSpec`, `StagedModel` frozen dataclasses as the AF message types — same pass as `RunContext`; `standard_views`
  becomes a render argument. **Anti-corruption layer** `translate.ba_to_spec(...)` (A-D3); pin the ubiquitous language
  (`src/tgt`, one word for domain/folder/group, disambiguate view/node) at the schemas + MCP signatures (C-O3, with M5).
- **`Model` owns ArchiMate legality** (C-O1): inject the vocabulary; `rel()` guards; accumulator + relrepair delegate;
  one `build_model(spec)` (A-D2).
- **Ports**: `ToolGateway` (the APIM seam — A-D5), `EAWritePath` Strategy (A-F15 / C-O5), `RunLog`/`Lock`/
  `StagedRegistry` interfaces, `TokenSource` + `AgentIdentity` (B-O3), Governance typed events + `EventStream`
  (B-O2, subsumes B-H4's streams.py), then ONE composition root `shared/composition.build(role)` (B-O4 — last).
- C-H4 `RunContext` + module-level executors + `BA_MODES` Strategy (A-F9). A-F5 run-log as AF event observer (`run_stream`).
- A-F15 `WritePath` adapter (XML views | Excel objects | REST). C-§4 parser Registry; **process registry** (GROUPS, generic
  consumer, Submit dropdown). B-H5 `deploy/topology.py` + `CloudTarget`. B-M1 `ArtifactStore` Protocol + pool. B-H3
  `gateway/graph.py`. B-M4 `shared/envfile.py`. B-M5 `lab.sh start_service`. C-M3 engine split. C-M5 enum single-source.
  Packaging: `pyproject.toml`, engine as a real module.

## Wave 1 partition (parallel builders, disjoint files)
- **W1a gateway security** — `src/lab/substrate/gateway/pii_guardrail.py`, `src/lab/substrate/gateway/auto_router.py`, `src/lab/substrate/mcpauth.py`, `.gitignore`.
- **W1b deploy least-privilege + dead files** — `deploy/railway.py`, `deploy/docker-compose.yml`(rm), `deploy/README.md`,
  `deploy/Dockerfile`, `scripts/e2e_smoke.py`, `deploy/requirements.txt` (pymupdf), `deploy/oci_*`, CLAUDE.md compose line.
- **W1c shared scaffold + MCP servers** — `shared/{redis_client,otel,mcpserver,specref}.py`, `shared/{docparse,artifacts,
  runlog,approvals,workflows,locks,staged_registry}.py`, `src/lab/substrate/gateway/custom_auth.py`, `mcp/*/server.py`, `scripts/*.py`.
- **W1d domain** — `src/lab/core/semantic/*`, `src/lab/core/archimate/{archimate_engine,archimate_notation}.py`, skill docs
  (both skills), `src/lab/substrate/review/app.py`, `src/lab/workloads/visio_to_archimate/consumer.py`, skill re-registration.
- **W1f accumulators + normaliser + ids** — `shared/{accumulator,ids,canon}.py`, `src/lab/workloads/visio_to_archimate/{ba_tools,
  architect_tools}.py`, `src/lab/substrate/mcp/adoit/adoit_excel.py` (`_norm`), `src/lab/core/visio/read_lucidchart.py`.
- **Coordinator** — `src/lab/workloads/visio_to_archimate/{workflow,host,devui_entry}.py` (A-F4, C-H3, C-M6, A-F2 import, A-F12,
  A-F16), scratchpad-test rescue, then wave 2.
