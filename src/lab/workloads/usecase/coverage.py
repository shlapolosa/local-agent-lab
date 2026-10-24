"""How step 5 matches business functions to the capability map — the strategies, and the registry.

Two exist, they answer the same question differently, and which is better is an empirical question
rather than a matter of taste. So they live behind one seam, a deployment picks one by name, and an
evaluation harness can run both over the same inputs.

**`drill`** walks the map level by level: which L1 capabilities this use case touches, then which
L2 within those, then which L3. Each pass sees a small candidate set and what it selects decides
what the next pass is shown. Cheap in tokens (~2,200 for a 1,666-concept map) because no level is
large.

**`leaves`** asks once, over every L3 concept, each carrying the path that disambiguates it —
"Initiative Identification" means nothing until you know it sits under Initiative Management >
Initiative Definition. Expensive in tokens (~42,000 for the same map) and one call instead of three.

Measured on a clinical referral-triage use case against the BA Guild healthcare map, adjudicated
blind:

    drill      returned 23  applicable  4   precision 0.17  recall 0.36   362s over 3 calls
    leaves     returned  8  applicable  7   precision 0.88  recall 0.64   126s over 1 call

The drill's failure is structural rather than careless: having selected a branch at L1 it must
report it, so its answer is mostly the scaffolding it climbed — `assess urgency ->
Healthcare Case Management` is true of everything and actionable for nothing. `leaves` cannot make
that mistake because it never stands on a branch.

But `leaves` cannot be the only strategy: its prompt grows with the map, and a corpus that does not
fit is not a corpus it can answer over. The drill is what a map too large for one prompt gets, and
`MAX_CORPUS_BYTES` is where the choice is made — a measurement, not a preference.

Neither is comprehensive yet: on that same case both missed Partner Referral Management, Schedule
Management and the patient/medication branch entirely. That is why this is a registry with a
harness rather than a decision already taken.

**`vector`** is the third: one relevance query per behavioural element against the map's store
(through the gateway — registered, granted, metered, attributed to the derived field), the hits
unioned into a candidate set, and ONE pass of step 5 over that set exactly as `leaves` does. It
sends a few dozen candidates rather than a thousand, and a candidate arrives because it is near
the use case rather than because it exists. Whether that recovers what the other two miss is the
harness's question.

The map reaches every strategy the same way now: rows of the GOVERNED corpus under the run's pin
(`id, parent, level, label, path`), so a match cites a version. `children` and `search` are seams
the caller supplies — which corpus a run reads is the workload's decision; how it is matched is not.
"""
from __future__ import annotations

from typing import Callable

from lab.core.usecase.coverage import (DEEPEST_LEVEL, candidates_from_hits, composed, leaves_fit, leaves_for, majority, matched_ids, named, queries_for, register_of, vote, with_parents, with_siblings)
from lab.platform import config
from lab.workloads.usecase import derivation
from lab.core.validation import GateFailed
from lab.core.usecase.steps import CAPABILITY_QUERY, step_for

__all__ = ["MATCHERS", "SAMPLES", "STORE_BACKED", "VECTOR_HITS", "match", "resolve"]

#: How many times step 5 is asked before its answers vote. ONE is the behaviour that was there
#: before this existed, and is the default so that turning sampling on is a deliberate act with a
#: measured threshold behind it rather than a cost every deployment pays by surprise.
SAMPLES = config.COVERAGE_SAMPLES

#: How many hits one behavioural element's relevance query brings back. Twelve, so the union over a
#: dozen elements is a few dozen candidates — enough to disagree with, not enough to be a corpus.
VECTOR_HITS = 30      # per element; 12 was measured too narrow (eval, 10 Sep 2026)


async def _children_of(children, ids, level: int, project) -> list[dict]:
    """The concepts one level BELOW each of these, and nothing else.

    `children(ids, level)` is the caller's — a corpus read by parent under the run's pin — and a
    branch that cannot be fetched is skipped rather than failing the level: a candidate set
    containing the thing already matched invites the next pass to match it again and call that
    progress, so the parent is filtered out by level as well."""
    try:
        got = await children(list(ids), level)
    except Exception:                                    # noqa: BLE001 — a branch is best effort
        return []
    return [c for c in project(got) or [] if c.get("level") == level]


async def drill(cfg, d, corpus, *, children, project, deepest: int = DEEPEST_LEVEL,
                **_) -> dict:
    """Level by level: which L1 capabilities match, then which L2 within those, then L3.

    Walking the tree is deterministic — given the matches, the children to fetch next are not a
    matter of opinion. Deciding which of those children the use case touches is not, and could not
    be: it is a judgement about relevance, which is what an agent is for and what a gate should
    check rather than replace.

    Every level is kept. "Which L1s matched, then which L2s within those" is the reasoning a
    reviewer follows, and a final L3 list alone cannot be checked — a leaf under a branch nobody
    should have opened looks exactly like a leaf under one they should.
    """
    step = step_for("5")
    trail: list[dict] = []
    candidates = [c for c in corpus if isinstance(c, dict) and c.get("level") == 1]
    for level in range(1, deepest + 1):
        if not candidates:
            break
        try:
            if not await d.run_step(cfg, step, label=f"match capabilities (L{level})",
                                    context={"capabilities": candidates}):
                break
        except GateFailed as refused:
            # A deeper pass is MORE likely to fail its gate, and losing the run would throw away
            # every level that already passed plus every other step in a 700-second run.
            d.defer("5", f"match capabilities stopped at L{level}: {refused}")
            break
        found = dict(d.derived.get("coverage_map") or {})
        d.candidates = list(candidates)      # the level the drill actually chose from, last wins
        trail.append({"level": level, "candidates": len(candidates), **found})
        ids = matched_ids(found)
        if not ids or level == deepest:
            break
        candidates = await _children_of(children, ids, level + 1, project)

    if not trail:
        return {}
    # NO step number: `record(..., "5")` would clear the pending marker the gate-failure branch may
    # have just written, erasing the only statement that the drill stopped early.
    d.record("coverage_map", composed(trail))
    return {"capability_depth": trail[-1]["level"], "coverage_trail": trail}


def _gate_coverage(out: dict, candidates: list[dict]) -> list:
    """Step 5's completeness rule, run over an answer — the default `_gate` of `_one_pass`.

    Given the SAME context the rule sees on a single pass (`capabilities`), because it checks the
    matched ids against exactly the rows the step was shown.
    """
    return list(step_for("5").complete(out, {"capabilities": candidates}) or [])


async def _one_pass(cfg, d, candidates: list[dict], *, label: str,
                    deepest: int = DEEPEST_LEVEL, samples: int | None = None,
                    threshold: int | None = None, _stamp=derivation.stamp_shape,
                    _gate=None) -> dict:
    """Step 5 over a candidate set that already carries its paths — what `leaves`, `vector` and
    `translate` share. A gate failure defers the step by name rather than losing the run.

    Asked `samples` times, and what the samples AGREE on is the answer. `COVERAGE_SAMPLES=1` is
    exactly the single pass this used to be, so sampling has a real off switch rather than a
    differently-shaped answer. More than one because the alternatives were measured and do not
    work: at temperature 0 with a seed, on this step's real payload, both a reasoning and a
    non-reasoning model returned three distinct answers out of three (20 Sep 2026). The variance
    is in the question, not in the decoding.

    A sample that does not RUN — an unwired agent, a gate it could not satisfy — is not a vote
    against anything; the runs that answered still stand and the threshold is of those. Only when
    none answers does the step defer, exactly as the single pass did.
    """
    if not candidates:
        return {}
    d.candidates = list(candidates)          # the ceiling: what the chooser could possibly return
    n = SAMPLES if samples is None else samples
    answers: list[dict] = []
    for i in range(max(1, n)):
        try:
            if not await d.run_step(cfg, step_for("5"), context={"capabilities": candidates},
                                    label=label if n <= 1 else f"{label} — sample {i + 1}/{n}"):
                break                        # nothing more will run; vote on what did
        except GateFailed as refused:
            if not answers:
                d.defer("5", f"match capabilities: {refused}")
                return {}
            break                            # a sample that failed its gate is simply not a vote
        answers.append(dict(d.derived.get("coverage_map") or {}))
    if not answers:
        return {}
    wanted = config.COVERAGE_VOTES if threshold is None else threshold
    # A threshold above what actually answered would agree on nothing and read as a step that found
    # no capabilities — the one outcome worse than a wide match.
    agreed, excluded = vote(answers, threshold=(majority(len(answers)) if wanted <= 0
                                                else min(wanted, len(answers))))
    # The VOTE is the step's answer — the last sample is an arbitrary one of n, and recording it
    # would spend n times the tokens to keep exactly the variance this was bought to remove.
    agreed["matched"] = named(agreed.get("matched") or [], candidates)
    # The vote is a NEW answer, so it is gated like one. The rule ran per SAMPLE and never on what
    # was recorded, so the invariants it exists to enforce — a function is matched or named as a
    # gap; at least one `lookup` or a gap flag — did not hold of the object the run carried.
    problems = (_gate(agreed) if _gate else _gate_coverage(agreed, candidates))
    if problems:
        # Every SAMPLE recorded its own answer on the way through, so deferring without clearing
        # would leave the LAST sample's answer sitting in the record under a step the run says did
        # not complete — a defer that is not true is worse than no defer at all.
        for store in (getattr(d, "derived", None), getattr(d, "available", None)):
            if isinstance(store, dict):
                store.pop("coverage_map", None)
        d.defer("5", f"match capabilities: the agreed answer is incomplete — {problems[:3]}")
        return {}
    d.record("coverage_map", agreed, "5")
    # Each SAMPLE stamped `step_5` as it ran, so the board holds an arbitrary one of n. Re-stamp
    # with what was agreed, or a person watching the run reads a different answer from the record.
    _stamp(cfg, step_for("5"), agreed)
    return {"capability_depth": deepest,
            "coverage_trail": [{"level": deepest, "candidates": len(candidates),
                                "samples": len(answers), "excluded": excluded, **agreed}]}


async def leaves(cfg, d, corpus, *, budget: int = 0, deepest: int = DEEPEST_LEVEL,
                 samples: int | None = None, threshold: int | None = None, **_) -> dict:
    """One pass over every leaf, each carrying its path.

    No branch is ever closed, which is the whole difference: the drill's L1 decision is the
    highest-stakes one it makes and it makes it with the least information — 42 bare labels, no
    idea what lives underneath. "Is Work Management relevant?" is nearly unanswerable; "is
    Submission Validation relevant?" is obvious. The meaning is in the leaf.
    """
    candidates = leaves_for(corpus, deepest=deepest, budget=budget)
    carries = sum(1 for c in candidates if c.get("definition"))
    return await _one_pass(cfg, d, candidates, deepest=deepest, samples=samples,
                           threshold=threshold,
                           label=f"match capabilities ({len(candidates)} leaves, "
                                 f"{carries} with a definition)")


async def vector(cfg, d, corpus, *, search, deepest: int = DEEPEST_LEVEL,
                 samples: int | None = None, threshold: int | None = None, **_) -> dict:
    """One relevance query per behavioural element, the hits unioned, one pass of step 5 over the
    union. `search(query, k)` is the caller's — the map's store through the gateway, under the
    run's pin, attributed to this field."""
    queries = queries_for(d.available.get("elements"))
    if not queries:
        d.defer("5", "match capabilities — needs the behavioural elements from step 4")
        return {}
    hits: list = []
    for query in queries:
        try:
            hits += await search(query, VECTOR_HITS)
        except Exception as exc:                          # noqa: BLE001 — one query, not the run
            d.defer("5", f"match capabilities: the relevance search refused — {exc}")
            return {}
    candidates = with_parents(with_siblings(candidates_from_hits(hits), corpus, deepest), corpus)
    return await _one_pass(cfg, d, candidates, samples=samples, threshold=threshold,
                           label=f"match capabilities ({len(candidates)} candidates from "
                                 f"{len(queries)} queries)")


async def translate(cfg, d, corpus, *, search, deepest: int = DEEPEST_LEVEL,
                    samples: int | None = None, threshold: int | None = None, **_) -> dict:
    """Translate, then search, then choose — the three stages the other matchers collapse.

    Measured 17 Sep 2026: the functions a submission names ("assess urgency", "reconcile the
    medication list") and the abilities a capability map names ("Healthcare Case Risk Level
    Determination") share almost no words, so a search made with the function's own wording
    retrieves generic information-handling capabilities and the medication branch sits untouched.
    The other matchers have no stage that could close that gap: `leaves` shows the model everything
    and hopes, `drill` narrows by a label it cannot read, `vector` searches with the words that do
    not match.

    So: one agent call translates every function into the map's register, the translations are what
    is searched, and the hits plus their siblings and PARENTS go to the choosing pass. Parents
    because a capability map answers at more than one level — measured the same day, the referral
    case's own expected set is level 2 and level 3, and a matcher offering only leaves could not
    have returned a third of the right answers however well it searched.
    """
    elements = d.available.get("elements")
    if not (elements or {}).get("behavioural"):
        d.defer("5", "match capabilities — needs the behavioural elements from step 4")
        return {}
    d.available["register"] = register_of(corpus)
    if not await d.run_step(cfg, CAPABILITY_QUERY, label="translate the functions"):
        d.defer("5", "match capabilities — the translation step is not wired")
        return {}
    queries = [f'{q.get("ability", "")} — {q.get("about", "")}'.strip(" —")
               for q in (d.derived.get("capability_query") or {}).get("queries") or []]
    hits: list = []
    for query in [q for q in queries if q]:
        try:
            hits += await search(query, VECTOR_HITS)
        except Exception as exc:                          # noqa: BLE001 — one query, not the run
            d.defer("5", f"match capabilities: the relevance search refused — {exc}")
            return {}
    candidates = with_parents(with_siblings(candidates_from_hits(hits), corpus, deepest), corpus)
    return await _one_pass(cfg, d, candidates, samples=samples, threshold=threshold,
                           label=f"match capabilities ({len(candidates)} candidates from "
                                 f"{len(queries)} translated abilities)")


#: The matchers that reach a relevance STORE rather than reading the corpus rows themselves.
#: Beside the registry, because "does this matcher need a store" is a fact about the MATCHER — it
#: was held in the screening workflow and duplicated in the eval harness, which is two places to
#: forget when a fifth matcher lands.
STORE_BACKED = ("vector", "translate")

#: The strategies, by name. Adding one is a line here and nothing else — which is what lets a
#: harness run them all over the same inputs and a deployment choose on evidence.
MATCHERS: dict[str, Callable] = {"drill": drill, "leaves": leaves, "vector": vector,
                                 "translate": translate}


def resolve(name: str, corpus, budget: int, deepest: int = DEEPEST_LEVEL) -> Callable:
    """The matcher a run should use: the one asked for, unless its prompt will not fit.

    `leaves` is the better matcher and the fallback is not a preference — it is arithmetic. Its
    candidate set grows with the map, and a corpus that does not fit in a prompt is not one it can
    answer over. The drill's does not grow, because no LEVEL of a tree is large.
    """
    matcher = MATCHERS.get(name)
    if matcher is None:
        raise KeyError(f"{name!r} is not a capability matcher; have {sorted(MATCHERS)}")
    if matcher is leaves and not leaves_fit(corpus, budget, deepest):
        return drill
    return matcher


async def match(cfg, d, corpus, *, name: str, children, search, project, budget: int,
                deepest: int = DEEPEST_LEVEL, samples: int | None = None,
                threshold: int | None = None) -> dict:
    """Step 5, by whichever strategy this deployment runs. Every strategy is handed every seam and
    takes what it needs — the registry stays one line per strategy.

    `deepest` is the MAP's matching grain and must reach the matcher: it was a parameter of `leaves`
    that neither this function nor `resolve` forwarded, so every live run matched at the constant 3
    however shallow its map. Against a two-level map that is no candidates at all, and no candidates
    is indistinguishable downstream from "nothing is relevant".

    `samples` and `threshold` override `COVERAGE_SAMPLES`/`COVERAGE_VOTES` for one call, which is
    how the eval harness tunes k on the frozen cases. `drill` takes them and ignores them — it runs
    step 5 once per LEVEL rather than through `_one_pass`, so there is no single pass to sample.
    """
    return await resolve(name, corpus, budget, deepest)(
        cfg, d, corpus, children=children, search=search, project=project, budget=budget,
        deepest=deepest, samples=samples, threshold=threshold)
