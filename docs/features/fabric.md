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
  dumps beside the 35 `.txt`**. Nothing downstream filtered by extension, and the classifier reads a
  file's NAME and path, never its bytes — so a raw recording would have been catalogued as a document
  with a plausible type and its own draft-review approval, noise a steward cannot tell from a real
  document. The entry was correct the day it was written and became wrong later, with no code change
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
