# Two capability maps, two questions — never one word for both

**Decision, 18 Sep 2026.** "Capability map" is banned as an unqualified term in this lab. There are
two maps, they answer different questions, and conflating them is what made capability matching
look unreliable for five weeks.

| | **business** capability map | **technology** capability map |
|---|---|---|
| answers | **what ability does this exercise** | **how would we do it** |
| today | `healthcare-provider-v2.0` (BA Guild, SKOS) | `ai-capability-map` (CAFÉ M4) |
| shape | 4 levels, 1,042 concepts at the matched level | 2 levels, 58-63 capabilities |
| grain matched at | L3 | L2 |
| reached by | a MODEL match over the whole map | a deterministic key join, then an id-gated selection |
| drives | `capability_matched`, the heat-map flags, prompt context for steps 8 and 10 | guardrails -> families -> components -> cost |
| a wrong answer costs | a weaker gate reading and a worse prompt | **a wrong guardrail and a wrong price** |

## Why the distinction is not pedantry

Measured 17 Sep 2026 (see [[capability-map-is-mostly-domain-free]]): **836 of the 1,042 L3 concepts
in the business map — 80% — mention no clinical or health word at all**, and every definition is
phrased "Ability to <verb> a <noun>". A negative-control use case (a chat bot that tells the time)
matched it 3-4 times on every run, with real entries whose definitions are literally true of it
("Ability to find and recognize a time").

So **a business-capability match is not evidence that a use case belongs to the domain.** It is
evidence that the use case performs an information-handling act that the map names. The map cannot
say "not applicable", and reading it as though it could is a category error.

The same recording run through the technology map returned 1-3 solution-space capabilities, all of
which a chat bot genuinely needs, and did so with markedly less run-to-run variance.

## The rules this decision sets

1. **Name the map.** In code, prompts, schemas, corpus ids, docs and conversation: *business
   capability map* or *technology capability map*. Never the bare term. A corpus id, a step name or
   a variable called `capabilities` is ambiguous by construction and must say which.
2. **A match against the business map is a classification, not a justification.** It may inform a
   gate and a prompt. It must never, on its own, select a component, attach a guardrail or price
   anything.
3. **Identity matters on the technology map and does not on the business map.** Guardrails and cost
   dispatch on the technology capability's identity, so that path resolves by exact key and refuses
   what it cannot resolve (G04). The business path has no consumer that distinguishes siblings, so
   near-synonym choice there is not a correctness defect and must not be scored as one.
4. **Evaluation follows the consumer, not the vocabulary.** Two labels are acceptable substitutes
   when nothing downstream can tell them apart — a property of the CODE, checkable, not a judgement
   about meaning. Corollary and MECE test: two sibling concepts no consumer distinguishes are
   carrying no information, which is a defect in the MAP.
5. **The matching grain belongs to the map.** The business map is matched at L3 and deliberately
   ignores its L4; the technology map is two deep. `coverage.leaves` takes `deepest` as a parameter
   for this reason — a constant silently returns zero candidates against a shallower map, which
   reads downstream as "nothing is relevant".

## What this does not decide

Whether the two maps should be matched by the same mechanism (they are not today: one is a model
match, the other a join), and whether the technology map is MECE enough to carry guardrail
attribution. Both are open, and the second is the next piece of work.

---

## Addendum, same day — the business map is retired from the live path

**Decision.** `config.BUSINESS_CAPABILITY_SCHEME` is **empty by default**. Until this tenant names a
published map there, step 5 records a declared default (`fallbacks.FALLBACKS["coverage_map"]`) and
the feasibility verdict returns the new `Feasibility.ESCALATE` rather than `REJECT`.

**Why it is a setting and not a deletion.** CAFÉ: "CAFÉ does not supply the map; the enterprise owns
it", and a conformant one is organisation-independent, outsourcing-independent, MECE at each level,
and decomposed only to where an investment decision changes. The BA Guild workbooks satisfy none of
those *for this enterprise* — they are a generic starting map. Naming a conformant scheme in the
setting turns matching, pinning and preflight back on with no code change.

**Why ESCALATE and not REJECT.** The published rule reads "the use case serves no capability **on the
map**". With no map that is absence of evidence read as evidence of absence, and it would reject
every use case identically, citing an artifact nobody wrote. `capability_matched` therefore has three
states, and the unknown one asks an architect — the precedent set by the investment step, which
escalates by name when no delegation-of-authority table is configured. ESCALATE is placed after the
existing-realisation rule, so escalation replaces only the rule whose evidence is missing.

**Condition for reinstatement.** A map passing CAFÉ's four conformance tests, published to the
reference corpus as a vector-retrievable workbook, and its scheme named in the setting.

## Addendum — the guardrail bindings, repaired

Measured before the repair: **20 of 24 live guardrails named an enforcement point resolving to no row
in the technology map; 6 of 63 capabilities enforced anything.** Nine were label drift, eleven named a
control capability the map lacked, two were prose. `families.unclaimed()` reported all of it as corpus
silence — a legitimate state — so a typo was indistinguishable from a gap.

Repaired in the CAFÉ source (v0.25 HTML, the framework author's artifact, not a lab-side overlay):
nine `cap` references renamed to the rows that exist, eleven control capabilities added following the
v0.11 precedent, and the four whose enforcing product is a *function of* a catalogued component name
that component in their own `primary` text so the existing linker resolves them — **the link is data
the author owns, not a table in a generator script**. After: **24 of 24 resolve, no family unclaimed.**

Held by `tests/governance/test_guardrail_bindings_resolve.py` (no ratchet) and
`tests/governance/test_no_artifact_content_in_code.py` (the generator's translation tables may shrink
and never grow). The general lesson: **a join whose failure mode is an empty result needs a check that
the operands exist, because an empty result is what success looks like when the data is genuinely
silent.**

Composition move 5 — "every obligation bound to a named enforcement point on a selected component" —
was named in `composition.py`'s docstring and never implemented; `lab.core.usecase.enforcement` now
does it, gated softly on step 21. It keeps `unbound` (the design chose nothing that enforces this —
the architect's to fix) apart from `unenforceable` (the corpus cannot bind it at all — not the
design's fault), because a single count would have read as an architect who selected nothing.

## Addendum — step 5 now matches the TECHNOLOGY map

**Decision (user, 18 Sep 2026): the technology capability map replaces the business one as "the
capabilities", and its output is what every later step consumes.**

Read from the governed corpus under the run's pin — `ai-capability-map` (74 rows, declared `whole`
retrieval: a small complete register is read entirely, never as "the relevant rows") plus
`capability-domains` for its top level. **Nothing about the map is in code or in a prompt**: a new
version is a publish, and which version a run matched against is on its record.

`lab.core.usecase.capabilities.concepts()` is the one mapper from the corpus's columns to the shape
every matcher reads. **The concept id is the map's natural key**, `"Domain · Capability"` — the same
string `guardrails.cap` and `ai-capability-map.components` join on. That is the whole reason this map
can be matched against at all: a match reaches its obligations and its components with no further
resolution, where a business-map match reached nothing this framework catalogues.

Measured: 83 concepts (9 domains, 74 capabilities), 74 candidates at the grain, **22,744 bytes —
~5,700 tokens, the whole map in one prompt**, so `leaves` is chosen and no retrieval is needed. 24 of
the 74 are a guardrail enforcement point; 69 reach a component.

**A seam that had made the grain parameter worthless.** `coverage.leaves` took `deepest`, but
`resolve` and `match` — the only route a RUN takes to it — did not forward it, so every live run
matched at the constant 3 however shallow its map. Against a two-level map that is zero candidates,
which downstream is indistinguishable from "nothing is relevant". The harness never saw it because it
calls the matcher directly. `deepest` now threads through `match` → `resolve` → every matcher, and
`capabilities.LEVEL` (2) is declared rather than inferred from the deepest level present: CAFÉ's M4 is
domain → capability → **product**, so inferring would silently move the match onto products the day a
tenant published them as rows.

## Addendum — Part 5, both layers at their proper places

A matched capability is staged at the layer its MAP belongs to, and the direction reverses with it:

| | element | relation |
|---|---|---|
| technology capability | `ApplicationService` | **Serving** → the BusinessFunction that needed it |
| business capability | Strategy-layer `Capability` | ← **Realization** from the BusinessFunction |

Both readings are wrong in the other's place: a business function does not realize Microsoft Foundry,
and the enterprise does not possess "Agentic retrieval". Which map a match came from is told by the
id itself (`capabilities.is_key`) — natural key versus synthetic content id — because no other field
distinguishes them. The business branch is dormant, not deleted, so reinstating it is a setting.

The chain closes: `component —Realization→ service —Serving→ business function`, joined on the map's
key, because step 5 and step 21 now name capabilities identically. Where that service exists, no
`ApplicationFunction` is made for the same capability — one box holding the label and another the raw
key is the same thing drawn twice.
