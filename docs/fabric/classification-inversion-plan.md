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

### Phase 3 — specificity
- **3.1** concept document-frequency across the catalogue.
- **3.2** link strength on the subject edge — a concept on most of the corpus carries little.
- **3.3** "related documents" ranks by the RAREST shared concept, not the count of shared concepts.

### Phase 4 — topology (steward B)
- **4.1** propose/accept `broader` / `related` between ADMITTED concepts. Today `broader` is settable only
  at proposal time, so the relation graph is effectively frozen after publication.
- **4.2** a structured diagram yields relation candidates — its boxes are terms, its arrows are relations.
  **This is the only feeder steward B has.**

### Phase 5 — fidelity
- **5.1** render-to-text records WHICH rendering the text came from, and its fidelity.
- **5.2** fidelity rides the assertion: a concept grounded in one provider's transcript is weaker evidence
  than the same concept in the document itself. Measured, not theoretical — Teams' own transcript of a
  bilingual meeting returned 53 words against soniox-en's 97, having silently dropped a language.

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
