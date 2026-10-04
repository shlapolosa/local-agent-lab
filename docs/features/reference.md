# Reference corpus

*Feature notes split out of the root `CLAUDE.md` on 4 Oct 2026, verbatim. Shared rules (method, quality bar, invariants, cloud shape, identity, gateway, approvals, observability) stay in the root file.*

## Reference Corpus (`reference-mcp` :9700 — the governed artifacts every derivation reads)

**The corpus IS Postgres** (Neon, `ref_*` tables, `src/lab/substrate/reference/schema.py`): signed
versions (`ref_artifact_version`, Ed25519, `CHECK derived_from = master_sha256`), released per ring
(`ref_release`), records by natural key (`ref_record`, JSONB) and passages with pgvector
(`ref_passage`, undimensioned column, exact cosine, **no ANN index by design**), read ONLY under a
pin (`ref_pin`) with every read written to `ref_consumption` inside the call (FR-44). The server runs
as `lab_reference_reader` (SELECT + INSERT on pin/consumption only — DR-03 as a GRANT); publishing is
the operator CLI `python -m lab.substrate.reference.publish` holding the signing seed
(`var/run/reference_signing_key`, NEVER `.env`/`LAB_ENV`) and the publisher DSN. **Deterministic data
in `ref_record`, relevance in `ref_passage`, nothing reference-shaped in memory or Redis.**

- **Retrieval mode is DATA on the artifact** (`ref_artifact.retrieval`, `lab.core.reference.model.
  Retrieval`): `whole` (a small complete register — read every record, never "the relevant rows"),
  `key` (exact by natural key), `vector` (also indexed; a RECORD artifact can be both — the capability
  map is exact by `parent`/`level` AND searchable). Undeclared = the kind's default (prose ⇒ vector).
  The catalogue and the pin tell a caller the mode; **a consumer reads the way it is told and never
  infers it from size** — baseline artifacts grow, and the consumer must not be what changes when
  they do. A `vector` record artifact publishes one passage per record (`derive.record_passages`,
  `ref_passage.record_id` → the row), so a relevance hit resolves to the exact record.
- **Search is scoped by declared mode** (`pg_library._searchable`): a whole-pin search covers the
  vector-mode artifacts and skips the exact ones; NAMING an exact artifact refuses ("read it with
  reference_lookup"); naming one not in the pin refuses; a vector artifact with no completed index
  still refuses (CR-12 — an empty list is the most dangerous return value in this layer).
- **Relevance retrieval goes THROUGH LiteLLM**: one VECTOR STORE per vector-mode artifact (**store
  id = artifact id**, so a team is granted ONE map), declared in `lab.platform.contracts.VectorStores`
  and reconciled into the gateway's DATABASE on every push by `scripts/register_vector_stores.py`
  (CD step after `verify`). **Not a yaml `vector_store_registry`**: that loads into memory, and with
  a database configured the list endpoint DELETES any in-memory store the database lacks — verified
  live, the block loaded and one `GET /vector_store/list` later a search fell through to OpenAI's
  own vector-store API. Provider `pg_vector` is an HTTP client, NOT a Postgres client, pointed at
  reference-mcp's **OpenAI vector-store façade** (`lab.substrate.mcp.reference.vectorstore`, `POST
  /v1/vector_stores/<id>/search`, mounted beside `/mcp` via `LabServer.serve(routes=)`, behind the same
  bearer). It is a second TRANSPORT over the one `pg_library.search`, not a second implementation:
  a workload's search carries `pin_id/run_id/process/field` in `filters` (a pin with no field is 400)
  so it is attributed exactly like one through the tool; a search with NO pin — the gateway UI, a
  person with a key — is served AD HOC under a pin the façade takes of that store, recorded as
  `adhoc`/`gateway-<date>`/`search` (user decision 10 Sep 2026: exploration stays governed and in
  the trail, only workloads must name a field). A team is granted stores with
  `object_permission.vector_stores` — **LiteLLM reads an absent OR EMPTY list as "every store"**, so
  `provision_usecase_agents._grants` always writes it and spells "none" as the sentinel `["-"]`.
  `file_search` injection stays OFF (no pin travels with it). **No credential on the store**: LiteLLM
  1.98 resolves no `os.environ/` on this path (verified in `vector_stores/main.py`), so the provider's
  own `PG_VECTOR_API_BASE` (reference-mcp's ORIGIN) / `PG_VECTOR_API_KEY` (= `MCP_SHARED_SECRET`) are
  set in the gateway's PROCESS env by `lab.sh`, `deploy/railway.py substrate_env` and compose.
  Workloads call `lab.workloads.gateway.vector_search` and preflight with `preflight_stores`
  (`/vector_store/list`), the same zero-token contract as `REQUIRED_TOOLS`.
- **Embedding is the substrate's OWN model** — service `embedder` (`deploy/railway.py ensure_embedder`:
  `ollama/ollama` image, `nomic-embed-text`, weights on a `/root/.ollama` volume, bound `[::]`, no
  domain, no credential — the private network is the trust boundary, as for Redis; `EMBED_URL` is set
  per tier by `substrate_env`/`lab.sh`/compose). Decided 10 Sep 2026 after the alternatives were
  tried: Ollama Cloud, OpenRouter and Anthropic serve NO embedding model (listed live) and the OpenAI
  account answered `credit_balance_exhausted` on the first call. The gateway's `model_list` entry
  `nomic-embed-text` (`ollama/…`, `api_base: os.environ/EMBED_URL`) is the ONE place a vendor
  change lands; `REFERENCE_EMBED_DIM=768` is held equal to its `output_vector_size` by a governance
  test. The corpus embeds with a VIRTUAL key, `REFERENCE_EMBED_KEY` (team `reference-corpus`, that
  one model, zero tools; `scripts/provision_reference_embedder.py` mints it once and reconciles the
  allowed model after). `REFERENCE_EMBED_MODEL` unset ⇒ every search refuses and publishing a vector
  artifact defers by name — fail closed, never an empty answer.
- **Every workload PINS before its first derivation** (`lab.workloads.usecase.reference`): exactly
  its `REFERENCE_ARTIFACTS` — what its own steps read plus `DecisionTools.READS` /
  `ValuationTools.READS`, the artifacts the governed derivations read on its behalf (decision-mcp
  REFUSES without a pin; there is no packaged fallback any more). The pin id, the frozen versions and
  the DRIFT ride the run board, the screening record and the design package: the design run re-pins
  (the approval can wait days) and states "screened at v0.26, designed at v0.27" per artifact —
  recorded, never blocked on (user decision). Reads are attributed to the DERIVED FIELD
  (`reference.attribution`), and `cells.rows` is the one corpus-to-domain mapper.
- **Stated exception to gateway-only egress, the third**: decision-mcp, valuation-mcp and the review
  app read the corpus by calling reference-mcp DIRECTLY — substrate to substrate, on the private
  network, bearer-authenticated with `MCP_SHARED_SECRET`, `REFERENCE_PROVIDER=mcp`
  (`lab.substrate.reference.mcp_library`, the reference port over reference-mcp's tools). Bounds: a
  substrate server reading published rules under a pin, no model content, no caller credential, and
  every read still lands in `ref_consumption`. What it forgoes is the gateway's metering and span
  for those reads; routing them through the gateway would mean a virtual key per substrate server —
  deliberately not done yet, recorded here so the rule erodes by decision and not by accident.
- **"Capability map" is BANNED unqualified — there are two, answering different questions**
  (`docs/decisions/2026-09-18-two-capability-maps.md`, 18 Sep 2026). The **business** map
  (`healthcare-provider-v2.0`, matched at L3 by a MODEL) answers *what ability does this exercise*;
  the **technology** map (`ai-capability-map`, CAFÉ M4, 2 levels) answers *how would we do it*.
  Measured: **836 of the business map's 1,042 L3 concepts — 80% — name nothing clinical**, and a
  negative-control chat bot that tells the time matched it 3-4 times on every run with entries whose
  definitions are literally true of it. So **a business-capability match is a classification, not a
  justification**: it may inform a gate and a prompt, and must never on its own select a component,
  attach a guardrail or price anything. Identity matters on the technology map (guardrails and cost
  dispatch on it, so that path is an exact key join with an id gate, G04) and does NOT on the
  business map (no consumer distinguishes siblings) — so near-synonym choice there is not a defect
  and must not be scored as one. Two labels are acceptable substitutes when **nothing downstream can
  tell them apart**, a property of the CODE; two siblings no consumer distinguishes carry no
  information, which is a defect in the MAP. The matching GRAIN belongs to the map —
  `coverage.leaves` takes `deepest` as a parameter because the constant silently returns zero
  candidates against a shallower map, and zero candidates reads downstream as "nothing is relevant"
  (`match`/`resolve` forward it now; they did not, so every live run matched at the constant 3).
  **Step 5 matches the TECHNOLOGY map** (18 Sep 2026): `ai-capability-map` + `capability-domains`,
  read WHOLE from the corpus under the pin, projected by `lab.core.usecase.capabilities.concepts` —
  74 candidates, ~5,700 tokens, so `leaves` needs no retrieval. **The concept id IS the natural key
  `"Domain · Capability"`**, so a match reaches its guardrails and its components with no further
  resolution. The business map is retired behind `config.BUSINESS_CAPABILITY_SCHEME` (empty), step 5
  records a declared default without one, and `Feasibility.ESCALATE` asks a human rather than
  rejecting every use case for a map nobody published. **Guardrail bindings**: `guardrails.cap` ->
  a capability -> its components is checked with NO ratchet by
  `tests/governance/test_guardrail_bindings_resolve.py` (20 of 24 dangled until 18 Sep 2026, reported
  by `families.unclaimed()` as corpus silence and therefore invisible); composition move 5 —
  obligation bound to a SELECTED component — is `lab.core.usecase.enforcement`, keeping `unbound`
  (the design's fault) apart from `unenforceable` (the corpus's). **Artifact content never lives in
  code**: `tests/governance/test_no_artifact_content_in_code.py` ratchets the seeding scripts'
  translation tables downward — put the fact in the CAFÉ artifact, where its author owns it.
- **The capability map is read from the corpus, searched through a store, matched three ways.**
  Screening pins its map (`VectorStores.for_scheme(SCHEME)` = the artifact id), fetches L1 and L3
  rows under the pin (`id, parent, level, label, path`) and hands the matchers two SEAMS —
  `children(ids, level)` (rows by parent through `reference_lookup`) and `search(query, k)` (the
  store through the gateway, under the pin, attributed to the coverage map). `coverage.MATCHERS`
  = `drill` | `leaves` | `vector` (one query per behavioural element, record-backed hits unioned,
  one pass of step 5); `COVERAGE_MATCHER` picks, `scripts/eval_coverage.py` scores all three over
  the same seams — the harness decides, not the plan. `semantic_concepts` is no longer an intake
  grant; the intake team holds exactly the two map stores.
- **Cost is a JOIN, not an estimate** (user decision). Step 21 selects components BY CATALOGUE ID
  (`reference-architecture-components`, keyed by `content_id("cmp-", zone, name)`; the AI
  capability map's `components` column says which realise each capability) and its gate refuses an
  id the pinned catalogue lacks — G04 as a gate. `valuation_cost(component_ids, envelope, volume,
  …, pin_id)` joins them onto `component-prices` (`(component, variant)`; opex three-point,
  `envelope_in`, `volume_driver` + `expected_at`/`high_at`) at the pinned version: the envelope
  FOLLOWS the confirmed criticality class (`cost.envelope_for`), the volume is what intake captured
  (`cost.volume_from_intake`, the "Volume assumptions" group), a driven line with no captured volume
  is EXCLUDED and named, a component with no line is a gap flag, capex the catalogue lacks is
  named. Step 23's agent is left with the build cost and its provenance. decision-mcp and
  valuation-mcp read the corpus THROUGH reference-mcp (`REFERENCE_PROVIDER=mcp`,
  `lab.substrate.reference.mcp_library`, the shared `lab.substrate.mcp.pinned.rules` policy): no
  DSN, no packaged fallback — no pin, no derivation.
