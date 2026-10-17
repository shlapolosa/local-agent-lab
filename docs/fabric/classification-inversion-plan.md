# Inverting the classifier — implementation plan

**The change.** Today the classifier is handed ~100 concepts and asked which fit. Instead: read the
artifact, say what it is about in its own words, and match afterwards. One model call reads; everything
after it is deterministic.

**Why**, in one line each:
- a closed set ANCHORS the answer — `UseCase` on 37 of the 40 records carrying any subject, `Clinical
  document` on 39 of 93;
- a taxonomy only fits in a prompt while it is small, so taxonomy-first cannot survive a real one;
- the vocabulary GAP becomes measurable (terms extracted vs matched) instead of showing up as thin
  subjects, which is indistinguishable from a weak classifier;
- judgement moves from `[A]` to `[D]`, which is where this lab says it belongs.

## What makes it safe to attempt now

| | |
|---|---|
| 123 of 123 CAFÉ concepts carry a definition | matching has something to match against, not just labels |
| the eRx corpus exists, 7 documents, known-good answers | the comparison is measurable rather than argued |
| candidate dedup, `proposedFor`, counts and the threshold shipped 12 Oct | the defences against a candidate flood are already in place |
| argument-parity guards (AST + Router) shipped 12 Oct | a new tool argument cannot reach the cloud unnoticed |

## Phase 0 RESULT — the gate passed (17 Oct 2026)

Measured by `scripts/fabric_extraction_probe.py` on live records, then again on the eRx documents, which
is the realistic corpus. **The two runs disagree in ways that matter**, and the second is the one to
believe: the first sampled `.csv` fixtures and a README.

| | all records | eRx documents |
|---|---|---|
| grounded verbatim | 97% | **66%** |
| grounded once whitespace is tolerated | 99% | **100%** |
| matched a concept label LEXICALLY | 2 of 78 | **0 of 30** |
| top concept's share of terms | 13% | 20% (`Dispense`) |
| median top1−top2 margin | 0.0356 | 0.0351 |

**Four conclusions.**

1. **Grounding must tolerate whitespace, and that is not a detail.** Real markdown prose wraps, so a
   third of honest spans cross a line break. A strictly verbatim rule — which the 97% invited — would
   have silently discarded a third of all terms on exactly the documents that matter.
2. **The lexical tier is dead on prose.** Zero of thirty. The extractor says "dispense confirmation
   callback"; the vocabulary says `Dispense`. It costs nothing to keep (it is `find()`, already there)
   but it is not the path — which also means the homonym risk that shaped the design is *rare*, not
   absent, and the definition check still belongs somewhere.
3. **The semantic tier finds the right concepts** on real documents — `Dispense`, `Prescription item`,
   `Pharmacy`, `Audit event` — and does NOT collapse onto a hub the way the old classifier did.
4. **The margin is the whole decision.** At a 0.05 gate, 11 of 30 are accepted and every one is
   defensible; the 19 rejected include `budget planning support → Service request` and `dead-letter
   handling rota → Migration disposition`, which an absolute threshold would have written to the graph
   as facts. The cost is recall: `pharmacy prescription retrieval → Pharmacy` is right and is rejected
   because two concepts scored within 0.01. That is the correct trade — a wrong edge is worse than a
   missing one, and a rejected term is not lost but escalated to a steward as a candidate.

Also found, and fixed before any of this shipped: **admission has never linked the documents that asked
for a term** (`_propagate` read a key `_admit` does not return, and the test's fake invented it), and the
review card never said which subjects a run took away.

## Phases

### Phase 0 — prove it, change nothing  *(the gate)*

- **0.1** an extraction skill + schema (`term`, `evidence_span`, `salience`) — a NEW skill beside the
  classifier, replacing nothing.
- **0.2** an offline harness that runs BOTH over the same 7 eRx documents.
- **0.3** four numbers per document: subjects produced · how many are defensible by eye · share of
  extracted terms that matched · what the unmatched set contains.

> **GATE.** If extraction-first does not produce more defensible subjects per document AND a more
> informative unmatched set, stop here and keep the taxonomy-first classifier. The inversion is a bet
> about anchoring and scale; this is the cheapest place to find out it was wrong.

### Phase 1 — the deterministic lane
- **1.1** `lab.core.semantic.fabric.concepts.ground(term, span, text)` — pure; the span must be present
  verbatim or the term is discarded.
- **1.2** `normalise(term)` — pure; lemmatise, strip determiners. Start without spaCy; add it only when
  matching proves brittle on inflections.
- **1.3** `match(term, candidates, threshold)` — pure rule over candidates proposed by embedding the term
  against concept **definitions**. One-off index build over the 123 definitions.
- **1.4** intake takes the three-way outcome. Tests at every step; the rule is pure, so it is cheap.

### Phase 2 — alias as a first-class candidate
- **2.1** candidate KIND: alias vs concept — they are different questions with different costs.
- **2.2** `vocab_propose` (or a sibling) accepts an alias proposal naming the concept it would join.
- **2.3** steward A1 batch card: "is this another word for X?" — seconds each.
- **2.4** on admit, write the `altLabel`; the next document using that word matches deterministically and
  never reaches the embedder. **The vocabulary improves itself.**

### Phase 3 — specificity — DONE (17 Oct 2026)

- **3.1** `concepts.specificity(df, total)` — `log(N/df)/log(N)`, so a concept on every record scores 0 and a
  concept on one scores 1, on a scale that does not change meaning when the corpus grows.
- **3.2** **link strength is NOT stored on the assertion.** It is computed per call, over the graph as it
  stands: a concept that distinguished a document among forty stops distinguishing it among four thousand,
  and a number frozen at assert time would keep insisting otherwise. The population is the records that are
  about something at all — a record with no subject is not one this concept failed to distinguish.
- **3.3** `concepts.rarest()` / `relatedness()` + `FabricService.related()` + the governed tool
  **`semantic_related`** (catalogue `SemanticTools.related`, in `READ`). Ranked on the RAREST shared concept,
  with ties broken on the concept id so the order is the same on every call. Each row names the concept that
  earned the rank, because a score with no `via` is a number a person cannot check.

  Read at `IMPACT_READS`, so a model's suggestion at rung S never ranks as a relation. One scan of the
  subject assertions serves both the shared sets and the frequencies.

**The complement of `semantic_similar`, not a duplicate of it**: `similar` embeds a record's facets and
answers "what reads like this"; `related` reads asserted subjects and answers "what is about the same
thing". The first is a guess that needs no vocabulary; the second is evidence and names it.

**Deliberately not fed into `impact`** — shared-concept links are associative, not causal, and feeding them
in would make every change appear to break everything it resembles.

**Three things design review changed, all of them about what the answer must NOT contain:**
- **A link worth nothing is not returned.** A concept carried by every record in the population scores
  exactly zero. Returning those rows padded one real answer with thirty-six non-answers a caller — and
  especially a model — cannot tell apart from the answer, while the filter was already computed and thrown
  away. The consequence is deliberate: where every record shares one subject, that subject relates nobody.
- **A withdrawn record is hidden** unless that state is asked for, exactly as in `search`. The same corpus
  must not answer "what reads like this" without it and "what is about the same thing" with it.
- **The catalogue is read only for what is RETURNED.** Hydrating per candidate was one Neon round trip per
  record sharing any concept — ~36 queries to return 20 rows today, ~4,000 at corpus scale — for a title.
  Ranking happens on the in-process graph; `limit` reads follow, and `limit` itself is capped at 100.

Grants follow from `READ`, which both `scripts/provision_fabric_agents.py` and `deploy/grants.py` derive
programmatically — but each still needs its apply run before a caller sees the tool.

### Phase 4 — topology (steward B) — DONE (17 Oct 2026)

Steward A decides MEMBERSHIP; steward B decides TOPOLOGY. Both acts are in `PROMOTE`, never `PIPELINE`, for
the reason `vocab_amend` is: an agent that could reorganise the vocabulary it is classified against would be
marking its own homework.

- **4.1** two acts, because they write two different things — a parent is a concept COLUMN and a relation is a
  relationships ROW:
  - `DomainScheme.place` / `vocab_place` / **`semantic_vocab_place`** — put an admitted concept under a
    broader one, or lift it back to the root. `broader` was settable only at proposal time and the batch card
    deliberately collects no parent, so nearly every admitted concept arrived unplaced and the hierarchy froze
    at admission. A cycle is refused by NAME (the level is recomputed, and `_level_of` walks with a seen-set),
    a retired concept is refused at either end, and every DESCENDANT's level is recomputed — a stale level
    would misreport the depth of a whole subtree.
  - `DomainScheme.relate` / `vocab_relate` / **`semantic_vocab_relate`** — a TYPED relation, because
    `skos:related` cannot carry what the derived rung needs. Dangling end, retired end, self-relation and
    duplicate are each refused by name.

  **`_replay` learned both in the same change**, which was the trap: a curation act the replay does not know
  is recorded faithfully, replayed never, and so lost at the first boot — durable and invisible. `recurate`
  raises on an unknown act, so the test that matters asserts `failed == 0` after a reseed. Admissions still
  replay first and in passes, so a placement naming a freshly admitted parent applies either way.

  Both survive publication: the concepts master already carries `parent`, and the relationships master is
  rendered from `scheme.relationships` — so a steward's topology reaches the corpus unchanged.

- **4.2** `lab.core.semantic.fabric.relations` + **`semantic_vocab_relation_candidates`** — a diagram's boxes
  are terms and its arrows are relations, in the shape `storage_read_vsdx` already returns. Pure, with the
  vocabulary arriving as two seams (`resolve`, `states`), so one function serves a `.vsdx`, a Lucidchart
  export or anything else that yields boxes and arrows. Three decisions:
  - **a box the vocabulary cannot name is a GAP, not an error** — a term a steward can admit, and dropping it
    silently is how a diagram stops being evidence;
  - **an AMBIGUOUS box resolves to nothing** — choosing between two meanings narrows the vocabulary, which no
    diagram may settle;
  - **an unlabelled arrow is a candidate marked `unnamed`** — the diagram says two concepts connect, not how,
    and a guessed predicate is an edge no author drew.

  It parks nothing, deliberately: a term candidate arrives one document at a time and must wait to be
  batched, while a relation candidate is only answerable with the diagram in front of the person. Nothing
  durable means nothing to replay and no second lifecycle to keep honest.

### Phase 5 — fidelity — DONE (17 Oct 2026)

- **5.1** `lab.core.semantic.fabric.renderings` — the ladder, as a registry: adding an input source is one
  line. **Fidelity is a RANK, not a score.** The honest claim is an ORDERING, and this lab has the
  measurements for an ordering rather than a probability: on one bilingual recording the tenant's own
  transcript returned 53 words having silently dropped every Arabic turn, a verbatim provider returned 86-97
  with both turns present, and an English rendering returned 97 translated. No experiment here yields "a
  transcript is 0.7 of a document", and a number invented to look rigorous would be read as one that was
  measured. An UNDECLARED rendering is treated as the WEAKEST, never the strongest — an unstated provenance
  is where the fabric knows least, and defaulting it to the document's own words would make the least
  trustworthy evidence indistinguishable from the most.

- **5.2** fidelity rides the **RECORD**, not each assertion — a deliberate deviation from the plan's wording,
  for two reasons. One run produces one excerpt, so every term it grounds shares a rendering. And nothing in
  this layer reads per-assertion provenance: `FAB.confidence` has been written since the beginning and is
  read nowhere, so a field added there would be invisible — the shape of a defect this repo has already paid
  for twice. So `rendering` is a FACET (`fabric_artifact.rendering`, `fab:rendering`, in the closed SHACL
  shape with a two-way parity test against the ladder), asserted at X by the intake node before anything is
  linked, and returned by `catalog_get` like any other facet.

  **The sharp case is a minutes record.** It is the lab's own JSON — `structured` by how the node reads it —
  but its words are a machine translation of speech. `RENDERING_BY_PROCESS` lives in the WORKLOAD, because
  `lab.core` cannot know what the lab's processes are, and the writing process's rendering wins: evidence is
  only as strong as its weakest hop.

  **The facet is MONOTONE DOWNWARD — a record carries its weakest reading.** Design review found the hole in
  "one run produces one excerpt": subjects ACCUMULATE and a record can be read more than once, so a
  reclassify that read the document body would supersede `transcript-translated` with `document` and leave
  three concepts grounded in a machine translation on a record claiming the artifact's own words. `_weakest`
  compares against the ROW (a reclassify starts a fresh state), and it is also what gives the ladder's
  ordering its first production reader — a rank nobody consults being the exact defect this phase set out to
  avoid.

**What design review changed, beyond that** (two of them real defects it reproduced with probes):

- **A predicate is an IRI local name, not prose.** `relate` accepted any non-empty string, and the diagram
  lane feeds it arrow captions — so `"sends a prescription to"` became an IRI the scheme's own graph could no
  longer serialise. Recorded in the curated graph, it would replay on every boot and travel out through the
  relationships master: a one-way door. The author's wording lives in `note`, where `graph()` already puts it.
- **A refused placement now restores the whole SUBTREE.** `place` recomputes every level, and the service's
  rollback restored only the row it named — measured, a three-deep subtree left at depths 4 and 5 while its
  root was back at 1. `level` is not inert: `SkosScheme` puts `L{level}` into the concept doc string an agent
  is shown. The older acts (`retire`, `amend`) touch one row each, which is why copying their idiom was the
  defect; `DomainScheme.levels()` is now the one home both paths call.
- **A diagram box resolves through the classifier's own normaliser.** `find` only folds case and strips, so a
  hand-authored box arriving plural, with an article, or wrapped across two lines became a GAP asking a
  steward to admit a concept the vocabulary already held — while the relation drawn on it was dropped. That
  was the one place the two lanes could disagree about what a term IS.
- **An empty document no longer claims it was read.** The document branch returned its rendering
  unconditionally, so an empty body recorded "the artifact's own words" on a record where nothing was grounded.
- **`fab:rendering` is declared in `fab.ttl`**, and `tests/governance/test_fabric_facets.py` now holds the
  four places a facet lives in parity — `FACETS`, the ontology, the closed shape, and the row. Adding the
  fifth facet touched all four and nothing would have failed if one had been missed.
- Dropped: `curated_relationships()` (no caller — publication renders from `relationships`), `gaps` as an
  option (every caller passed it), a duplicated `reason` on the relation's curation row, and the `getattr`
  default in `put()` that would have stored `''` for a column whose field was forgotten. The duplicate check
  now folds case, as `find` and the diagram lane both do. `MAX_ARROWS` refuses an oversized diagram rather
  than halving it silently; the by-ref door is the upgrade when a model rather than a steward surface calls.

## Sequencing

```
0 ──gates everything
1 ──┬─ 2 (alias needs the three-way outcome first)
    └─ 3 (independent, but only meaningful at corpus scale)
4 ── independent of 0–3; needs admitted concepts, which exist
5 ── small, any time
```

## What could kill it, and where that shows up

| risk | caught by |
|---|---|
| extraction returns vague terms ("process", "system", "data") | Phase 0's defensibility count |
| candidate volume floods the steward | Phase 0's unmatched-set inspection; the threshold already exists |
| embedding match too fuzzy on two-word terms | Phase 1.3 threshold tuning on the eRx set |
| cost — one embedding per extracted term per document | measurable in Phase 0; the alias loop reduces it over time |

## Not changing, deliberately

- **document type** stays a closed-set choice — small, stable, and anchoring is appropriate there;
- **citations** stay their own path (`doc —references→ doc`), shipped 12 Oct;
- **impact** stays driven by references and delivery context. Shared-concept links are ASSOCIATIVE, not
  causal: two documents about Dispensing do not invalidate each other, and feeding concept links into
  impact would make every change appear to break everything it merely resembles.
