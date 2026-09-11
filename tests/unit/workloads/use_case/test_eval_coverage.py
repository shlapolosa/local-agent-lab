"""The coverage harness's baseline gate — pure functions over its own results shape.

The harness is a script (exempt from the coverage target), but the two functions that decide
whether a change SHIPS are worth holding still: a baseline nobody can regress against is a number,
not a test.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("eval_coverage", ROOT / "scripts" / "eval_coverage.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def _row(p, r, note=""):
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0, "note": note}


def test_means_average_the_runs_that_scored_and_carry_no_labels():
    results = {"leaves": {"c1": [_row(0.4, 0.5), _row(0.3, 0.5), _row(0.0, 0.0, note="429")]}}
    m = ev.means(results)
    assert m == {"leaves": {"c1": {"precision": 0.35, "recall": 0.5, "f1": 0.41, "n": 2}}}
    assert "missed" not in str(m) and "wrong" not in str(m)


def test_a_recall_drop_beyond_tolerance_is_a_regression_and_nothing_else_is():
    base = {"leaves": {"c1": {"recall": 0.5}, "c2": {"recall": 0.6}}, "drill": {"c1": {"recall": 0.5}}}
    now = {"leaves": {"c1": {"recall": 0.40}, "c2": {"recall": 0.58}}, "vector": {"c1": {"recall": 0.1}}}
    fell = ev.regressions(now, base)
    assert fell == ["leaves/c1 recall 0.40 < baseline 0.50 (-0.10)"]
    assert ev.regressions(base, base) == []


def test_a_pair_the_run_attempted_but_never_scored_is_a_regression_not_an_absence():
    """A run of all-429s once reported "no regression": every row carried a note, `means` dropped
    them all, and the baseline pair looked simply unmeasured."""
    base = {"leaves": {"c1": {"recall": 0.5}}}
    attempted = {"leaves": {"c1": [_row(0.0, 0.0, note="429")]}}
    assert ev.regressions(ev.means(attempted), base, results_cases=attempted) == [
        "leaves/c1: no run scored (every run failed) — baseline recall 0.50"]
    assert ev.regressions({}, base, results_cases={}) == [], "not attempted is not a regression"
