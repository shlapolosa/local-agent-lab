# Wave-1 design review (post-implementation) — 2026-09-03

Reviewer: `code-reviewer` agent over the full uncommitted working tree (44 modified + 29 untracked files;
all 23 test files run; py_compile clean). Verdict: wave 1 landed cleanly, **no broken cross-builder callers**
(every renamed/deleted symbol grepped). Invariants re-verified: no `artifacts.store(` under `src/lab/workloads/`;
all three MCP servers behind `shared/mcpserver.serve` → `BearerAuthMiddleware`; `extra_headers`
traceparent on all `mcp_servers`; `ANTHROPIC_API_KEY` never in `ROLE_ENV`; `custom_auth` contract intact;
LiteLLM reaches the guardrail with `route_type="aresponses"`.

## Findings (ranked) → disposition
| # | Sev | Finding | Disposition |
|---|---|---|---|
| F1 | HIGH | `adoit_import_status` claims a REST write executes when `ADOIT_REST_WRITE=true`; no apply step exists (`src/lab/substrate/mcp/adoit/server.py:246-263`) | fix text + drop `write_path: "rest"` (T5 builder owns file) |
| F2 | HIGH | production changes without tests: `workflow.py` executor logic, `custom_auth`, `mcpserver`, `adoit_rest` facade, `read_vsdx(page=)`/`type_hint`, `inputs.split_page`, storage `page` | coverage wave (T1–T6, target ≥ 80 %) |
| F3 | HIGH | suite not offline/CI-runnable: `test_locks`/`test_staged_registry` need live Redis; `test_canon.py` absolute path; script-style tests pytest can't collect; `test_ids` function after `__main__`; `test_engine` needs git-ignored `lab_model.json` | `tests/run.sh` added; fixes routed (canon/ids: coordinator; locks/registry: T4; engine: T6) |
| F4 | MED | `ROLE_ENV["gateway"]` still grants `GATEWAY_EVENTS_FILE` (reader deleted in W1a); stale `_setup_otel` comments | T3 (railway.py) + coordinator (devui_entry) |
| F5 | MED | `mcpserver.serve` only warns on non-loopback bind without `MCP_SHARED_SECRET` — must refuse | T4 |
| F6 | MED | `custom_auth._redis()` inline fallback duplicates the seam and is unreachable | T3 |
| F7 | MED | dead: `render_vsdx.py` (kept deliberately as the Phase-A spike, omitted from coverage), `staged_registry.STATUSES`, `config.public_url`, `canon.same/group/pick_display/tokens`, `otel.service_name`, `workflow "path"` key, stale pragma | coordinator (config/canon/accumulator) + T4/T1 |
| F8 | MED | OCP/DIP items still open by plan: env-read modes in executors (A-F9/C-H4), `_EXECUTOR_OF_SPAN` second table (A-F5), Excel BA dialect (A-D3), `store` mutating spec (C-O2), approvals/workflows parallel (B-O2) | multi-request refactor |
| F9 | LOW | `auto_router` imports `collect_texts` from `pii_guardrail` via sys.path | move to `shared/prompt_walk.py` with B-M3 |
| F10 | LOW | tombstone tests (`"_setup_otel" not in src` etc.) | delete after this lands |

Closed (confirmed): B-H1/H2/L2/L4/M6/M7/L3/M2(partial)/H4(half); A-F1/2/3/4/7/8/11(partial)/12/13(latch)/14;
C-H1/H2/H3/M1/M2/M3(half)/M4/M6/M7/M8/L1/L2; all §5 dead-code items of the consolidated report.

## Scale & migration readiness (reviewer's walkthrough)
- Add an MCP server: `serve()` + one `litellm-config.yaml` entry + one `ROLE_ENV` row (data only).
- Add an observability sink: one function (`shared/otel.tracer`); App Insights = exporter swap.
- Add a workload: still FOUR places (`ROLE_ENV`, `WORKLOADS`, `workflows.GROUPS`, a consumer copy) → process registry (C-§4).
- Azure: `ROLE_ENV` ↔ Key Vault scopes 1:1; guardrail pure functions ↔ APIM policy; auth contract intact.
