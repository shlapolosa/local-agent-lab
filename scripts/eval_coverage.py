"""Which capability matcher is more accurate — measured, repeatably.

G10 requires every production agent to have "an evaluation harness gating deploys"; G18 requires a
step above the lowest influence class to carry "a harness with a stated recall target on the branch
it can suppress". The capability matcher suppresses branches — that is its mechanism — so this is
the harness those guardrails name, applied to the agent that derives them.

    python scripts/eval_coverage.py --cases var/eval/coverage --runs 3
    python scripts/eval_coverage.py --cases var/eval/coverage --matcher leaves --runs 1

A CASE is a directory holding:

    submission.md   the prose a person would submit
    elements.json   the element inventory (step 4's output), FIXED — so the matcher is the only
                    variable. Derived once with `--derive` and then committed to the case.
    expected.json   {"applicable": ["Capability A", ...], "notes": "..."} — the capabilities a
                    human says this use case genuinely exercises.

**`expected.json` is the whole point, the only part that cannot be automated, and it is FROZEN.**
Precision and recall are meaningless against a denominator a model invented. They are equally
meaningless against one EDITED after reading a result: adding what the matcher returned raises both
metrics arithmetically, and on 18 Sep 2026 exactly that happened here — a widening moved recall
+0.05 and precision +0.24 while measuring nothing at all. The rule, stated so it is not rediscovered:
**a set is never reconciled against the output it exists to judge.** One that is wrong is re-derived
BLIND, from `submission.md` alone with no results open, or by an architect.

**Cases live IN the repository** (`docs/evals/cases`, the `--cases` default). They used to sit under
git-ignored `var/` because the expected sets named a licensed reference model. They no longer do —
the business capability maps are retired and the technology map is the framework's own, already
committed as seed — so the bar is versioned, and a change to it shows up in a diff instead of
happening quietly on one machine.

Exempt from TDD as a script, but it decides what ships, so its scoring is deliberately dull
arithmetic over sets and every number it prints can be recomputed from the JSON it writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.platform import config
from lab.core.usecase import capabilities, seed                 # noqa: E402
from lab.workloads import gateway                              # noqa: E402
from lab.workloads.usecase import agents as A                  # noqa: E402
from lab.workloads.usecase import coverage, reference          # noqa: E402
from lab.workloads.usecase.derivation import Derivation        # noqa: E402
from lab.workloads.usecase.gates import GateFailed             # noqa: E402
from lab.workloads.usecase.steps import step_for               # noqa: E402


#: The recorded bar. NAMED rather than spelled at the flag, because it was spelled there and the
#: file was renamed out from under it: `--baseline` defaulted to `coverage-baseline.json` while the
#: file on disk was `technology-baseline.json`, so `base_path.exists()` was False and every run
#: compared against nothing, silently. A test asserts this path is a file that exists.
BASELINE = "docs/evals/technology-baseline.json"

#: The capabilities a human says this use case genuinely exercises. One map now, so one file.
EXPECTED = "expected.json"


def expected_for(case: Path) -> set:
    """Refuses by name rather than scoring against an absent file: recall against an empty expected
    set is 0.0 for every matcher, which reads as a total failure and is in fact a missing input."""
    path = case / EXPECTED
    if not path.is_file():
        raise SystemExit(f"{case.name}: no {EXPECTED} — a case with no expected set cannot be "
                         f"scored, and scoring it at zero would read as a matcher that found "
                         f"nothing")
    return set(json.loads(path.read_text())["applicable"])


def technology_map() -> list[dict]:
    """The TECHNOLOGY capability map, projected exactly as the screening run projects it.

    Same artifacts, same mapper (`capabilities.concepts`), same grain — so what the harness scores
    is what a run is shown. The rows come from the committed SEED rather than the corpus: the seed
    is the publish-time master, so scoring it measures the map that is ABOUT to be published, which
    is the version a baseline should gate on. A published corpus behind the seed would otherwise
    make an eval pass on content no run will ever see.
    """
    return capabilities.concepts(seed.artifact("ai_capability_map")["capabilities"],
                                 seed.artifact("capability_domains")["domains"])


def corpus_from_file(path: str) -> list[dict]:
    """A corpus read from a JSON file rather than the licensed scheme — how a DIFFERENT map is
    scored on the same cases. Same row shape the SKOS service emits (`id, label, level, parent,
    path, definition`), so every matcher and every seam below is unchanged. The `vector` matcher
    is the exception and says so: its candidates come from a published store, and a file has none."""
    rows = json.loads(Path(path).read_text())
    missing = [k for k in ("id", "label", "level") if any(k not in r for r in rows)]
    if missing:
        raise SystemExit(f"{path}: every row needs {missing} — this is a corpus, not a table")
    return rows


def agents_for(gateway_url: str, model: str, credential: str, *steps) -> dict:
    return {s.key: A.make_agent(s, credential=credential, gateway_url=gateway_url,
                                model=model, timeout=900.0) for s in steps}


async def derive_elements(cfg, submission: str) -> dict:
    """Step 4's inventory. Run ONCE per case and kept, so the matcher is the only variable — a
    matcher scored against a different element list each run is not being compared to anything."""
    d = Derivation(available={"submission": submission})
    if not await d.run_step(cfg, step_for("3"), label="frame"):
        raise RuntimeError("the frame step did not run — is its agent wired?")
    if not await d.run_step(cfg, step_for("4"), label="elements"):
        raise RuntimeError("the elements step did not run")
    return d.derived["elements"]


def identity_of(match: Mapping, corpus: list[dict]) -> str:
    """What a match IS, scored the way the rest of the framework joins on it.

    The technology map's id is its natural key, and that key is what a guardrail and the component
    catalogue resolve against — so scoring a LABEL would measure something no downstream consumer
    uses. But a reasoning model writes the label where the key belongs often enough to have been
    measured (12 Sep 2026), and refusing those would score the model's field discipline rather than
    its judgement. So: the id when the map knows it, otherwise the label resolved back to its id,
    otherwise the raw string — which then matches nothing and is a visible wrong answer.

    `bad_ids` still counts the ones that needed resolving, because a match a RUN could not join on
    is a defect even when the harness can charitably read it.
    """
    by_id = {str(c.get("id")) for c in corpus if isinstance(c, dict) and c.get("id")}
    by_label = {str(c.get("label", "")).strip(): str(c.get("id"))
                for c in corpus if isinstance(c, dict) and c.get("label")}
    ident = str(match.get("capability_id") or "").strip()
    if ident in by_id:
        return ident
    return by_label.get(str(match.get("capability_label") or "").strip(), ident)


async def _no_store(query, k):
    """The `search` seam, for a map that has none.

    The technology capability map is a register read whole — 74 rows in one prompt — so there is
    nothing to search. It RAISES rather than returning an empty list, because an empty relevance
    result is indistinguishable from a map that knows nothing about the query, and a store-backed
    matcher would then score zero for a reason that has nothing to do with matching.
    """
    raise RuntimeError("the technology capability map has no relevance store — it is read whole; "
                       "score `leaves` or `drill`")


def children_of(corpus: list[dict], seen: set | None = None):
    """The drill's `children` seam over the LOCAL tree — the same rows the corpus would serve.

    `seen` collects every label this seam ever handed the matcher: that is the `offered` set the
    stage metrics need, and a seam is the only honest place to take it. Counting the corpus
    instead would credit the drill with candidates it closed a branch on and never showed."""
    by_parent: dict = {}
    for c in corpus:
        by_parent.setdefault(c.get("parent"), []).append(c)

    async def children(ids, level):
        rows = [c for i in ids for c in by_parent.get(i, [])]
        if seen is not None:
            seen.update(str(r.get("id") or "").strip() for r in rows)
        return rows
    return children


def present(corpus: list[dict], definitions: str, budget: int, deepest: int) -> list[dict]:
    """The candidate rows AS THE MATCHER WILL SEE THEM — the experiment's real variable.

    Every downstream derivation rests on this match, and for months the only thing varied was which
    matcher ran, while the thing that decides whether a match is a lookup or a guess — whether the
    candidate carries its DEFINITION — was fixed by a constant nobody re-measured after the model
    changed. `none` is what production sent (labels and path), `full` is every definition whatever
    it costs, `fit` is as much as the byte budget allows.
    """
    if definitions == "full":
        return corpus
    if definitions == "none":
        return [{k: v for k, v in c.items() if k != "definition"} for c in corpus]
    trimmed = coverage.leaves_for(corpus, deepest=deepest, budget=budget)   # budget-aware trim
    keep = {t["id"]: t.get("definition") for t in trimmed}
    # Built explicitly, because the dict-merge this used to be did not do what it read as:
    # `{**c, **{k: v for k, v in c.items() if k != "definition"}}` spreads `c` INCLUDING its
    # definition and then merges a copy without that key, which removes nothing. So `fit` never
    # dropped a definition the budget could not afford — it only ever truncated one — and every
    # `--definitions fit` measurement was of a prompt larger than the flag claimed.
    out: list[dict] = []
    for concept in corpus:
        ident = concept.get("id")
        if ident not in keep:
            out.append(concept)
            continue
        row = {k: v for k, v in concept.items() if k != "definition"}
        if keep.get(ident):
            row["definition"] = keep[ident]
        out.append(row)
    return out


def payload_size(corpus: list[dict], matcher: str, budget: int, deepest: int) -> int:
    """Roughly what one prompt will carry — printed so a recall number is read beside its cost."""
    rows = coverage.leaves_for(corpus, deepest=deepest, budget=budget) if matcher == "leaves" \
        else [c for c in corpus if c.get("level") == 1]
    return len(json.dumps(rows, ensure_ascii=False, default=str))


async def one_run(cfg, corpus, elements, matcher: str,
                  deepest: int) -> tuple[set, float, str, list, set]:
    """One matcher over one case: the capabilities it returned, the seconds it took, why it
    stopped if it did, and WHAT IT WAS SHOWN.

    The last of those is what separates a retrieval failure from a choosing failure, and the two
    have opposite fixes. `leaves` shows the whole leaf set and is computed directly; every other
    matcher decides what to show as it goes, so its offered set is collected at the seams."""
    d = Derivation(available={"elements": elements, "capabilities": corpus})
    offered: set = set()
    if matcher == "leaves":
        offered = {str(c.get("id") or "").strip()
                   for c in coverage.leaves_for(corpus, deepest=deepest)}
    started = time.time()
    note = ""
    try:
        await coverage.MATCHERS[matcher](cfg, d, corpus,
                                         children=children_of(corpus, offered),
                                         search=_no_store, project=lambda r: r, deepest=deepest)
    except GateFailed as refused:
        note = f"gate: {refused}"
    except Exception as exc:                       # noqa: BLE001 — a failed run is a DATA POINT
        note = f"{type(exc).__name__}: {exc}"
    matched = (d.derived.get("coverage_map") or {}).get("matched") or []
    got = {identity_of(m, corpus) for m in matched}
    # What recall cannot see: an id that is not in the map. A reasoning model writes the label
    # where the key belongs (measured 12 Sep 2026); the label scores, the id would not join.
    ids = {str(c.get("id")) for c in corpus if isinstance(c, dict) and c.get("id")}
    bad_ids = sorted({str(m.get("capability_id")) for m in matched
                      if str(m.get("capability_id", "")).strip() not in ids})
    return ({g for g in got if g}, time.time() - started, note or d.pending.get("5", ""),
            bad_ids, {o for o in offered if o})


def score(got: set, expected: set, offered: set | None = None) -> dict:
    """The outcome, and WHERE it was lost.

    A pipeline scored only end to end cannot tell a retrieval problem from a chooser problem, and
    they have opposite fixes. So two more numbers, both standard for a retrieve-then-rerank stack:
    `reachable` is recall@k of the candidate set — the ceiling, since a chooser cannot return what
    it was never shown — and `chose` is what the chooser took OF what was reachable. A low
    `reachable` says fix retrieval (or the translation feeding it); a high `reachable` with a low
    `chose` says fix the choosing prompt.
    """
    tp = len(got & expected)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    out = {"returned": len(got), "correct": tp, "precision": precision, "recall": recall,
           "f1": f1, "wrong": sorted(got - expected), "missed": sorted(expected - got)}
    if offered is not None:
        present = expected & offered
        out |= {"candidates": len(offered),
                "reachable": len(present) / len(expected) if expected else 0.0,
                "chose": len(got & present) / len(present) if present else 0.0,
                "unreachable": sorted(expected - offered)}
    return out


def means(results: dict) -> dict:
    """Per matcher and case: the mean precision, recall and F1 — the only thing a baseline holds.
    No labels: the cases' expected sets derive from a licensed map and stay out of the repo."""
    out: dict = {}
    for matcher, cases in results.items():
        for case, samples in cases.items():
            ok = [s for s in samples if not s.get("note")]        # a failed run is not a score
            if ok:
                out.setdefault(matcher, {})[case] = {
                    k: round(statistics.fmean(s[k] for s in ok), 3)
                    for k in ("precision", "recall", "f1")} | {"n": len(ok)}
    return out


def regressions(current: dict, baseline: dict, tolerance: float = 0.05,
                results_cases: dict | None = None) -> list[str]:
    """What fell below the recorded baseline by more than `tolerance` recall — the sentence a
    change has to answer before it ships. A matcher/case the baseline never scored is not a
    regression; an improvement is reported by the caller, never here. `results_cases` (matcher -> {case: ...}) says which pairs this run
    ATTEMPTED: one attempted and never scored — every run failed — is a regression too,
    because "not scored" and "scored zero" must not both read as "no regression"
    (11 Sep 2026: a run of all-429s reported none)."""
    out = []
    for matcher, cases in sorted(baseline.items()):
        for case, base in sorted(cases.items()):
            now = (current.get(matcher) or {}).get(case)
            if now is None:
                if case in (results_cases or {}).get(matcher, {}):
                    out.append(f"{matcher}/{case}: no run scored (every run failed) — baseline "
                               f"recall {base['recall']:.2f}")
                continue
            drop = base["recall"] - now["recall"]
            if drop > tolerance:
                out.append(f"{matcher}/{case} recall {now['recall']:.2f} < baseline "
                           f"{base['recall']:.2f} (-{drop:.2f})")
    return out


def report(results: dict, runs: int) -> int:
    """What each matcher scored, and whether the difference survives the variance.

    Means over `runs` repeats, with the spread — a single sample is not evidence when the same
    step has been measured at 32 s and at 984 s. Returns non-zero when a matcher scored below the
    recall target G18 asks for, so this can gate a deploy rather than merely inform one.
    """
    target = float(os.environ.get("COVERAGE_RECALL_TARGET", "0.6"))
    print(f"\n{'matcher':10} {'case':22} {'prec':>6} {'recall':>7} {'F1':>6} "
          f"{'reach':>6} {'chose':>6} {'sec':>6}   n={runs}")
    failed = []
    for matcher, cases in sorted(results.items()):
        for case, samples in sorted(cases.items()):
            mean = lambda k: statistics.fmean(s[k] for s in samples)
            spread = (f" ±{statistics.stdev(s['recall'] for s in samples):.2f}"
                      if len(samples) > 1 else "")
            stage = (f"{mean('reachable'):6.2f} {mean('chose'):6.2f}"
                     if all("reachable" in s for s in samples) else f"{'—':>6} {'—':>6}")
            print(f"  {matcher:8} {case:22} {mean('precision'):6.2f} {mean('recall'):7.2f}"
                  f"{spread} {mean('f1'):6.2f} {stage} {mean('seconds'):6.0f}")
            if mean("recall") < target:
                failed.append(f"{matcher}/{case} recall {mean('recall'):.2f}")

    print("\nwhat the best-scoring matcher still MISSES (the comprehensiveness gap):")
    for matcher, cases in sorted(results.items()):
        for case, samples in sorted(cases.items()):
            missed = sorted(set.intersection(*(set(s["missed"]) for s in samples)))
            if missed:
                print(f"  {matcher}/{case}: {missed[:6]}{' …' if len(missed) > 6 else ''}")
    if failed:
        print(f"\nBELOW the {target:.2f} recall target: {failed}")
    return 1 if failed else 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="docs/evals/cases",
                    help="directory of case directories; the default is the versioned bar")
    ap.add_argument("--matcher", action="append", choices=sorted(coverage.MATCHERS),
                    help="repeatable; default is every matcher")
    ap.add_argument("--runs", type=int, default=3, help="repeats per matcher per case")
    ap.add_argument("--case", action="append",
                    help="repeatable; run only these case directories (the tight loop is one case)")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="cases in flight at once. 5 turns a four-minute arm into one, at the cost "
                         "of sharing the upstream's rate limit — keep it 1 beside a cloud run")
    ap.add_argument("--show", action="store_true",
                    help="print what a matcher WOULD send and stop — no model call, no cost. The "
                         "loop for tuning presentation: change a field, see the candidates")
    ap.add_argument("--deepest", type=int, default=0,
                    help="the map's matching GRAIN — the level candidates are drawn from. Default "
                         "is the published map's (3); with --corpus-file, the deepest level present")
    ap.add_argument("--corpus-file",
                    help="score against THIS capability map (JSON rows) instead of the "
                         "published technology map. The "
                         "`vector` matcher is unavailable: it reads a published store, not a file")
    ap.add_argument("--definitions", choices=("none", "fit", "full"), default="fit",
                    help="how a candidate is PRESENTED: labels only (what production sent until "
                         "17 Sep 2026), as much definition as the byte budget allows, or all of it")
    ap.add_argument("--budget", type=int, default=200_000,
                    help="the prompt byte budget `fit` trims to; the production constant is "
                         "MAX_CORPUS_BYTES and it was sized on a different upstream")
    ap.add_argument("--derive", action="store_true",
                    help="derive each case's elements.json and stop — run once per case")
    ap.add_argument("--model", default=config.USECASE_AGENT_MODEL,
                    help="the model the matcher's agents run on. The default is what production "
                         "runs; naming another is how a model change is MEASURED against the "
                         "frozen bar before it ships, rather than argued about")
    ap.add_argument("--out", default="var/eval/coverage-results.json")
    ap.add_argument("--baseline", default=BASELINE,
                    help="recorded means to refuse a regression against (recall, per matcher/case)")
    ap.add_argument("--record-baseline", action="store_true",
                    help="write this run's means AS the baseline (after a reviewed improvement)")
    args = ap.parse_args()

    gateway_url = os.environ.get("EVAL_GATEWAY") or os.environ.get("GATEWAY_URL",
                                                                   "http://127.0.0.1:4000")
    credential = os.environ.get("EVAL_AGENT_KEY") or ""
    if not credential:
        raise SystemExit("EVAL_AGENT_KEY is not set — evals run on their OWN identity, never on a "
                         "production agent's key (scripts/provision_usecase_agents.py mints it)")
    cfg = {"agents": agents_for(gateway_url, args.model, credential,
                                step_for("3"), step_for("4"), step_for("5"),
                                coverage.CAPABILITY_QUERY),   # the `translate` matcher's own stage
           # what the `vector` matcher needs to reach the store the way a run does
           "headers": gateway.auth_headers(credential), "gateway_url": gateway_url,
           "mcp_url": gateway_url.rstrip("/") + "/mcp/", "run_id": "eval", "process": "eval"}
    if args.corpus_file:
        corpus = corpus_from_file(args.corpus_file)
        # A file's grain is the file's, not the published map's: the constant is 3 and a two-level
        # map would yield zero candidates, which reads downstream as "nothing is relevant".
        args.deepest = args.deepest or max(int(c.get("level") or 0) for c in corpus)
    else:
        corpus = technology_map()
        args.deepest = args.deepest or capabilities.LEVEL
    # Neither source has a relevance store, so a store-backed matcher cannot be scored at all.
    # Refusing beats scoring it at zero, which would read as a matcher that finds nothing.
    asked = set(args.matcher or []) & set(coverage.STORE_BACKED)
    if asked:
        raise SystemExit(f"{sorted(asked)} search a published relevance store, and this map has "
                         f"none — it is a register read whole. Score `leaves` or `drill`.")
    args.matcher = args.matcher or [m for m in sorted(coverage.MATCHERS)
                                    if m not in coverage.STORE_BACKED]
    with_def = sum(1 for c in corpus if str(c.get("definition") or "").strip())
    corpus = present(corpus, args.definitions, args.budget, args.deepest)
    print(f"corpus: {len(corpus)} concepts ({with_def} carry a definition) | "
          f"definitions={args.definitions} | model: {args.model} | gateway: {gateway_url}")

    cases = sorted(p for p in Path(args.cases).glob("*")
                   if (p / "submission.md").exists() and (p / EXPECTED).is_file())
    if args.case:
        wanted = {c.strip() for c in args.case}
        cases = [c for c in cases if c.name in wanted]
        if not cases:
            print(f"no case named {sorted(wanted)} under {args.cases}")
            return 2
    if not cases:
        print(f"no cases under {args.cases} — a case is a directory with submission.md, "
              f"elements.json and expected.json")
        return 2

    if args.show:
        # Zero calls: what the matcher would be handed, and what it costs. Tuning the presentation
        # is the tightest loop there is, and paying a model to see a prompt is absurd.
        for matcher in (args.matcher or sorted(coverage.MATCHERS)):
            rows = (coverage.leaves_for(corpus, deepest=args.deepest, budget=args.budget)
                    if matcher == "leaves" else [c for c in corpus if c.get("level") == 1])
            size = len(json.dumps(rows, ensure_ascii=False, default=str))
            carry = sum(1 for r in rows if str(r.get("definition") or "").strip())
            print(f"\n{matcher}: {len(rows)} candidates, {size:,} bytes (~{size // 4:,} tokens), "
                  f"{carry} with a definition")
            for row in rows[:3]:
                print("   ", json.dumps(row, ensure_ascii=False)[:300])
        for case in cases:
            elements = json.loads((case / "elements.json").read_text())
            expected = sorted(expected_for(case))
            behavioural = [b.get("name") for b in elements.get("behavioural") or []]
            print(f"\n{case.name}: {len(behavioural)} functions to match, {len(expected)} expected")
            print(f"    functions: {behavioural[:6]}")
            print(f"    expected:  {expected[:6]}")
        return 0

    if args.derive:
        for case in cases:
            if (case / "elements.json").exists():          # a scored case keeps its elements
                print(f"  {case.name}: elements.json exists — kept (delete it to re-derive)")
                continue
            elements = await derive_elements(cfg, (case / "submission.md").read_text())
            (case / "elements.json").write_text(json.dumps(elements, indent=2))
            print(f"  {case.name}: {sum(len(v) for v in elements.values() if isinstance(v, list))}"
                  f" elements derived")
        return 0

    results: dict = {}
    gate = asyncio.Semaphore(max(1, args.concurrency))

    async def scored(matcher: str, case, run: int) -> tuple:
        expected = expected_for(case)
        elements = json.loads((case / "elements.json").read_text())
        async with gate:
            got, seconds, note, bad_ids, offered = await one_run(
                cfg, corpus, elements, matcher, args.deepest)
        row = score(got, expected, offered) | {"seconds": seconds, "note": note, "run": run,
                                               "invalid_ids": bad_ids}
        print(f"  {matcher:8} {case.name:22} run {run + 1}/{args.runs}  "
              f"P {row['precision']:.2f} R {row['recall']:.2f}  "
              f"[reachable {row.get('reachable', 0):.2f} of {row.get('candidates', 0)} shown, "
              f"chose {row.get('chose', 0):.2f}]  {seconds:4.0f}s"
              f"{'  bad-ids ' + str(len(bad_ids)) if bad_ids else ''}"
              f"{'  ' + note[:50] if note else ''}", flush=True)
        return matcher, case.name, row

    for matcher in (args.matcher or sorted(coverage.MATCHERS)):
        print(f"    candidates ≈ {payload_size(corpus, matcher, args.budget, args.deepest):,} bytes")
        todo = [scored(matcher, case, run) for case in cases for run in range(args.runs)]
        for matcher_, name, row in await asyncio.gather(*todo):
            results.setdefault(matcher_, {}).setdefault(name, []).append(row)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwritten: {args.out}")
    rc = report(results, args.runs)
    current = means(results)
    base_path = Path(args.baseline)
    if args.record_baseline:
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_text(json.dumps({"recorded": time.strftime("%Y-%m-%d"),
                                         "map": "technology", "model": args.model,
                                         "means": current}, indent=2) + "\n")
        print(f"baseline recorded: {base_path}")
    elif not base_path.exists():
        # Loudly: the gate's whole value is refusing a regression, and a missing file used to mean
        # it quietly did not run.
        print(f"\nNO BASELINE at {base_path} — nothing was gated. "
              f"`--record-baseline` writes one from this run.")
    else:
        recorded = json.loads(base_path.read_text())
        # A baseline scored on ANOTHER model is not the same bar. Comparing across them is exactly
        # what this flag is for, so it is reported rather than refused — but never silently, or a
        # model swap reads as a regression in the matcher.
        if recorded.get("model", args.model) != args.model:
            print(f"\nNOTE: baseline was recorded on {recorded['model']}, this run is "
                  f"{args.model} — the comparison below is across MODELS, not matchers.")
        fell = regressions(current, recorded.get("means") or {}, results_cases=results)
        if fell:
            print(f"\nREGRESSION against {base_path}: {fell}")
            rc = 2
        else:
            print(f"\nno recall regression against {base_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
