# Documentation Fabric and the semantic layer

*Feature notes split out of the root `CLAUDE.md` on 4 Oct 2026, verbatim. Shared rules (method, quality bar, invariants, cloud shape, identity, gateway, approvals, observability) stay in the root file.*

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

## Operating rules learned the hard way (4 Oct 2026)

Each of these cost hours to find, and none is derivable from reading the code. They share one shape:
**the failure is indistinguishable from success**, so nothing asks to be investigated.

- **A grant needs THREE applies, and no test can see any of them.** Adding a tool to a
  `ToolCatalogue` and to a grant table (`provision_fabric_agents.CURATOR_TOOLS`) grants it NOWHERE. The
  declaration must be applied to (1) the dev LiteLLM team's per-tool ACL — `provision_fabric_agents.py`,
  or `/team/update` with `_grants(TOOLS)`; (2) the prod APIM MCP policy — `deploy/apim.py apply mcp`,
  which RENDERS from the table at apply time; (3) the image. Measured: the dev ACL carried the 25 Sep
  tool set, so 13 tools were refused — `semantic_store_page` and `semantic_vocab_conflicts` among them —
  and the measurements page silently stopped being written while the steward sweep failed every tick,
  each swallowed by its caller's own guard. Prod was stale independently, in its own place. A governance
  test compares a module's call sites with the SCRIPT's table, which is in git; the truth is in two
  tenants, and it passed throughout both failures. `_reconcile`'s docstring already said it: *"A table is
  only the truth if something applies it every time."*
- **`FABRIC_SWEEP_LIMIT` ends the WHOLE walk, not a folder.** `fabric_reconciler.sweep` counts `seen`
  across the entire sweep; `if seen >= limit: break` leaves the inner loop and `while stack and
  seen < limit` then exits too, **with every unvisited subfolder still on the stack**. At `5`, the pilot
  drive's 6-file root consumed the budget and no subfolder was EVER visited: 4 collab-file records
  against 119 files, for weeks, while the log read `swept: 1 change(s) published` — four files already
  known plus the fabric's own `fabric-metrics.md`, which the loop guard then drops. That is exactly what
  a quiet, fully-ingested library looks like. Prod was the control case: a 2-file library stays under the
  cap and descends correctly, so the same code was right there and wrong here, decided only by size.
  A second, independent defect sits behind it: `collab_list` PAGES and the sweep reads one page per
  folder, ignoring `more` and `cursor` (`Architectures` returns `50 items, more=True`). Raising the limit
  is also a BACKFILL — each newly-seen file is one `artifact_intake` run, i.e. one LLM classification —
  but it cannot double-queue: the ingress submits with `idempotency_key = pointer_key@version`, claimed
  `SET NX EX` with a 24 h TTL.
- **A deploy ships IMAGES, not SETTINGS.** CD and `deploy/railway.py release` move the image tag and
  redeploy; neither hands an app a new `.env`/`.env.azure` value. `substrate up` (and `workload <n> up`)
  is what writes each role's env slice. Measured: `FABRIC_VOCAB_REFS` sat correctly in `.env.azure`
  through a successful prod deploy while prod served NO domain vocabulary — `semantic_schemes` simply
  omitted `cafe`, and every subject term would have been a silent miss. Also: prod's artifact store is a
  different database, so dev's `art://` refs are dead there and the masters must be uploaded per tier.
- **Judge CD by the `deploy` JOB, never the run conclusion.** A run whose `deploy` succeeded reads
  **"cancelled"** overall whenever `deploy-prod` is waiting on the production environment's required
  reviewer — which it had been on every run since 28 Sep, leaving Azure 14 commits behind while each run
  showed two greens and a grey. The mirror image also bites: a watcher gated on the RUN completing stayed
  silent for 30 minutes while the deploy had succeeded 15 minutes in. Check the job, and confirm with
  `deploy/railway.py substrate versions`, which compares what each service was ASKED to run with what it
  SAYS it is running.
- **An allow-listed folder is a FOLDER, not a promise about what people put in it.** `FABRIC_ALLOWLIST`
  grants a path, and the folder's CONTENTS then change without anything in the lab changing: the
  entry for the organiser's `Recordings` folder was added for the meeting `.txt` transcripts, and
  measured 6 Oct 2026 that folder held **145 files — 28 `.mp4` recordings and 42 per-lane `.json`
  dumps beside the 35 `.txt`**. Nothing downstream filtered by extension, and the classifier read a
  file's NAME and path and not its bytes — so a raw recording would have been catalogued as a document
  with a plausible type and its own draft-review approval, noise a steward cannot tell from a real
  document. (The classifier has since been given a bounded excerpt of what it classifies — see below —
  but that does not retire the filter: an excerpt of an `.mp4` is not a document either, and the sweep
  must decide what to take in BEFORE a classifier is paid to look at it.) The entry was correct the day it was written and became wrong later, with no code change
  and no failing test; only `FABRIC_SWEEP_LIMIT` had kept the sweep from reaching those files, which
  means the earlier defect had been MASKING this one. So the sweep now decides on what the fabric can
  READ — `fabric_reconciler.SWEEPABLE_KINDS` via `filetypes.kind_for` — and never on a deny-list of
  what it has already met, because a deny-list is wrong about every format nobody has thought of yet.
  `artifact` is excluded deliberately: a lab-produced render arrives through the always-admitted `lab`
  door carrying the product and run that made it, which a swept copy of the same bytes could not. The
  filter bounds what the sweep TAKES IN, not what it maintains — a record that already exists is still
  told when its bytes change, or the catalogue would keep asserting a version that is no longer true.
  The consequence to remember: a filtered sweep goes SILENT about a folder whose files it cannot read,
  and that silence looks exactly like a sweep that is broken.

- **The classifier reads the document, within a bound — and the catalogue still holds no content.**
  Two statements that sound contradictory and are not. The CATALOG RECORD is content-free and
  structurally so: `CatalogEntry` has no field a body could go in, a title over 300 characters is
  refused as "a label, not a body", and the graph shape is `sh:closed true`. The PIPELINE, since
  6 Oct 2026, does read bytes: `artifact_intake._excerpt` passes the first `EXCERPT_CHARS` (2000) to
  the classifier, fetching a collab pointer's file into the upload store first. Before that it was
  shown a title, a file name, a path and 123 concepts and asked what the document is about, which on
  the live catalogue produced `Clinical document` on 39 of 93 records and a meeting about a
  note-taking app filed under `Teleconsultation`.
  State the distinction carefully whenever the fabric is compared with an index that ingests content
  (the market scan marks such products `✕ custody — content moves in`): the fabric does not COPY
  content into its store of record, and the source still decides who may read at read time. It does
  now READ content, transiently and bounded, to decide what an artifact is about. "We never touch the
  bytes" was true in September and is not true now; "the catalogue holds only descriptions, links and
  status" (BRS principle 2) remains true and is enforced by the schema rather than by habit.

## The semantic tools' published contract (`contracts/semantic-tools.json`)

What an external consumer binds to — today the SAF pack, which is the taxonomy master at go-live and
implements the fabric's spec verbatim behind a port (user decisions 24 Oct 2026, FR-5). One JSON file:
`server`, `contract_version` (semver, bumped BY HAND in `lab.substrate.mcp.semantic.contract.VERSION` —
major for a removed/renamed stable tool or a breaking schema change, minor for an addition), every
tool's `name`/`description`/`inputSchema`/`outputSchema` as the server registers them, the grant tuples
(`READ`, `PIPELINE`, `PROMOTE`, …) and a `stability` per tool. The tiers live in ONE place,
`SemanticTools.STABLE` / `IN_FLUX` (everything else is `internal` — not a surface for anyone outside the
lab). Regenerate with `PYTHONPATH=src .venv/bin/python scripts/render_semantic_contract.py` (offline);
`tests/governance/test_semantic_contract_is_current.py` fails until the committed file equals what the
server registers, byte for byte, and tells you to bump the version when the surface changed.

## Channel-agnostic vocabulary proposals (24 Oct 2026, user decisions FR-7/8/10 + handover)

Vocabulary is proposed FROM THE DOCUMENT and confirmed by people working in WORDS, identically through any
channel (contract `contracts/semantic-tools.json` 1.1.0):

- **Relations carry provenance** — `semantic_vocab_relation_propose(scheme, subject, predicate, object,
  evidence="", actor="", proposed_for="")`: ends may be labels (resolved, ambiguity refused); proposers and
  artifacts accumulate on the ONE idempotent question; `semantic_vocab_relation_open` returns
  `proposed_by`, `proposed_for`, `proposals`, and the ontology card shows them.
- **"existing" in words** — a steward answers `existing:<concept label or id>`; `FabricService.vocab_amend`
  resolves the word (also via `POST /api/vocabulary/aliases`).
- **The author confirms first** — a term EXTRACTED by `artifact_intake` is parked `awaiting-author`
  (`semantic_vocab_resolve(..., awaiting_author=True)`), off the steward queue until the owner's review card
  answers its `term:<candidate>` item: `confirm` | `rename:<word>` | `remove` (withdrawn BY THE AUTHOR,
  `fab:withdrawnBy "author"`), applied through `semantic_vocab_author_confirm(candidate, decision, actor,
  label="")`. A term a PERSON proposes through a channel skips the step: the proposer is the author.
- **Handover** — `semantic_vocab_candidates_import(rows, actor)` seeds the candidate register (Pending /
  Withdrawn terms and relations) from another master, idempotently, so a decline made in SAF is never asked
  again; `Admitted` rows are checked against the vocabulary (admissions travel in the master). PROMOTE grant.
- A declined relation stays closed on re-proposal (pinned by `test_a_DECLINED_relation_is_never_asked_about_again`).

## Reopen, author timeout, frozen subjects (FR-16 · FR-17 · FR-18, 24 Oct 2026)

Three product rules from SAF becoming a channel, all in `lab.core.semantic.fabric.service`:

- **A decline has a repair path (FR-16).** `semantic_vocab_reopen(target, actor, reason, scheme="")` —
  `target` is a candidate IRI, a relation-question IRI, or a term's LABEL. Only a declined row reopens
  (steward decline, author removal, or an imported/seeded decline); it returns to PENDING with its evidence
  (`proposed_for`, proposers) kept, and the "already asked" marker goes with the decline, so the normal
  queue asks a steward afresh. The decline's facts move onto a `fab:Reopening` record with who reopened it,
  why and when — nothing is erased. PROMOTE grant. `semantic_vocab_candidates_import` takes
  `status: "Reopened"` rows (`declined_by`, `decline_reason`, plus the reopening `actor`/`reason`),
  idempotently. A decline now REPLACES the row's state (a declined row used to keep `InReview` beside
  `Withdrawn`).
- **Vocabulary never blocks the forum (FR-17).** A term extracted from an artifact waits for its author
  from `fab:awaitingSince`; after `FABRIC_AUTHOR_CONFIRM_HOURS` (default 24) of WORKING time — Monday to
  Friday, UTC (`lab.core.semantic.fabric.workdays`) — it goes on with `confirmation: timeout`, and the
  steward's card says **UNCONFIRMED by the author**. `confirmation` on a candidate row is `author`
  (confirmed), `person` (a person proposed it), `timeout`, or "" (never waited). The reconciler runs
  `semantic_vocab_author_timeouts(hours?)` on its sweep, BEFORE raising questions; a legacy awaiting row
  with no start time starts its clock rather than timing out. TIMERS grant (curator only).
- **A ratified record's subjects freeze (FR-18).** `semantic_catalog_freeze(iri, actor, reason="")` records
  a `fab:SubjectFreeze` in the curated graph (its own node — the artifact's shape is closed). From then on
  no automated path changes what the record is about: `graph_assert` of `dct:subject` below rung H
  answers `frozen: true` and writes nothing (admission propagation included), and `vocab_link` (so a
  re-read or `semantic_catalog_reclassify`) returns `frozen: true` with `frozen_skipped`, retracting
  nothing. A steward still changes it at rung H (`semantic_edge_assert` rung H, `semantic_edge_retract`,
  `semantic_promote`). `semantic_catalog_get` reports `subjects_frozen`. PROMOTE grant.

Contract: `contracts/semantic-tools.json` 1.2.0 — the three tools are in-flux.
