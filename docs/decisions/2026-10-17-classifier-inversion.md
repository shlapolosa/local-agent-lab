# Classify by EXTRACTING first and matching afterwards, not by offering a model the taxonomy

Status: decided (Oct 17 2026; recorded Oct 19) · Supersedes the taxonomy-first classifier ·
Informs `lab.core.semantic.fabric.{concepts,relations,renderings}`,
`lab.workloads.artifact_intake`, `SemanticTools`
· Implementation plan and measurements: `docs/fabric/classification-inversion-plan.md`

## Requirement

The fabric must classify any artifact, link it to related artifacts with high confidence, and keep
doing both as the vocabulary grows from ~130 concepts to a DOH-scale one. Stated by the user as the
goal the whole exercise serves: *"a process that allows us to ingest any artifact, classify it and
link it to any related artifact with high confidence."*

## The problem, measured not suspected

The classifier handed a model ~130 concept definitions and asked which fit. Two failures:

- **A closed set anchors the answer.** `UseCase` on 37 of the 40 records carrying any subject;
  `Clinical document` on 39 of 93. A model offered a list will pick from the list.
- **It cannot survive a real taxonomy.** ~130 concepts fit in a prompt; a tenant vocabulary does not,
  and "the relevant concepts" is a retrieval problem wearing a classification mask.

A third, found while measuring and worth keeping separate: **71 % of records carry no subject** is a
statement about corpus composition, not classifier quality — 154 records, six of them documents. See
`docs/fabric/` and the catalogue-composition finding. The inversion does not fix that and was never
meant to.

## Decision

**Invert it.** An *extractor* agent reads the artifact and says what it is about **in its own words**,
shown no vocabulary and no concept list. Everything after it is deterministic: ground the evidence,
normalise, then match in tiers.

1. **Three outcomes, not two** — a term either matches a concept (link it), matches two (a conflict
   for a steward), or matches none (park a candidate). The third is the one the old design could not
   express, and it is the one that grows the vocabulary.
2. **Two agents, clean separation** (user decision): an extractor that is shown no taxonomy, and the
   existing classifier keeping the document TYPE — a closed set of ten, where being offered the list
   is correct because the list is the answer space.
3. **Flag-guarded coexistence** (user decision): `FABRIC_EXTRACT_FIRST`, default off. Not a
   replacement commit.
4. **Confidence is several signals, not one** (user's framing, "like the idea of a confidence
   score"): salience (how central the term is to the document) × grounding (the span is really in the
   text) × match quality × specificity (how much the concept narrows the corpus) × fidelity of the
   rendering the text came through. Each is computed in one place and none is folded into another.
5. **Two stewards, because there are two jobs** (user decision): steward **A** decides MEMBERSHIP —
   what the vocabulary contains; steward **B** decides TOPOLOGY — how its concepts relate. B had no
   acts at all before this.
6. **Phase 0 was a gate, not a warm-up.** Measure on live records first, with the authority to cancel
   two of the three tiers. It did change the design (below).

## Why not keep taxonomy-first

Because the anchoring is not a prompt-engineering problem. The list is in the context; the model's job
becomes selection from it; and the failure is invisible — `UseCase` on 37 of 40 records reads as a
corpus about use cases, not as a classifier that cannot say "none of these".

## Why not the NAIVE inversion — this is the reasoning that shaped the plan

The obvious version of this is a **regression**, and the reason is worth stating plainly: **today the
definition check happens inside the model's head.** The classifier is shown each concept's definition
and told that when a definition and a label disagree, the definition wins and the label is a trap
(`skills/fabric-classification/SKILL.md`). `vocab_link` is purely lexical, and it is safe *only
because* the labels reaching it were chosen by something that had read the definitions.

Remove that and an extractor emitting `{term: "encounter", span: "the encounter was productive"}`
hands the lexical matcher a perfectly grounded term that links `Encounter` — a care interaction — at
rung **X**, which `IMPACT_READS` trusts and `derive` turns into `relatedTo` edges.

**Grounding makes the wrong link *more* confident, not less: the span really is in the document.** So:

- **the lexical tier may not write unchecked** — a term matching two concepts in one scheme
  short-circuits to a steward and must not fall through to the semantic tier;
- **the semantic tier proposes, never disposes** — it may rank options on a steward's card; admitting
  a concept widens what every future document is classified against, and choosing between two
  meanings narrows it, and neither is a question a model may settle;
- **ungrounded degrades, it never deletes.** `vocab_link` replaces a record's extracted subjects
  wholesale and `_excerpt` returns `""` on any failure, so composed naively one storage blip retracts
  every rung-X subject on a record — and under a reclassify sweep, across the estate.

## Why an LLM first and a deterministic matcher second (not spaCy first)

The question was explicitly "spaCy then LLM, or LLM then spaCy?". A model is the better *extractor*
because what a document is about is a judgement about salience, and it can say so with an evidence
span. It is the worse *matcher*, because matching is a decision with consequences for the vocabulary
and must be reproducible, inspectable and testable without a model. So the model proposes terms and
pure functions decide: `concepts.ground/normalise/match`, tested like `citations.py`.

**A margin, not a threshold.** Measured on live records: a 1–2 word term against a 1–2 sentence
definition compresses scores into a narrow band, so the gap between the top two separates a real match
from an arbitrary one where an absolute floor cannot — `'proposed decision status'` ranked top against
*Prior authorisation* at a margin of 0.0016, which any threshold low enough to admit real matches
waves through. Accepted matches scored 0.36–0.52 with margins of 0.08–0.13.

## Alternatives considered and rejected

| rejected | why |
|---|---|
| **Store link strength on the assertion** | Specificity is a property of the corpus NOW. A concept that distinguished a document among forty stops distinguishing it among four thousand, and a frozen number keeps insisting otherwise. Computed per call instead. |
| **Feed shared-concept links into `impact`** | They are associative, not causal. Impact would then report that every change breaks everything it resembles. Impact stays driven by references and delivery context. |
| **Rank related documents by how MANY concepts they share** | Counting rewards the hubs: five shared concepts that everything shares say nothing, one rare one says something exact. Ranked by the rarest shared concept. |
| **Return every shared-concept link** | A concept on every record scores exactly zero. Returning those padded one real answer with thirty-six non-answers a caller — especially a model — cannot distinguish from the answer. |
| **A fidelity NUMBER** | The defensible claim is an ORDERING (a translated transcript is further from the artifact than a verbatim one) and the measurements support an ordering, not a probability. No experiment here yields "a transcript is 0.7 of a document", and an invented number reads as a measured one. A RANK. |
| **Fidelity per assertion** | Nothing in this layer reads per-assertion provenance — `FAB.confidence` has been written since the beginning and is read nowhere. It rides the record, which one run reads once; and monotone downward, since subjects accumulate across runs. |
| **Park relation candidates durably** | A term candidate arrives one document at a time and must wait to be batched; a relation candidate is only answerable with the diagram in front of the person. Nothing durable means nothing to replay and no second lifecycle to keep honest. |
| **A number for salience reusing `subject_floor`** | That dial gates a model's confidence in the MATCH; salience is how central a term is to the DOCUMENT. Different quantity, same dial. |
| **One agent with an extended schema** | User decision: two agents, so the extractor can be shown no vocabulary at all. Its defining property is what it is NOT shown. |

## Addendum, 19 Oct 2026 — the ontology queue, and what testing it found

**Steward B got a queue.** The acts existed (`vocab_place`, `vocab_relate`) and nothing announced that a
decision was waiting, so the only way in was a curator identity calling tools by hand. Now:
`ApprovalKind.CONCEPT_RELATION`, a register, an applier (`lab.substrate.fabric_ontology`), and a third
Teams channel.

- **A THIRD AUDIENCE, not a second kind on the steward's queue.** `ApprovalAudience` was OWNER/STEWARD
  and is now OWNER/TAXONOMY/ONTOLOGY. "Steward" stopped distinguishing anything the moment there were two
  steward queues; the audiences are named for the JOB. The partition test is three-way and exhaustive,
  because a kind in no set is announced to nobody, silently.
- **The register is `_conflict`-shaped, not `_candidate_for`-shaped**, and that is what keeps it small. A
  term candidate must be durable because it arrives one document at a time over weeks. A relation
  candidate is RECOMPUTABLE — both producers regenerate theirs every run — so only ASKEDNESS and REFUSAL
  are durable and openness is DERIVED. A relation the vocabulary now states leaves the queue by itself,
  however it came to be stated, so no path has to remember to clean up after itself.
- **Two producers, one kind**: a diagram's arrows (sharp, but only where diagrams are ingested) and
  co-occurrence over the corpus (works on the corpus a tenant already has). Neither may settle a
  relation — an arrow says two concepts connect and not how, co-occurrence says they turn up together
  and not why, and a predicate the fabric invented would be an edge no author drew that the derived rung
  then reasons over as if somebody had.
- **Four answers**, because three would be wrong: `relate`, `relate:<predicate>` for an arrow drawn
  without one, `broader` (an arrow is sometimes a hierarchy, and only a person reading the diagram can
  tell), and `decline`.

**And `samples` was split from `choices`.** The review app offered an item's samples as its pick list —
right for the use-case questions, whose samples ARE the answers, and wrong for the intake's, whose samples
are prose and scores. Choosing the offered `context` wrote `urn:fabric:context:project:alpha (0.92)` as a
rung-H assertion: a record marked associated, at the fabric's highest rung, under a context that does not
exist. Nothing downstream refuses it, because the OBJECT of a triple is the one end never validated. Now
`choices` are answers, `samples` explain, and an item declaring no choices is free text — so a producer
cannot make a sentence selectable by accident.

## Consequences

- **An extractor's prompt must stay free of the vocabulary.** If a future change passes concepts into
  it "for context", the design is back to taxonomy-first with extra steps and nothing will fail.
- **A new curation act must land with its `_replay` branch in the same commit**, or it is recorded
  faithfully, replayed never, and lost at the first boot: durable and invisible.
- **The semantic tier needs an embedder**, and an unavailable one must mean "tier 2 unavailable, tier
  3 takes it" — never a refusal to start. Concept vectors are lazy for that reason: `boot()` is
  synchronous and runs before `serve()`, so a flapping embedder would take `catalog_get`, `impact` and
  every view down with it.
- **Four new tools need their grants applied in three places** (dev LiteLLM team, prod APIM policy,
  image); a catalogue entry grants nothing.
- **A facet now lives in four places** — `FACETS`, `fab.ttl`, the closed SHACL shape, the row — and
  `tests/governance/test_fabric_facets.py` holds them in parity, because adding the fifth touched all
  four and nothing would have failed had one been missed.
- **Steward B's only feeder is a structured diagram.** If diagrams are not ingested, topology does not
  grow, whatever acts exist.
