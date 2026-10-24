"""Step 5's PURE half — matching rows, voting on samples, widening candidates. No agent, no I/O.

The strategies that DRIVE an agent over these (`drill`, `leaves`, `vector`, `translate`) and the
registry that picks one are orchestration and live in `lab.workloads.usecase.coverage`. What is here
decides nothing a model decides: it shapes what a model is shown and combines what it answered, and
every function is a deterministic function of its arguments.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

__all__ = ["DEEPEST_LEVEL", "MAX_BRANCHES", "REGISTER_SAMPLE", "candidates_from_hits", "composed",
           "leaves_fit", "leaves_for", "majority", "matched_ids", "matched_labels", "named",
           "queries_for", "register_of", "vote", "with_parents", "with_siblings"]


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
    # A function whose matches ALL lost the vote is an UNCOVERED function, not an absence. Three
    # samples matching it to three different capabilities give three pairs at one vote each, all
    # excluded — and no sample ever called it uncovered, so it appeared in neither list: not a
    # match, not a gap, the coverage check silently not done for it. Downstream that reads as
    # `capability_matched: False` rather than None, and step 16 rejects a use case nobody assessed.
    kept = {str(row.get("function") or "") for row in agreed}
    lost = [f for f in dict.fromkeys(str(row.get("function") or "") for row in excluded)
            if f and f not in kept]
    for field_name in _VOTED_LISTS:
        counted: dict[str, int] = {}
        for s in samples:
            for value in (s or {}).get(field_name) or []:
                counted[str(value)] = counted.get(str(value), 0) + 1
        out[field_name] = [v for v, seen in counted.items() if seen >= threshold]
    out["functions_without_capability"] = list(
        dict.fromkeys(list(out.get("functions_without_capability") or []) + lost))
    return out, excluded


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


def leaves_fit(corpus, budget: int, deepest: int = DEEPEST_LEVEL) -> bool:
    """Whether the leaf pass's prompt fits the budget. Measures what would ACTUALLY be sent:
    `leaves_for` trims the definitions to the budget, so this fails only when the bare labels alone
    exceed it — which is the case the drill exists for."""
    return len(json.dumps(leaves_for(corpus, deepest=deepest, budget=budget),
                          ensure_ascii=False, default=str)) <= budget
