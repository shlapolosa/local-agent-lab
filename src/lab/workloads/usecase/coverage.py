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

import json
from typing import Any, Callable, Mapping

from lab.platform import config
from lab.workloads.usecase import derivation
from lab.workloads.usecase.gates import GateFailed
from lab.workloads.usecase.steps import CAPABILITY_QUERY, step_for

__all__ = ["MATCHERS", "SAMPLES", "STORE_BACKED", "VECTOR_HITS", "candidates_from_hits", "composed",
           "leaves_for", "majority", "match", "matched_ids", "matched_labels", "named",
           "queries_for", "resolve", "vote"]

#: How many times step 5 is asked before its answers vote. ONE is the behaviour that was there
#: before this existed, and is the default so that turning sampling on is a deliberate act with a
#: measured threshold behind it rather than a cost every deployment pays by surprise.
SAMPLES = config.COVERAGE_SAMPLES

#: How many hits one behavioural element's relevance query brings back. Twelve, so the union over a
#: dozen elements is a few dozen candidates — enough to disagree with, not enough to be a corpus.
VECTOR_HITS = 30      # per element; 12 was measured too narrow (eval, 10 Sep 2026)

#: How many branches one level may open into the next (drill only). A coverage map that matched
#: thirty branches is not a coverage map, and following them all would rebuild the whole corpus one
#: subtree at a time.
MAX_BRANCHES = 8

#: The deepest level either strategy goes to. The published map has L4 concepts, so this is a
#: deliberate stop rather than the bottom of the tree.
DEEPEST_LEVEL = 3


def matched_labels(coverage: Mapping[str, Any], corpus=None) -> list[str]:
    """The capability branches a coverage map matched, in order, de-duplicated.

    `capability_label` is OPTIONAL in the schema and `capability_id` is required, because an id is
    what a lookup can check and a label is what a model can approximate. So the label is resolved
    from the CORPUS by that id where the match did not carry one: the mapping is already in hand,
    and asking the agent to repeat a label it read is asking it to typo a subtree fetch."""
    by_id = {str(c.get("id")): str(c.get("label") or "") for c in (corpus or [])
             if isinstance(c, dict)}
    seen: list[str] = []
    for match_ in (coverage or {}).get("matched") or []:
        label = str(match_.get("capability_label")
                    or by_id.get(str(match_.get("capability_id")), "")).strip()
        if label and label not in seen:
            seen.append(label)
    return seen[:MAX_BRANCHES]


def matched_ids(coverage: Mapping[str, Any]) -> list[str]:
    """The capability IDS a coverage map matched — what a child lookup is keyed on."""
    seen: list[str] = []
    for match_ in (coverage or {}).get("matched") or []:
        ident = str(match_.get("capability_id") or "").strip()
        if ident and ident not in seen:
            seen.append(ident)
    return seen[:MAX_BRANCHES]


def composed(trail: list[dict]) -> dict:
    """One coverage map out of the levels a drill walked — one row per FUNCTION.

    Concatenating the levels was wrong and it showed: 14 functions produced 40 rows and one
    capability appeared eleven times. A deeper level REFINES the shallower one for the same
    function, so treating refinement as addition turns a coverage map into a transcript of
    everything the drill considered.

    The DEEPEST level per function, not the last: a function may resolve at L1 and find nothing
    relevant below it, and it must keep that match — `feasibility_evidence` reads this field to
    decide `capability_matched`, whose false is step 16's reject rule.
    """
    first = trail[0]
    deepest: dict[str, dict] = {}
    path: dict[str, list[str]] = {}
    for entry in trail:
        for match_ in entry.get("matched") or []:
            function = str(match_.get("function", ""))
            label = str(match_.get("capability_label") or "")
            if label and label not in path.setdefault(function, []):
                path[function].append(label)
            if entry["level"] >= deepest.get(function, {}).get("level", 0):
                deepest[function] = dict(match_, level=entry["level"])
    return {**{k: v for k, v in first.items() if k not in ("level", "candidates", "matched")},
            "matched": [dict(m, path=path.get(f, [])) for f, m in deepest.items()]}


def leaves_for(corpus: list[dict], deepest: int = DEEPEST_LEVEL, budget: int = 0) -> list[dict]:
    """Every concept at the deepest level, each carrying the path that disambiguates it.

    The path is not decoration. A leaf label is frequently meaningless alone — "Initiative
    Identification" could belong to half a dozen branches — and a match made on the label alone is
    a match made on a coincidence of words."""
    concepts = [c for c in corpus if isinstance(c, dict)]
    by_id = {c["id"]: c for c in concepts if c.get("id")}

    def path_of(concept):
        # A corpus row carries its path already (the workbook publisher writes it); a concept list
        # from the semantic layer does not, and it is rebuilt from the parents present.
        if concept.get("path"):
            return str(concept["path"])
        out, cur = [], concept
        while cur:
            out.append(str(cur.get("label", "")))
            cur = by_id.get(cur.get("parent"))
        return " > ".join(reversed(out))

    # Only DICTS: a corpus that is not a concept list contributes no leaves rather than raising.
    # `semantic_concepts` is not the only thing that can end up under this key — a deployment
    # missing the scheme, or a different corpus wired by mistake, must degrade to "no candidates"
    # and let the step defer, which is what every other absent corpus here does.
    leaves = [{"id": c["id"], "label": c["label"], "path": path_of(c),
               **({"definition": str(c["definition"])} if c.get("definition") else {})}
              for c in concepts
              if c.get("level") == deepest and c.get("id") and c.get("label")]
    return _within(leaves, budget) if budget else leaves


#: A definition shorter than this discriminates nothing — "Ability to define, identify, quantify"
#: fits in eighty characters and says nothing a label does not. Below it, the leaves go without.
DEFINITION_MIN = 140


def _within(leaves: list[dict], budget: int) -> list[dict]:
    """Every leaf, with as much of its definition as the prompt budget allows.

    A thousand leaves cannot carry three hundred characters each — that is 300 KB against a 200 KB
    budget, and `resolve` would silently fall back to the drill. So the definitions are trimmed to
    what fits, and dropped entirely when what fits is too little to mean anything. The alternative,
    sending labels alone, is what made every match an assumption.
    """
    bare = [{k: v for k, v in leaf.items() if k != "definition"} for leaf in leaves]
    spare = budget - len(json.dumps(bare, ensure_ascii=False))
    if spare <= 0 or not leaves:
        return bare
    room = spare // max(len(leaves), 1) - len('"definition":"",')
    if room < DEFINITION_MIN:
        return bare
    return [{**leaf, "definition": leaf["definition"][:room].rstrip() + "…"}
            if leaf.get("definition") and len(leaf["definition"]) > room else leaf
            for leaf in leaves]


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


#: The list fields of a coverage map, voted on exactly the same terms as the matches. A function
#: one run of three called uncovered is not a gap — it is the same disagreement from the other side.
_VOTED_LISTS = ("functions_without_capability", "capabilities_without_function")

#: What identifies a MATCH for the purpose of agreeing on it. The pair, never the capability alone:
#: the same capability serving two functions is two separate claims, and pooling them would let a
#: well-agreed function carry a second claim nothing agreed on.
def _pair(match: Mapping[str, Any]) -> tuple[str, str]:
    return str(match.get("function") or ""), str(match.get("capability_id") or "")


def named(matched: list[Mapping[str, Any]], candidates: list[dict]) -> list[dict]:
    """Give every match the LABEL of the candidate its id was copied from.

    `capability_label` is optional in the coverage_map schema — only `function`, `capability_id`
    and `confidence` are required — and the model routinely omits it, which left the record, the
    approval and the live page holding `tec-cap-0031` where a capability's name belongs.

    It is a join, not a guess: the id was copied character for character from a candidate this step
    was SHOWN, and that candidate carries the label. So nothing is asked of a model and nothing is
    rendered around. Two things it deliberately will not do — overwrite a label the model did
    supply (it saw the same candidate; different words are its answer, not an error to correct
    silently), and invent one for an id no candidate carries, because an unjoinable id must keep
    looking unjoinable.
    """
    labels = {str(c.get("id")): str(c.get("label") or "") for c in candidates or []
              if isinstance(c, dict) and c.get("id")}
    out = []
    for match in matched:
        row = dict(match)
        if not row.get("capability_label"):
            label = labels.get(str(row.get("capability_id") or ""))
            if label:
                row["capability_label"] = label
        out.append(row)
    return out


def majority(n: int) -> int:
    """More than half of n. The default threshold, and the only one that means "most runs said so"
    for every n rather than for the n it was tuned on."""
    return n // 2 + 1


def vote(samples: list[Mapping[str, Any]], *, threshold: int) -> tuple[dict, list[dict]]:
    """Several independent answers to the same question -> the answer they agree on, and what they
    did not agree on.

    Returns `(agreed, excluded)`. Every kept match carries `votes` and `of`, so a reader can see
    that thirteen capabilities were unanimous and one scraped in two-of-three; every EXCLUDED match
    carries the same, because a capability some runs chose is a disagreement and not a wrong
    answer, and the approver is who is entitled to settle it. Dropping them silently is what made
    the spread invisible in the first place.

    Order is the FIRST sample's, so the vote does not trade one kind of jitter for another. The
    kept match is the first sample's own object, so `capability_label`, `confidence` and anything
    else a real answer carried survive rather than being re-synthesised here.
    """
    if not samples:
        return {}, []
    tally: dict[tuple[str, str], int] = {}
    first: dict[tuple[str, str], dict] = {}
    for s in samples:
        for match in (s or {}).get("matched") or []:
            if not isinstance(match, Mapping):
                continue
            key = _pair(match)
            tally[key] = tally.get(key, 0) + 1
            first.setdefault(key, dict(match))
    n = len(samples)
    agreed, excluded = [], []
    for key, seen in ((k, tally[k]) for k in first):        # first-sample order
        row = first[key] | {"votes": seen, "of": n}
        (agreed if seen >= threshold else excluded).append(row)
    out: dict = dict(samples[0]) | {"matched": agreed}
    for field_name in _VOTED_LISTS:
        counted: dict[str, int] = {}
        for s in samples:
            for value in (s or {}).get(field_name) or []:
                counted[str(value)] = counted.get(str(value), 0) + 1
        out[field_name] = [v for v, seen in counted.items() if seen >= threshold]
    return out, excluded


async def _one_pass(cfg, d, candidates: list[dict], *, label: str,
                    deepest: int = DEEPEST_LEVEL, samples: int | None = None,
                    threshold: int | None = None, _stamp=derivation.stamp_shape) -> dict:
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


def queries_for(elements: Mapping[str, Any] | None) -> list[str]:
    """One relevance query per BEHAVIOURAL element — the functions the use case performs are what a
    capability map classifies; its actors and its data are not."""
    out: list[str] = []
    names: set[str] = set()
    for element in (elements or {}).get("behavioural") or []:
        if not isinstance(element, dict):
            continue
        parts = [str(element.get(k) or "").strip() for k in ("name", "verb", "object")]
        if not parts[0] or parts[0].lower() in names:       # one query per element, by NAME
            continue
        names.add(parts[0].lower())
        out.append(" — ".join(p for p in (parts[0], " ".join(x for x in parts[1:] if x)) if p))
    return out


def candidates_from_hits(hits) -> list[dict]:
    """Relevance hits as the candidate rows step 5 reads: `{id, label, path}`, de-duplicated,
    first-seen order. A hit over the map is RECORD-backed — its `key` carries the id — and the
    façade names the `path` and `label` its passage opens with, so nothing here knows how the
    index was written."""
    out: list[dict] = []
    seen: set[str] = set()
    for hit in hits or []:
        attrs = (hit or {}).get("attributes") or {}
        try:
            key = json.loads(attrs.get("key") or "{}")
        except ValueError:
            key = {}
        ident = str(key.get("id") or attrs.get("record_id") or "").strip()
        path = str(attrs.get("path") or "").strip()
        if not ident or ident in seen or not path:
            continue
        seen.add(ident)
        out.append({"id": ident, "label": str(attrs.get("label") or path.rsplit(" > ", 1)[-1]),
                    "path": path})
    return out


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


def with_siblings(candidates: list[dict], corpus, deepest: int = DEEPEST_LEVEL) -> list[dict]:
    """The candidates plus every leaf that shares a parent with one of them, hits first.

    A relevance hit says "this branch", and the eval showed the misses were the leaves NEXT TO a
    hit, not strangers. The adjudicating pass decides which leaves of a branch apply, so it is
    shown the branch. Nothing here reaches the store: the siblings come from the map already in
    hand, so a wider candidate set costs no extra query."""
    rows = [r for r in (corpus or []) if isinstance(r, dict)]
    parent_of = {str(r.get("id")): str(r.get("parent") or "") for r in rows}
    wanted = {parent_of.get(c["id"], "") for c in candidates} - {""}
    out, seen = list(candidates), {c["id"] for c in candidates}
    for r in rows:
        ident = str(r.get("id") or "")
        if ident in seen or str(r.get("parent") or "") not in wanted:
            continue
        if int(r.get("level") or 0) != deepest:
            continue
        seen.add(ident)
        out.append({"id": ident, "label": str(r.get("label") or ""), "path": str(r.get("path") or "")})
    return out


#: The strategies, by name. Adding one is a line here and nothing else — which is what lets a
#: harness run them all over the same inputs and a deployment choose on evidence.
#: How many capabilities are shown as the map's REGISTER — enough to write like it, far too few to
#: choose from. Spread across the tree rather than taken from one branch, so the sample teaches the
#: style and not a subject.
REGISTER_SAMPLE = 24


def register_of(corpus, n: int = REGISTER_SAMPLE) -> list[dict]:
    """A sample of the map, as the translator is shown it: label and definition, nothing to match on.

    The translator writes the ability a function exercises in the map's own language. It cannot do
    that without seeing the language, and it must not be handed the map itself — the whole point of
    translating first is that choosing comes afterwards, against the real thing, with search having
    narrowed it.
    """
    rows = [c for c in (corpus or []) if isinstance(c, dict) and c.get("label")]
    if not rows:
        return []
    stride = max(1, len(rows) // n)
    return [{"label": str(r["label"]), "definition": str(r.get("definition") or "")[:200]}
            for r in rows[::stride][:n]]


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


#: What a widened parent row carries into the prompt — the same keys a candidate has, and no more.
_PARENT_KEYS = ("id", "label", "path", "level", "parent", "definition")


def with_parents(candidates: list[dict], corpus) -> list[dict]:
    """The candidates plus the branch each sits under — because an answer is not always a leaf.

    The parent is resolved from the CORPUS by the candidate's id, NOT read off the candidate. That
    distinction was the defect: this read `candidate["parent"]`, and the two callers hand it
    `candidates_from_hits` -> `with_siblings` output, which is `{id, label, path}` and carries no
    parent — so it widened nothing on every run since it was written, while its test supplied a
    `parent` key by hand and agreed with it. The corpus is where a concept's branch is actually
    known, and a candidate the corpus does not contain simply has no branch to add.

    Nothing here reaches the store; the parents come from the map already in hand."""
    rows = {str(r.get("id")): r for r in (corpus or []) if isinstance(r, dict) and r.get("id")}
    seen = {str(c.get("id")) for c in candidates}
    out = list(candidates)
    for c in candidates:
        row = rows.get(str(c.get("id") or ""))
        parent = rows.get(str((row or c).get("parent") or ""))
        if parent and str(parent["id"]) not in seen:
            seen.add(str(parent["id"]))
            out.append({k: v for k, v in parent.items() if k in _PARENT_KEYS})
    return out


#: The matchers that reach a relevance STORE rather than reading the corpus rows themselves.
#: Beside the registry, because "does this matcher need a store" is a fact about the MATCHER — it
#: was held in the screening workflow and duplicated in the eval harness, which is two places to
#: forget when a fifth matcher lands.
STORE_BACKED = ("vector", "translate")

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
    if matcher is leaves:
        # Measure what would ACTUALLY be sent: `leaves_for` trims the definitions to the budget, so
        # this only exceeds it when the bare labels alone do — which is the case the drill exists for.
        size = len(json.dumps(leaves_for(corpus, deepest=deepest, budget=budget),
                              ensure_ascii=False, default=str))
        if size > budget:
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
