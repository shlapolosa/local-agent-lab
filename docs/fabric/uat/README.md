# UAT: author → taxonomy → ontology → research

Six documents, three scenarios, one arc. The point is not that the fabric works; it is that each
step is DISTINGUISHABLE from the step before it failing silently — which is how every defect found
on 19 Oct 2026 survived a green test suite.

Upload them to the pilot library (`AI Use-Case Intake PoC` → `Documents`). The reconciler sweeps on
its tick; a deploy restarts the gateway, so leave a few minutes after one before uploading or the
runs fail at preflight and need `workflow_replay`.

**Two thresholds shape this, and both are deliberate.** `FABRIC_CANDIDATE_THRESHOLD=2` — a term used
by ONE document is parked and never raised, because a term met once is usually somebody's phrasing.
`FABRIC_RELATION_MIN_RECORDS=3` — the corpus must put two concepts together three times before it is
taken to be saying they relate. That is why S2 is a pair and S3 is a trio.

---

## S1 — everything matches. No steward, no card beyond the owner's.

`S1-repeat-dispense-note.md`, written entirely in existing concepts and in natural prose
("prescriptions", "the pharmacy", not bare labels).

| expect | where | why it matters |
|---|---|---|
| `Prescription`, `Prescription item`, `Dispense`, `Pharmacy`, `Medicinal product`, `Clinician`, `Encounter`, `Audit event` at rung **X** | `semantic_catalog_get` | tier 1, no human. The PLURAL "prescriptions" only reaches `Prescription` because of the normaliser fix — before it, this missed and parked a duplicate candidate |
| **no** new candidates | `semantic_vocab_candidates` | a document the vocabulary already covers must cost a steward nothing |
| an OWNER card with `document_type` **and up to three `subject:` items** | `pilot-approvals` | the author confirms what their document is about — new, and the reason subjects can now be trusted |
| answer `keep` on one, `drop` on another | | `keep` promotes X→H and survives the next sweep; `drop` records a durable NO and does NOT come back |

**Then publish it.** `derive` runs on publish, and nothing else runs it — the research step needs it.

## S2 — nothing matches. Two documents, pure stewardship.

`S2a-calibration-drift.md` + `S2b-supplier-attestation-process.md` — deliberately outside the
vocabulary's healthcare shape.

| expect | where |
|---|---|
| **no** subjects at all on either record | `semantic_catalog_get` |
| `calibration drift` and `supplier attestation` parked, `proposals: 2`, each naming BOTH records in `proposed_for` | `semantic_vocab_candidates` |
| ONE batch card, both terms on it | `pilot-taxonomy` |
| answer `admit` for both | |
| **both records gain both concepts** at X, method `vocabulary-admission` | `semantic_catalog_get` |

That last row is the one to watch: `_propagate` had NEVER linked anybody until this branch — it read
a key the service does not emit. If admission succeeds and the documents stay unconnected, that is
the defect returning, not a slow sweep.

## S3 — partial. Three documents: the existing matched, the new approved, then related.

`S3a/b/c-formulary-exception-*.md`. Three because the ontology sweep needs three.

| expect | where |
|---|---|
| `Prescription`, `Prescription item`, `Dispense`, `Medicinal product` matched at X with no human | `semantic_catalog_get` |
| `formulary exception` parked once, `proposals: 3` | `semantic_vocab_candidates` |
| a card; answer `admit` | `pilot-taxonomy` |
| all three records gain `Formulary exception` | |
| **then, next tick**: a RELATION question — `Formulary exception` ↔ `Prescription`, evidence "3 records are about both" | `pilot-ontology` |
| answer `relate:raisedOn` (or `broader`, or `decline`) | |
| the vocabulary states it; the question leaves the queue by itself | `semantic_vocab_relation_open` |

## Research — the proof the whole arc was for

Ask the Teams agent, or call the tools:

1. *"What do we know about formulary exceptions?"* → the three S3 records, each with its owner, state
   and the rung each fact came from.
2. `semantic_related` on `S3a` → `S3b` and `S3c` as its TOP neighbours, `via_kind: "shared"`, `via` =
   `Formulary exception`. It ranks top because a concept on 3 of ~70 records is specific; a concept
   everything carries scores zero and is left out entirely.
3. `semantic_related` on a record about `Prescription item` alone → S3's documents appear with
   `via_kind: "derived"`, naming the predicate. **This is the step that needs a publish**: rung D is
   rebuilt only by `artifact_publish`, so an unpublished record has no derived neighbours.

Step 3 is the one a retrieval engine cannot do: those documents share no concept at all. They are
connected because a PERSON said the two concepts are related, and the derivation walked it.

---

## What would make this a false pass

- **Subjects appearing on S2's records.** The honest answer there is none. A classifier that finds
  something anyway is the anchoring this whole inversion was built to remove.
- **A card for a term used once.** The threshold exists; if it fires at one, it is not being read.
- **The ontology card arriving before three records.** Same.
- **`semantic_related` returning everything.** A concept on every record scores zero and must be
  dropped. A long list is the padding failure, not a rich answer.
