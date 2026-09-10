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
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from lab.platform.contracts import SemanticTools
from lab.workloads import gateway
from lab.workloads.usecase.gates import GateFailed
from lab.workloads.usecase.steps import step_for

__all__ = ["MATCHERS", "composed", "leaves_for", "match", "matched_labels", "resolve"]

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


def leaves_for(corpus: list[dict], deepest: int = DEEPEST_LEVEL) -> list[dict]:
    """Every concept at the deepest level, each carrying the path that disambiguates it.

    The path is not decoration. A leaf label is frequently meaningless alone — "Initiative
    Identification" could belong to half a dozen branches — and a match made on the label alone is
    a match made on a coincidence of words."""
    concepts = [c for c in corpus if isinstance(c, dict)]
    by_id = {c["id"]: c for c in concepts if c.get("id")}

    def path_of(concept):
        out, cur = [], concept
        while cur:
            out.append(str(cur.get("label", "")))
            cur = by_id.get(cur.get("parent"))
        return " > ".join(reversed(out))

    # Only DICTS: a corpus that is not a concept list contributes no leaves rather than raising.
    # `semantic_concepts` is not the only thing that can end up under this key — a deployment
    # missing the scheme, or a different corpus wired by mistake, must degrade to "no candidates"
    # and let the step defer, which is what every other absent corpus here does.
    return [{"id": c["id"], "label": c["label"], "path": path_of(c)}
            for c in concepts
            if c.get("level") == deepest and c.get("id") and c.get("label")]


async def _children_of(cfg, scheme: str, labels, level: int, project) -> list[dict]:
    """The concepts one level BELOW each of these, and nothing else.

    `semantic_concepts(root_label=X, depth=1)` returns X and its children, so the parent is filtered
    out by level — a candidate set containing the thing already matched invites the next pass to
    match it again and call that progress."""
    out: list[dict] = []
    for label in labels:
        try:
            got = await gateway.call(cfg, SemanticTools.concepts,
                                     {"scheme": scheme, "root_label": label, "depth": 1})
        except Exception:                                # noqa: BLE001 — a branch is best effort
            continue
        out += [c for c in project(got) or [] if c.get("level") == level]
    return out


async def drill(cfg, d, corpus, *, scheme: str, project) -> dict:
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
    for level in range(1, DEEPEST_LEVEL + 1):
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
        trail.append({"level": level, "candidates": len(candidates), **found})
        labels = matched_labels(found, candidates)
        if not labels or level == DEEPEST_LEVEL:
            break
        candidates = await _children_of(cfg, scheme, labels, level + 1, project)

    if not trail:
        return {}
    # NO step number: `record(..., "5")` would clear the pending marker the gate-failure branch may
    # have just written, erasing the only statement that the drill stopped early.
    d.record("coverage_map", composed(trail))
    return {"capability_depth": trail[-1]["level"], "coverage_trail": trail}


async def leaves(cfg, d, corpus, *, scheme: str, project) -> dict:
    """One pass over every leaf, each carrying its path.

    No branch is ever closed, which is the whole difference: the drill's L1 decision is the
    highest-stakes one it makes and it makes it with the least information — 42 bare labels, no
    idea what lives underneath. "Is Work Management relevant?" is nearly unanswerable; "is
    Submission Validation relevant?" is obvious. The meaning is in the leaf.
    """
    step = step_for("5")
    candidates = leaves_for(corpus)
    if not candidates:
        return {}
    try:
        if not await d.run_step(cfg, step, label=f"match capabilities ({len(candidates)} leaves)",
                                context={"capabilities": candidates}):
            return {}
    except GateFailed as refused:
        d.defer("5", f"match capabilities: {refused}")
        return {}
    found = dict(d.derived.get("coverage_map") or {})
    return {"capability_depth": DEEPEST_LEVEL,
            "coverage_trail": [{"level": DEEPEST_LEVEL, "candidates": len(candidates), **found}]}


#: The strategies, by name. Adding one is a line here and nothing else — which is what lets a
#: harness run them all over the same inputs and a deployment choose on evidence.
MATCHERS: dict[str, Callable] = {"drill": drill, "leaves": leaves}


def resolve(name: str, corpus, budget: int) -> Callable:
    """The matcher a run should use: the one asked for, unless its prompt will not fit.

    `leaves` is the better matcher and the fallback is not a preference — it is arithmetic. Its
    candidate set grows with the map, and a corpus that does not fit in a prompt is not one it can
    answer over. The drill's does not grow, because no LEVEL of a tree is large.
    """
    matcher = MATCHERS.get(name)
    if matcher is None:
        raise KeyError(f"{name!r} is not a capability matcher; have {sorted(MATCHERS)}")
    if matcher is leaves:
        size = len(json.dumps(leaves_for(corpus), ensure_ascii=False, default=str))
        if size > budget:
            return drill
    return matcher


async def match(cfg, d, corpus, *, name: str, scheme: str, project, budget: int) -> dict:
    """Step 5, by whichever strategy this deployment runs."""
    return await resolve(name, corpus, budget)(cfg, d, corpus, scheme=scheme, project=project)
