# Both readers: the classifier supplies SUBJECTS, the extractor supplies CANDIDATES

Status: proposed (Oct 20 2026) · Amends `2026-10-17-classifier-inversion.md` · Informs
`lab.workloads.artifact_intake`, `FABRIC_EXTRACT_FIRST`

## What the UAT measured

Three documents, the same text read both ways, on the live corpus.

| | classifier (taxonomy-first) | extractor (inverted) |
|---|---|---|
| S1, a document the vocabulary COVERS | **5 subjects, all correct**, 0 candidates | **0 subjects**, 7 candidates |
| S2a/S2b, documents it does NOT cover | **no subjects** — the honest answer | no subjects, 11 candidates |
| terms found that the vocabulary lacks | 2, and the two documents did not agree on them | 7, named consistently and grounded in spans |

The extractor is not wrong. `Repeat dispensing`, `Dispense audit event`, `Pharmacy integration
interface` are faithful readings. None is a vocabulary LABEL, so tier 1 matched nothing — the plan's own
Phase 0 measurement (zero of thirty terms on real prose) arriving in production.

## The decision this overturns

The ADR of 17 Oct rejected taxonomy-first because **a closed set anchors the answer** — `UseCase` on 37
of the 40 records carrying any subject, `Clinical document` on 39 of 93.

**That measurement was taken when the classifier read a FILE NAME.** Since 6 Oct it reads a 2000-character
excerpt, and S2 proves the anchoring is gone: shown two documents about device calibration and supplier
contracts, a healthcare-shaped vocabulary in front of it, the classifier returned **nothing**. The failure
the inversion was built to fix had already been fixed by giving the classifier the content.

What the inversion still buys is the OTHER half: finding the words the vocabulary does not have. On that
the extractor is plainly better — 7 grounded terms against 2 inconsistent ones.

## Decision

**Run both. Neither replaces the other.**

1. **The classifier supplies SUBJECTS.** It is measurably good at matching a vocabulary it can see, and
   measurably honest when nothing fits.
2. **The extractor supplies CANDIDATES only.** Its terms never become subjects. `FABRIC_EXTRACT_FIRST`
   becomes `FABRIC_EXTRACT_ALSO`: the flag stops choosing a reader and starts adding one.
3. **Tier 2 proposes aliases on the extractor's terms**, turning the steward's expensive question ("what
   does this mean and where does it sit?") into the cheap one ("is this another word for X?").
4. **The extractor's contribution reaches the graph THROUGH THE GATE** — a steward admits or aliases, and
   `_propagate` links the documents that asked. That is the governance story the design already wanted.

## Why not keep extract-first

Because it takes the corpus dark. With it on, the only path from a term to a link runs through a human, so
until a steward works the queue there are no subjects — and `semantic_related`, the owner's subject card
and the concept ring all go quiet, each of them silently. A design whose correct behaviour is
indistinguishable from an outage is the wrong default, whatever its reasoning.

## Costs, stated

- **Two model calls per document** instead of one.
- **The ADR's defining claim is amended.** Subjects no longer come from a reader shown no taxonomy. The
  reader shown no taxonomy now does discovery, which is the job the evidence supports.
- **The candidate register fills faster** — 18 candidates off 3 documents. `FABRIC_CANDIDATE_THRESHOLD`
  is what keeps that off a steward's card, and it will matter more than it did.

## The defect this found, which is the reason to trust the measurement

`semantic_concept_match` raised `'list' object has no attribute 'items'` on EVERY live call: a
`DomainScheme` — the vocabulary the fabric OWNS — answers `live()` with a list, while the reference
schemes the tests use have no `live()` and take the dict branch. So tier 2 was dead in production and
`artifact_intake` swallowed it by design. Eighteen candidates came off three documents with not one alias
proposed and nothing said it was broken.

Fourth instance in two days of ONE shape: **a test double more forgiving than production.** It is now the
dominant failure mode in this codebase, well ahead of logic errors.
