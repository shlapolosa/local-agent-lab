# Design review B — 2026-09-03 — platform layer (`gateway/`, `src/lab/platform/`, `deploy/`, `lab.sh`, `config/clients/`, `src/lab/substrate/channels/`)

Reviewer: `code-reviewer` agent. Claims verified against the vendored LiteLLM, the live `.env` key list, grep, and AST checks.

## 1. Summary
Better shape than its size suggests: `src/lab/substrate/artifacts.py` is a near-clean Strategy over three stores, `config.py` is the
address book it claims to be, `mcpauth.py`/`identity.py` are small and honest, and hard-won operational knowledge is
captured next to the code. The three highest-leverage problems are seams never cut: (1) **an invariant hole** — the PII
guardrail and auto-router inspect `data["messages"]` only → silent no-op on `/v1/responses`, the agents' actual API;
(2) **credential blast radius** — `railway.py` uploads the whole `.env` to every service with a denylist; (3) **no composition
root, four of everything** — Redis clients ×3+, `.env` parsers ×6, Graph clients ×4 (tenant GUID hardcoded ×3), stream
logic duplicated across `approvals.py`/`workflows.py`. `scripts/e2e_smoke.py` is the only platform test and needs the live stack.

## 2. Findings (ranked)
- **H1 HIGH · invariant breach — PII guardrail + auto-router skip the Responses API.** `pii_guardrail.py:91` and
  `auto_router.py:72` iterate `data.get("messages")`; `/v1/responses` reaches `pre_call_hook` with `route_type="aresponses"`
  and the body key `input` (LiteLLM does not normalise it). Every BA/Architect prompt egresses to Ollama Cloud unmasked.
  MCP tool args/results are also unscanned. Refactor: a `_carriers(data)` generator yielding text holders from `messages`,
  `input` (str or list), `instructions`; mirror in the post hook for `response.output[].content[].text`. Add a
  `/v1/responses` PII case to the smoke. Effort S. **Do first.**
- **H2 HIGH · least privilege — `railway.py` ships the entire `.env` to every service.** `load_env_for_cloud` drops 8
  management keys, `configure_workload` pops 6 more; `wf-visio` receives `ADOIT_*`, `OLLAMA_API_KEY`,
  `LITELLM_MASTER_KEY`, `ANTHROPIC_UPSTREAM_API_KEY`, `MICROSOFT_CLIENT_SECRET`, `MCP_SHARED_SECRET`, all agent client
  secrets. Refactor: a per-role **allowlist** `ROLE_ENV = {gateway: …, adoit-mcp: …, storage-mcp: …, workload: …}` glob-matched
  against `.env` (this is also the Container Apps secret-scope table). Effort S–M.
- **H3 HIGH · DRY / migration — four Microsoft Graph clients, tenant GUID hardcoded in three** (`entra_provision.py:19`,
  `entra_dev_provision.py:13`, `entra_ui_sso_provision.py:8`); each re-implements token refresh, `call/graph`, `find_app`,
  `ensure_sp`, `addPassword` with a literal 2027 expiry. Refactor: `gateway/graph.py` (`Graph` class + `patch_env`); scripts
  become ~30-line declarations. Effort M.
- **H4 HIGH · DRY / DIP — `approvals.py` and `workflows.py` are the same module twice; Redis acquisition scattered** (`_r`,
  `ensure_groups`, `request`, `status`, `pending`, `channel_events`, `ack`, CLI all parallel; `workflows._r()` reaches into
  `approvals._r()`; `custom_auth._redis()` re-derives `REDIS_URL`). Refactor: `src/lab/platform/redis_client.py: client(url)` (cached
  per url) + `shared/streams.py: Stream(ns, groups)` Template Method; `APPROVALS`/`WORKFLOWS` instances; `approvals` keeps
  `decide()`, `workflows` keeps `mark()`. `gateway/` importing `src/lab/platform/` is fine. Effort M.
- **H5 HIGH · SRP / OCP — `deploy/railway.py` is a 490-line god module; no `CloudTarget` seam.** Split: `deploy/topology.py`
  (pure data: SUBSTRATE, WORKLOADS, ROLE_ENV), `deploy/targets/railway.py` (`CloudTarget`: ensure_service/set_env/
  set_command/expose/deploy/stop/status/logs), `deploy/cli.py`. `workload_status()` scrapes hardcoded log strings the
  workload prints — read the `workflow:req:<id>` hash instead. Effort L (when Azure is next).
- **M1 MEDIUM · `artifacts.py`: good Strategy, missing the Protocol + pool.** `Store` is a type union not a contract;
  `store()` if-chain; `PostgresStore` opens a connection per operation (Neon TLS handshake per artifact read); `S3Store`
  reads `config.S3_*` at construction. Refactor: `ArtifactStore` Protocol + `BACKENDS` registry, `psycopg_pool`, constructor
  injection. Effort S.
- **M2 MEDIUM · `custom_auth.py`: correct contract, no test seam.** Env read at import; `_jwks()` not injectable;
  `ENTRA_CLIENT_TO_KEY` JSON-parsed per request; `except Exception: return None` swallows JWKS/clock failures;
  `os.environ["DEVELOPERS_TEAM_ID"]` KeyError inside the hook. Refactor: pure `map_claims_to_key(claims, mapping)`,
  injectable `jwks_provider`, parse mapping once, log non-lab-JWT failures. Effort S.
- **M3 MEDIUM · `auto_router.py` hardcodes routes + classifier upstream** in code while models live in the YAML. Move
  `routes`/`classifier` into `litellm_params` (the guardrail already proves the mechanism). `_classify_rules` untested. Effort S.
- **M4 MEDIUM · six `.env` parsers, two writers** (`lab.sh`, `railway.py` ×2, `provision_visio_agents.py`,
  `register_skill.sh`, `e2e_smoke.py` — the last still has the unfixed `$VAR` bug). Refactor: `shared/envfile.py`
  (`read(path, profile)`, `patch(path, pairs, profile)`); shell scripts call `python -m shared.envfile`. Effort M.
- **M5 MEDIUM · `lab.sh` almost the composition root**: four copy-pasted start stanzas, service list ×3, a 30-line embedded
  Railway GraphQL client duplicating `deploy/railway.py`, `free_port kill -9`, stale help. One `start_service` fn;
  `deploy/railway.py jaeger up|down|status`. Effort S–M.
- **M6 MEDIUM · `e2e_smoke.py` is a script, not a test**, and the only platform test; `redisok` dead. Wrap sections in
  functions; add pure unit tests (§6). Effort S.
- **M7 MEDIUM · two compose topologies** — `deploy/docker-compose.yml` (old, no Redis) vs `deploy/substrate/compose.yml`
  (current). Delete the old one; fix the CLAUDE.md reference. Effort S.
- **L1 LOW · `config.py` import-time constants; `gateway/` never imports it** (17 direct env reads). Eventual `Settings.from_env()`.
- **L2 LOW · `mcpauth.py` logs 24 chars of a bearer token on denial** → log a sha256 fingerprint. Effort S.
- **L3 LOW · content-type maps duplicated** (`artifacts.CONTENT_TYPES` vs `docparse.IMAGE_TYPES/DOC_TYPES`, already
  disagree). One table in `artifacts.py`. Effort S.
- **L4 · `.claude/settings.local.json` holds a live Neon API key** and is only ignored by the user's global gitignore. Add to
  project `.gitignore`; rotate the token. Effort S.

## 3. Quick wins
1. Mask `input`/`instructions` + Responses output in `pii_guardrail` (~15 lines). 2. Delete dead code (§5). 3. Expand
`configure_workload`'s pop-list (one line) / then the allowlist. 4. `src/lab/platform/redis_client.py` single cached client.
5. `tests/` with five pure unit tests (§6).

## 4. Scale & migration
Second process: ~6 places (2 copy-paste) → 3 data-only after H3+H4. Azure Blob backend: ~4 places → 2 after M1 (best
extension point). Azure Container Apps target: a full parallel of `railway.py` today → one ~150-line adapter after H5.
LiteLLM→APIM: good — `custom_auth` contract maps to `validate-jwt`; extract `mask(text, patterns)` pure functions from the
guardrail hook; vendor the 16 PII patterns; `_developer_key` is inherently LiteLLM (isolated). N workloads: Streams design
is right; `GROUPS` constant + hand-written `lab.sh` fn per host are the only constraints. Host assumptions in logic:
`brew`/`lsof`/`pkill` in lab.sh (acceptable), `PATTERNS_JSON` `.venv/lib/python3.12` (dead, wrong in container),
`register_skill.sh` BSD `sed -i ''` + `/opt/homebrew` (cannot run on Linux/CI — it enforces the skill-registration invariant),
`railway.py REPO` hardcodes a personal GitHub account.

## 5. Dead code (grep/AST-confirmed)
`pii_guardrail.PATTERNS_JSON`; `_emit_event` ×2 (no consumer of `gateway-events.jsonl`); `config.public_url`;
`e2e_smoke.redisok`; unused imports (`entra_provision sys`, `entra_dev_provision time`); `deploy/docker-compose.yml`;
`.env` `# CLOUD: REDIS_HOST/PORT/PASSWORD` (dropped by the drop-set — no effect; `litellm-config.yaml` REDIS_HOST refs work
only via the `REDIS_URL` fallback — document it); `bootstrap_registry.py` (historical one-shot — label it);
`deploy/oci_provision.sh` + `oci_cloudinit.sh` (unreferenced). Stale: `lab.sh:5-6`, `deploy/README.md:6-7,37`, `Dockerfile:1`.

## 6. Testing gaps (all pure / fakeable)
`pii_guardrail._pseudo` round-trip + stable placeholders; `pre_call_hook` on a Responses-shaped body (would have caught
H1); `auto_router._classify_rules`; `railway.load_env_for_cloud` (`# CLOUD:`, `$VAR`, inline-note strip, drop-set);
`artifacts._split`/`content_type_for`/`LocalStore` round-trip; `custom_auth.map_claims_to_key` (after M2);
`streams.Stream` against fakeredis (after H4). Land in `tests/` with pytest; add `pyflakes` to the venv.

## 8. OO / DDD / hexagonal (lens 10)
Verdict: closer to ports-and-adapters than it looks — no consumer of `artifacts`/`approvals`/`workflows` touches a Redis
key, psycopg connection, boto3 client or bucket (verified). Missing: the inward half — no declared port, no typed domain
object, adapters in the same module as the vocabulary.
- **O1 HIGH (leverage) · `ArtifactStore` is a port in all but name** — declare the `Protocol` (with an `ArtifactInfo`
  dataclass fixing the `created_at` LSP wrinkle), `BACKENDS` registry, constructor-injected credentials. Azure Blob then
  = one ~40-line `BlobStore` + one registry line + one `.env` URL; nothing in `mcp/`, `review/`, `src/lab/workloads/` changes.
- **O2 HIGH · Governance is a real bounded context, but Redis Streams *is* its model** — `import redis` at the top of
  domain modules; events are `dict[str,str]` with hand-rolled JSON on both sides (telegram re-parses payloads); the state
  machine is spread over three files (`terminal` checks ×3); `consumer.py` reasons about another module's
  `socket_timeout`. Refactor (subsumes H4): `Decision`/`RunStatus` enums (`terminal` property), frozen event dataclasses
  (`ApprovalRequested`, `RunRequested`, …), an `EventStream` Protocol, ONE `redis_streams` adapter → Service Bus/Event Grid
  becomes a new adapter file. Explicitly NO aggregates/repositories/UoW here.
- **O3 MEDIUM · identity has a port on the agent side (`agent_headers`) and none on the gateway side; neither fakeable**
  — MSAL welded in; a missing key is a raw `KeyError`; the 1:1:1 pairing exists only as an env JSON re-parsed per request.
  Refactor: `AgentIdentity` value object; `TokenSource` Protocol (`EntraClientCredentials`, `StaticKey` = test double);
  pair with M2's pure `map_claims_to_key`. Changes on migration (APIM `validate-jwt` replaces the inbound adapter only).
- **O4 MEDIUM · no composition root** — every module self-wires via module globals (`artifacts._stores`,
  `approvals._POOL`, `custom_auth._REDIS`, `identity._apps`, `config.*`); `railway.py` embeds two security invariants as
  `pop()`s inside a GraphQL mutation (→ declare `ROLE_ENV`, the provisioner applies it); `lab.sh` is a supervisor with
  one real composition rule (`env -u ANTHROPIC_API_KEY`). Refactor LAST (after O1–O3): `shared/composition.build(role)`
  → `Services(store, uploads, events, approvals, identity)`; no DI framework, a factory.
- **O5 MEDIUM · `art://<id>/<name>` is the inter-service currency living as a string with two grammars**
  (`artifacts._split` vs `docparse.split_fragment`; prefix literal-tested in two more places; `_split` of a `#page` ref
  yields a name with the fragment). Refactor: `ArtifactRef` value object (`parse`, `looks_like`, `__str__` round-trips
  the fragment) — highest clarity-per-line change in the layer.
- **O6 LOW–MED · Governance notifier speaks ArchiMate** — `src/lab/substrate/channels/telegram.py` hardcodes `elements/relationships/views`
  from the approval payload; any non-ArchiMate approval renders `?`. Fix at the producing edge: the Modelling side builds
  `summary_lines`; channels render any kind.
- **O7 · keep simple**: `mcpauth.py` as is; no `NotificationChannel` ABC (1.5 implementations); guardrail/router are
  LiteLLM adapters by definition — extract only the pure policy (`mask`, `classify`); provisioning scripts stay scripts
  (ceiling = shared `Graph` client); `lab.sh` stays shell; `e2e_smoke` stays a probe; no `Url` value types beyond one
  `Settings` dataclass; `SUBSTRATE`/`WORKLOADS` stay data.
- Context map: Governance (language consistent, no outward Redis leak, types absent, one inbound leak from Modelling);
  Storage/Artifacts (cleanest boundary; needs the Protocol + the ref value object); Deployment (not a domain; carries two
  Governance policies as imperative pops); Observability (config-only, fine). The structural gap: Governance has no inner
  ring to be separable into — O2 creates it.

## 7. Cross-scope
Redis client seam should be agreed jointly (`locks.py` already documents injection; `staged_registry` catches RedisError) —
extract it OUT of `approvals._r()`. `docparse` sizing contract is genuinely DRY — leave it. `devui_entry.py` imports
`python-dotenv` (not in requirements; a 7th `.env` reader). `register_skill.sh` is macOS-only.
