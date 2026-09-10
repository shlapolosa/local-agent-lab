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

**`expected.json` is the whole point and the only part that cannot be automated.** Precision and
recall are meaningless against a denominator a model invented; the earlier ad-hoc comparison had to
pool both matchers' outputs and adjudicate them, which can only ever measure which found more of
what one of them found. A fixed, human-reviewed set measures what they MISS.

**Cases live outside the repository.** The capability labels come from a licensed reference model
and this repository is public, so an expected set naming them is derived content that cannot be
committed. `var/` is git-ignored; `--cases` points wherever the tenant keeps them.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab.core.semantic.service import SemanticService          # noqa: E402
from lab.workloads.usecase import agents as A                  # noqa: E402
from lab.workloads.usecase import coverage                     # noqa: E402
from lab.workloads.usecase.derivation import Derivation        # noqa: E402
from lab.workloads.usecase.gates import GateFailed             # noqa: E402
from lab.workloads.usecase.steps import step_for               # noqa: E402


def corpus_for(scheme: str, reference_dir: str) -> list[dict]:
    svc = SemanticService(reference_dir=reference_dir)
    return svc.concepts(scheme, None, None)


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


async def one_run(cfg, corpus, elements, matcher: str, scheme: str) -> tuple[set, float, str]:
    """One matcher over one case: the capabilities it returned, the seconds it took, and why it
    stopped if it did."""
    d = Derivation(available={"elements": elements, "capabilities": corpus})
    started = time.time()
    note = ""
    try:
        await coverage.MATCHERS[matcher](cfg, d, corpus, scheme=scheme, project=lambda r: r)
    except GateFailed as refused:
        note = f"gate: {refused}"
    except Exception as exc:                       # noqa: BLE001 — a failed run is a DATA POINT
        note = f"{type(exc).__name__}: {exc}"
    got = {str(m.get("capability_label") or "").strip()
           for m in (d.derived.get("coverage_map") or {}).get("matched") or []}
    return {g for g in got if g}, time.time() - started, note or d.pending.get("5", "")


def score(got: set, expected: set) -> dict:
    tp = len(got & expected)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"returned": len(got), "correct": tp, "precision": precision, "recall": recall,
            "f1": f1, "wrong": sorted(got - expected), "missed": sorted(expected - got)}


def report(results: dict, runs: int) -> int:
    """What each matcher scored, and whether the difference survives the variance.

    Means over `runs` repeats, with the spread — a single sample is not evidence when the same
    step has been measured at 32 s and at 984 s. Returns non-zero when a matcher scored below the
    recall target G18 asks for, so this can gate a deploy rather than merely inform one.
    """
    target = float(os.environ.get("COVERAGE_RECALL_TARGET", "0.6"))
    print(f"\n{'matcher':10} {'case':22} {'prec':>6} {'recall':>7} {'F1':>6} {'sec':>6}   n={runs}")
    failed = []
    for matcher, cases in sorted(results.items()):
        for case, samples in sorted(cases.items()):
            mean = lambda k: statistics.fmean(s[k] for s in samples)
            spread = (f" ±{statistics.stdev(s['recall'] for s in samples):.2f}"
                      if len(samples) > 1 else "")
            print(f"  {matcher:8} {case:22} {mean('precision'):6.2f} {mean('recall'):7.2f}"
                  f"{spread} {mean('f1'):6.2f} {mean('seconds'):6.0f}")
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
    ap.add_argument("--cases", default="var/eval/coverage", help="directory of case directories")
    ap.add_argument("--matcher", action="append", choices=sorted(coverage.MATCHERS),
                    help="repeatable; default is every matcher")
    ap.add_argument("--runs", type=int, default=3, help="repeats per matcher per case")
    ap.add_argument("--scheme", default="healthcare-provider-v2.0")
    ap.add_argument("--derive", action="store_true",
                    help="derive each case's elements.json and stop — run once per case")
    ap.add_argument("--out", default="var/eval/coverage-results.json")
    args = ap.parse_args()

    gateway_url = os.environ.get("EVAL_GATEWAY") or os.environ.get("GATEWAY_URL",
                                                                   "http://127.0.0.1:4000")
    cfg = {"agents": agents_for(gateway_url,
                                os.environ.get("USECASE_AGENT_MODEL", "kimi-k3"),
                                os.environ["USECASE_AGENT_KEY"],
                                step_for("3"), step_for("4"), step_for("5"))}
    corpus = corpus_for(args.scheme, os.environ.get(
        "REFERENCE_MODELS_DIR", str(Path.home() / "Development/local-agent-lab/var/reference-sources")))
    print(f"corpus: {len(corpus)} concepts | gateway: {gateway_url}")

    cases = sorted(p for p in Path(args.cases).glob("*") if (p / "submission.md").exists())
    if not cases:
        print(f"no cases under {args.cases} — a case is a directory with submission.md, "
              f"elements.json and expected.json")
        return 2

    if args.derive:
        for case in cases:
            elements = await derive_elements(cfg, (case / "submission.md").read_text())
            (case / "elements.json").write_text(json.dumps(elements, indent=2))
            print(f"  {case.name}: {sum(len(v) for v in elements.values() if isinstance(v, list))}"
                  f" elements derived")
        return 0

    results: dict = {}
    for matcher in (args.matcher or sorted(coverage.MATCHERS)):
        for case in cases:
            expected = set(json.loads((case / "expected.json").read_text())["applicable"])
            elements = json.loads((case / "elements.json").read_text())
            for run in range(args.runs):
                got, seconds, note = await one_run(cfg, corpus, elements, matcher, args.scheme)
                row = score(got, expected) | {"seconds": seconds, "note": note, "run": run}
                results.setdefault(matcher, {}).setdefault(case.name, []).append(row)
                print(f"  {matcher:8} {case.name:22} run {run + 1}/{args.runs}  "
                      f"P {row['precision']:.2f} R {row['recall']:.2f}  {seconds:4.0f}s"
                      f"{'  ' + note[:50] if note else ''}", flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwritten: {args.out}")
    return report(results, args.runs)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
