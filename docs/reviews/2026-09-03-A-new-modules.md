# Design review A — 2026-09-03 — today's parallel-builder wave (visio_to_archimate + shared + adoit-mcp + skills)

Reviewer: `code-reviewer` agent (lenses: DRY, SOLID, YAGNI, GoF, DI, dead code, testability, scale, Azure/AF migration).
Scope: `ba_tools.py`, `architect_tools.py`, `devui_entry.py`, `workflow.py` (today's changes), `host.py`, `inputs.py`,
`agents.py`, prompts, tests; `shared/{runlog,workflowviz,staged_registry,canon,locks,render_vsdx,docparse,config}.py`;
`src/lab/substrate/mcp/adoit/{adoit_rest,adoit_excel,server}.py`; `src/lab/substrate/mcp/storage/server.py`; visio-reader + archimate-adoit skill additions;
`src/lab/substrate/review/app.py` Runs board. Claims verified by grep, by running the in-repo tests, and by probing installed `agent_framework`/`streamlit`.

## 1. Summary

Quality of the individual modules is high: `ba_tools`/`architect_tools` are pure and schema-driven, `relrepair` and
`staged_registry` reuse the semantic layer and Lua atomicity rather than re-implementing, and the in-repo tests pass
offline. The problems are the ones parallel building predicts: **the same skeleton was written twice, the same normaliser
three times, and four modules landed with zero callers.**

Top three leverage points:
1. **One accumulator skeleton + one normaliser home** — ~120 duplicated lines between the two accumulators; `_norm` exists
   in three subtly different forms (F1–F3).
2. **The run-log is hand-rolled over an Agent Framework primitive it should subscribe to** — AF already emits
   `executor_invoked|completed|failed` with the executor id; subscribing fixes a confirmed Runs-board bug by construction (F4, F5).
3. **YAGNI debt now costs image size**: `canon`, `locks`, `staged_registry`, `render_vsdx` and the ADOIT REST write facade
   have no callers, yet `pymupdf` was added to `deploy/requirements.txt` (F6).

One correctness bug to fix today regardless (F7: temp-file collision in `docparse.vsdx_dict`), and one prompt-contract
contradiction the BA is reading right now (F8).

## 2. Findings (ranked)

- **F1 HIGH · DRY / Template Method — the two accumulators are one class written twice.** `ba_tools.py` vs
  `architect_tools.py`: `_fmt`, `_coerce_items`, `_nonempty_str`, `MAX_BATCH`, the "batch too large" message (4 copies),
  the `{added, updated, rejected, total_*}` envelope, dedupe keys, `reset()/last_finish`, the `finish()` skeleton, and the
  `make_tools(acc)` factory are duplicated. Refactor: `src/lab/workloads/accumulator.py` base (`batch()` = coerce → cap → validate →
  add/update/reject; `finish()` = assemble → gate) with `_validate/_key/result/_gate` hooks. Effort M. Safe now (tests exist).
- **F2 HIGH · DRY — `_rid` duplicated byte-for-byte** (`workflow.py` and `architect_tools.py`; "byte-identical" is a comment,
  not a mechanism; relation-id stability prevents ADOIT duplicates). Move to `src/lab/workloads/ids.py`. Effort S. Do now.
- **F3 HIGH · DRY — three `_norm` implementations, two not equivalent.** `adoit_excel._norm` (regex) == `architect_tools._norm`;
  `read_lucidchart` uses `isalnum()` (keeps non-ASCII → different result); `canon.canonical()` is a different thing (token-sort
  key) and is imported by nobody. Refactor: `shared/canon.squash()` (one ASCII policy) + `canonical()`; import everywhere
  (skill script keeps its standalone fallback). Effort S–M.
- **F4 HIGH · confirmed bug — the Runs board never highlights the `store` node.** Node ids are derived from OTel span names
  (`store-spec` → `store_spec`) but executor ids are `store`; the `{"ba_agent": "ba"}` hack is the same bug patched once.
  Fix: pass the executor id explicitly to `span()` (or F5). Effort S.
- **F5 HIGH · migration / Observer — run tracking duplicates an AF primitive.** `WorkflowEventType` has
  `executor_invoked/completed/failed`, `superstep_*`, `output`, `error` via `wf.run_stream()`; AF also ships `CheckpointStorage`.
  Make the run-log ONE subscriber in `run_workflow()` (`async for ev in wf.run_stream(inputs): runlog.observe(run_id, ev)`);
  the six `with span(...)` blocks disappear and node-id bugs become impossible; on Azure the same subscriber feeds App
  Insights. Effort M. Do WITH the multi-request refactor.
- **F6 HIGH · YAGNI — four unwired modules + a dormant write facade.** Zero callers: `canon.py`, `locks.py`,
  `staged_registry.py`, `render_vsdx.py` (which pulled `pymupdf` into requirements and carries a LibreOffice host
  assumption that won't exist in a Container App), `adoit_rest` write verbs (the "approval-gated changeset tool" its docstring
  promises does not exist). Revert `pymupdf` until a caller exists; decide the REST facade (wire behind a gated tool or delete).
- **F7 HIGH · correctness under concurrency — temp-file collision in `docparse.vsdx_dict`.** Path keyed by pid + file name
  only; storage-mcp serves concurrent calls and the `page` param makes "N reads of the SAME workbook" the dominant pattern →
  truncated parses / `FileNotFoundError`. Fix: `tempfile.TemporaryDirectory()`/`NamedTemporaryFile`. Effort S. Do now.
- **F8 HIGH · contract drift — the BA's prompt contradicts itself about stencils.** `prompts/ba.md` + `method.md` (updated):
  stencil/`type_hint` = PRIMARY evidence; `skills/visio-reader/SKILL.md` (not updated): "soft hint, never ground
  truth"; the skill never documents `type_hint`. Fix SKILL.md + re-register (`scripts/register_skill.sh`). Effort S. Do now.
- **F9 MEDIUM · DIP / Strategy — mode per-run, model per-process, neither injected.** `BA_MODE`/`ARCHITECT_MODE` read inside
  executors; `MODEL` frozen at import; nothing varies per request. Put `ba_mode/architect_mode/model` in `cfg` from the
  composition root; `BUILDERS = {"json": …, "tools": …}` Strategy replaces the if-branches. Effort M. With the refactor.
- **F10 MEDIUM · DIP — `src/lab/platform/config.py` is bypassed.** `GATEWAY_URL` read raw in 5 places, `/mcp/` re-derived 4× though
  `config.GATEWAY_MCP_URL` exists; Jaeger default duplicated; none of the agent knobs (`AGENT_*`, `BA_RUN_TIMEOUT`, …) live in
  config. Add an agent-settings block. Effort S–M.
- **F11 MEDIUM · testability — the wave's tests exist only in a scratchpad** (`test_canon/locks/staged_registry.py`, 308 lines,
  one hardcodes an absolute path); `pytest` not installed; `test_relrepair.py` sits in the skill dir. Create `tests/`, move
  them, add `tests/run.py`. Effort S. Do now.
- **F12 MEDIUM · DRY — `cfg` built twice, already drifted.** `host.run_once` vs `devui_entry.build_cfg`: `run_id` missing
  in DevUI (so DevUI runs never reach the Runs board); `outdir` dead. Extract `make_cfg(...)`. Effort S.
- **F13 MEDIUM · runlog robustness.** `_DISABLED` latch never resets (one Redis blip kills the board until restart) → retry
  timestamp; `node()` does HGET→mutate→HSET (non-atomic) → `RPUSH`/Lua (with the refactor).
- **F14 MEDIUM · stale docs.** `adoit_rest.py` header ("full ADOIT 18… CRUD all work") contradicts `config.py` ("CE blocks
  REST writes"); `adoit_mcp/server.py` tool list stale (3 tools missing, `xml_path` → `xml_ref`); `read_vsdx.py` references
  an unlanded "Phase B". Effort S.
- **F15 MEDIUM · OCP / Adapter — three write paths, no interface.** XML views, Excel objects, dormant REST are selected by
  ad-hoc code across 5 files. Seam: `WritePath` protocol (`render/describe/apply`) with `XmlViewsPath`, `ExcelObjectsPath`,
  `RestPath` selected by config. Effort M. After the refactor.
- **F16 LOW · `sys.path` archaeology.** Nine-line import shim ×5 in `src/lab/platform/`; skill-scripts path inserted ×4. Also
  `workflow.py` imports `architect_tools` eagerly (hard dependency on the skill) while `_repair_relations` still pretends
  the same import is optional — pick one.
- **F17 LOW · review app is fine**; mermaid loads from a CDN (blank offline — say so); the height heuristic will under-size
  fan-out graphs.

## 3. Quick wins (do first)
1. F4 — run-log node ids from executor ids (1-line each). 2. F11 — rescue the scratchpad tests into `tests/` + `tests/run.py`.
3. F8 — fix `visio-reader/SKILL.md` + document `type_hint` + re-register. 4. F6/§5 — revert `pymupdf`; delete confirmed dead
code. 5. F2/F3 — hoist `_rid` → `src/lab/workloads/ids.py`, `_norm` → `shared/canon.squash()`, `_coerce_items/_nonempty_str/_fmt` →
`src/lab/workloads/accumulator.py`. Also fold in F7 (3 lines) and F14 (one paragraph of truth).

## 4. Scale & migration walkthroughs
- **New input source kind**: today SEVEN places (`docparse.kind`, a parser fn, `inputs.py`, a `storage_read_*` tool,
  `BA_MCP_TOOLS`, `_ba_message` branch, prompts). Seam: a parser **Registry** + one generic `storage_read(ref)`.
- **New write path**: five files (F15). Seam: `WritePath` adapter; `ADOIT_REST_WRITE` becomes a factory key.
- **New agent step/mode**: executor + env branch + chain entry + span-name convention + prompts. Seam: F9 Strategy + F5 events.
- **N workloads/views in parallel**: blockers F7, F13, F9; the modules built for it (`locks`, `staged_registry`, `canon`) are
  correctly designed but unwired and untested-in-repo.
- **Azure lock-in**: genuinely clean (gateway `(base_url, credential)`, `art://` refs, Redis keys inside `src/lab/platform/`). New
  exceptions: the LibreOffice/`soffice` host assumption (decide before wiring) and the vendored `.xlsx` template (fine).

## 5. Dead code (grep-confirmed)
`cfg["outdir"]` (host, devui); `architect_tools.ELEMENT_REQUIRED/RELATION_REQUIRED`; `ba_tools.RELATIONSHIP_REQUIRED`;
`staged_registry.STATUSES`; `canon.same/group/pick_display` (no callers); `render_vsdx.py` (no importers); `locks.py`,
`staged_registry.py` (no importers, expected with refactor); `adoit_rest` write verbs (no callers); `read_lucidchart._tok`;
`adoit_excel` "HOOK" comment; stale `adoit_mcp/server.py` tool list; contradictory `adoit_rest.py` header.

## 6. Testing gaps (cheapest first)
`docparse.split_fragment/kind/media_type/ext_of` (table test); `adoit_excel.generate` (3-element spec into a temp template);
`read_lucidchart.type_hint_for_master` incl. native `Database.70` → None; move scratchpad tests for `canon/staged_registry/locks`;
`runlog` needs a `client=` seam (as `locks` already has); `workflow._incomplete/_extract_json/_repair_relations` (pure);
`review/app._node_states/_mermaid_with_state` (a test would have caught F4).

## 7bis. OO / DDD / hexagonal (lens 10)
- **D1 HIGH · the `state` dict is an unguarded aggregate** — 14 keys accumulate across six executors; preconditions
  assert by `KeyError` minutes into a run; the BA dialect (`relationships/from/to/candidateType/group`) and the engine
  dialect (`relations/src/tgt/type/folder`) share one bag with no translation. Refactor (with the refactor): four frozen
  dataclasses as AF message types — `BaOutput`, `Resolution`, `ModelSpec`, `Staged` — only the messages that cross
  executor boundaries; do NOT wrap leaf dicts.
- **D2 HIGH · `ArchitectAccumulator` is the real aggregate root** — it enforces the ArchiMate invariant at mutation
  (`add_relations` cannot produce an illegal model). Name it (`ArchiMateModel`/`SpecDraft`); the shared base is the
  accumulation mechanism, each subclass owns its invariant. `_probe_build` duplicates `adoit_mcp.server._build` — one
  `build_model(spec)` in the engine.
- **D3 HIGH · three dialects for one vocabulary** (BA / Modelling / ADOIT `C_*`) — healthy contexts, unhealthy implicit
  translation: `adoit_excel._relations` accepts both `relations|relationships` and `src|from` (an EA-write adapter speaking
  BA). Overloaded words to pin: *domain* (folder vs DDD), *view* (ArchiMate view / vsdx page / workload unit), *node*
  (executor / run-log / Mermaid — the F4 bug is this ambiguity). Refactor: one explicit `translate.ba_to_spec(BaOutput,
  Resolution) -> ModelSpec` anti-corruption layer; drop the dual-shape tolerance.
- **D4 · bounded-context map** — Ingestion (docparse/read_vsdx/read_lucidchart/storage_mcp/inputs/BAAccumulator; leak:
  sys.path + temp files), Modelling (engine/relrepair/ArchitectAccumulator/semantic — clean core, keep it), EA-write
  (adoit_rest/adoit_excel; speaks BA dialect, three paths no port), Governance (clean), Observability (`runlog` imported
  inside the graph definition). The `state` dict is how all five share one mutable bag.
- **D5 · ports the core should not bypass** — `workflow.py` imports `artifacts` inside the `ba` executor (→ `ArtifactStore`
  port in cfg); `fastmcp.Client` constructed inline ×4 (→ **`ToolGateway.call(tool, args)`** — THE APIM-migration seam);
  `runlog`/`locks`/`staged_registry` import redis with no interface (→ `RunLog`/`Lock`/`StagedRegistry` ports; only
  `locks` has `client=`); `render_vsdx` shells out inside `src/lab/platform/` (→ `DiagramRasteriser`, keep out of the image until
  used). Composition root: `host.run_once` is 90% of one — make it the only one, constructing adapters for
  `build_workflow(ports)`.
- **D6 · keep simple**: `canon`, `relrepair`, `read_lucidchart` (pure functions; no `CanonicalName` type), `workflowviz`,
  `adoit_excel.generate` (procedural adapter — just stop it speaking BA), the thin `@mcp.tool()` wrappers, the Markdown
  prompt addenda (no template engine).

## 7. Sequencing
**Now:** F2, F3, F4, F6 (requirements + dead code), F7, F8, F11, F12, F14, F16.
**With the multi-request refactor:** F1, F5, F9, F13 (atomic append), wiring + tests for `canon/locks/staged_registry`.
**After:** F15 (write-path Adapter), the parser Registry.
**Fine as-is:** `relrepair` (reuse, not reimplementation), `staged_registry` Lua first-writer-wins, `locks` token
compare-and-delete, `_ident/_safe` (byte-identical for non-ADOIT ids), `adoit_excel` deriving maps from the template,
`docparse` single sizing contract.
