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


# ---------------------------------------------------------------- what the numbers are made of

CORPUS = [{"id": "D", "label": "D", "level": 1, "parent": None, "path": "D", "definition": "a domain"},
          {"id": "D · One", "label": "One", "level": 2, "parent": "D", "path": "D · One",
           "definition": "x" * 400},
          {"id": "D · Two", "label": "Two", "level": 2, "parent": "D", "path": "D · Two",
           "definition": "y" * 400}]


def test_the_stage_metrics_separate_retrieval_from_choosing():
    """The two have opposite fixes, and an end-to-end number cannot tell them apart. `reachable` is
    the ceiling — a chooser cannot return what it was never shown — and `chose` is what it took of
    what it could have."""
    out = ev.score(got={"a"}, expected={"a", "b", "c"}, offered={"a", "b"})
    assert out["recall"] == 1 / 3
    assert out["reachable"] == 2 / 3, "b was shown, c never was"
    assert out["chose"] == 1 / 2, "of the two it could have taken, it took one"
    assert out["unreachable"] == ["c"]


def test_perfect_retrieval_and_a_silent_chooser_is_distinguishable_from_the_reverse():
    """The measurement the whole technology-map result rests on: reachable 1.00 everywhere means
    every miss is the chooser, which is why HyDE and a tree walk were dropped rather than built."""
    chooser = ev.score(got=set(), expected={"a", "b"}, offered={"a", "b"})
    retrieval = ev.score(got={"a"}, expected={"a", "b"}, offered={"a"})
    assert chooser["reachable"] == 1.0 and chooser["chose"] == 0.0
    assert retrieval["reachable"] == 0.5 and retrieval["chose"] == 1.0


def test_score_without_an_offered_set_reports_no_stage_metrics_rather_than_zeroes():
    """Absent is not zero. A zero `reachable` would read as retrieval that found nothing."""
    assert "reachable" not in ev.score(got={"a"}, expected={"a"})


def test_an_expected_set_that_is_empty_scores_zero_rather_than_dividing_by_zero():
    assert ev.score(got={"a"}, expected=set())["recall"] == 0.0


def test_identity_of_prefers_the_id_and_falls_back_to_resolving_the_label():
    """A reasoning model writes the label where the key belongs — measured, not hypothetical. The
    id is what the guardrails and the component catalogue join on, so it is what we score; refusing
    a label would score the model's field discipline rather than its judgement."""
    assert ev.identity_of({"capability_id": "D · One"}, CORPUS) == "D · One"
    assert ev.identity_of({"capability_id": "One", "capability_label": "One"}, CORPUS) == "D · One"


def test_an_identity_nothing_can_resolve_is_returned_as_written_so_it_scores_wrong():
    """Not dropped. A match nothing can look up is a visible wrong answer, not an absent one."""
    assert ev.identity_of({"capability_id": "invented"}, CORPUS) == "invented"


def test_present_none_strips_definitions_and_full_keeps_them():
    assert all("definition" not in c for c in ev.present(CORPUS, "none", 200_000, 2))
    assert all("definition" in c for c in ev.present(CORPUS, "full", 200_000, 2))


def test_present_fit_drops_definitions_that_will_not_fit_the_budget():
    """The trim is the production constant's behaviour, and a definition too short to discriminate
    is worse than none — it costs prompt and says nothing a label does not."""
    tight = ev.present(CORPUS, "fit", 120, 2)
    assert all(not c.get("definition") for c in tight if c["level"] == 2)


def test_present_never_drops_a_concept_whatever_the_budget():
    """A projection, not a truncation: the match must see the whole map and still be able to
    refuse. Losing a candidate silently shrinks what it could ever have matched."""
    for mode in ("none", "fit", "full"):
        assert len(ev.present(CORPUS, mode, 100, 2)) == len(CORPUS)


def test_corpus_from_file_refuses_rows_that_are_not_concepts(tmp_path):
    """A table is not a corpus. Accepting one would yield no candidates at the grain, which reads
    downstream as 'nothing is relevant' rather than as the wrong file."""
    import json
    p = tmp_path / "rows.json"
    p.write_text(json.dumps([{"label": "no id or level"}]))
    with __import__("pytest").raises(SystemExit):
        ev.corpus_from_file(str(p))


def test_the_technology_map_projects_at_its_own_grain_and_is_not_empty():
    """The harness scores what a RUN is shown, through the same mapper — so a change to the
    projection cannot improve the score without changing the run."""
    from lab.core.usecase import capabilities
    made = ev.technology_map()
    assert len(made) > 50
    assert {c["level"] for c in made} == {1, capabilities.LEVEL}
    assert all(capabilities.SEP in c["id"] for c in made if c["level"] == capabilities.LEVEL)


def test_the_default_baseline_is_a_file_that_exists():
    """The gate's default pointed at `coverage-baseline.json` for two days after the file was
    renamed `technology-baseline.json`. `base_path.exists()` was simply False, so every run since
    printed nothing and compared against nothing — a gate that cannot fail is not a gate. The
    default is asserted rather than the rename remembered."""
    assert (ROOT / ev.BASELINE).is_file(), f"{ev.BASELINE} does not exist"


def test_the_baseline_records_the_model_it_was_scored_on():
    """A baseline is a bar for ONE model. Comparing a run on another model against it measures the
    swap, not the matcher — which is legitimate and is why `--model` exists, but it has to be said
    out loud. Recording the model is what makes saying it possible."""
    import json
    recorded = json.loads((ROOT / ev.BASELINE).read_text())
    assert recorded.get("model"), "the baseline names no model, so no run can tell it apart"


def test_a_tally_is_recoverable_from_one_sampled_run_so_every_k_scores_from_it():
    """Scoring k=2 and k=3 by SAMPLING TWICE costs twice the tokens and compares two different
    draws — a difference between them is then partly the threshold and partly the second sample,
    and nothing separates the two.

    It is unnecessary: a sampled run keeps every pair that got at least one vote — `matched` at or
    above the threshold, `excluded` below it — and both carry `votes`. So one pass at k=1 holds the
    whole tally, and every threshold is arithmetic over it.
    """
    trail = {"matched": [{"capability_id": "c1", "votes": 3}, {"capability_id": "c2", "votes": 2},
                         {"capability_id": "c3", "votes": 1}],
             "excluded": []}
    assert {m["capability_id"] for m in ev.at_threshold(trail, 1)} == {"c1", "c2", "c3"}
    assert {m["capability_id"] for m in ev.at_threshold(trail, 2)} == {"c1", "c2"}
    assert {m["capability_id"] for m in ev.at_threshold(trail, 3)} == {"c1"}


def test_the_tally_includes_what_the_run_s_own_threshold_excluded():
    trail = {"matched": [{"capability_id": "c1", "votes": 3}],
             "excluded": [{"capability_id": "c2", "votes": 1}]}
    assert {m["capability_id"] for m in ev.at_threshold(trail, 1)} == {"c1", "c2"}


def test_an_unsampled_run_counts_every_match_once_rather_than_scoring_nothing():
    """A single pass records no `votes`. Treating a missing vote as zero would score an ordinary
    run as having matched nothing at all."""
    trail = {"matched": [{"capability_id": "c1"}]}
    assert {m["capability_id"] for m in ev.at_threshold(trail, 1)} == {"c1"}
    assert ev.at_threshold(trail, 2) == []


def test_a_baseline_missing_cases_the_run_attempted_is_refused():
    """Measured 21 Sep 2026: the eval key hit its budget mid-run, four of six cases scored nothing,
    and `--record-baseline` wrote a two-case baseline over a six-case one. Nothing failed loudly.

    That is worse than a wrong number, because `regressions` only checks pairs the BASELINE holds:
    the four missing cases would simply have stopped being gated, and the next run would have
    reported "no recall regression" while measuring a third of the bar.
    """
    attempted = {"leaves": {"a": [], "b": [], "c": []}}
    scored = {"leaves": {"a": {"recall": 0.8, "n": 3}}}
    missing = ev.unscored(scored, attempted)
    assert missing == ["leaves/b", "leaves/c"]


def test_a_baseline_covering_everything_it_attempted_is_accepted():
    attempted = {"leaves": {"a": [], "b": []}}
    scored = {"leaves": {"a": {"recall": 0.8}, "b": {"recall": 0.7}}}
    assert ev.unscored(scored, attempted) == []


def test_results_from_several_runs_merge_into_one_set_of_samples():
    """A 30-run baseline is one long invocation, and on an 8 GB box a long invocation is one the
    OS can kill — twice, measured 21 Sep 2026, at 17 of 30 runs and then again. Recording the bar
    from SAVED results makes it resumable: score a case at a time, merge, record once.
    """
    a = {"leaves": {"c1": [{"precision": 0.8, "recall": 0.8, "f1": 0.8}]}}
    b = {"leaves": {"c1": [{"precision": 0.6, "recall": 0.6, "f1": 0.6}],
                    "c2": [{"precision": 0.5, "recall": 0.5, "f1": 0.5}]}}
    merged = ev.merge([a, b])
    assert len(merged["leaves"]["c1"]) == 2 and len(merged["leaves"]["c2"]) == 1
    assert ev.means(merged)["leaves"]["c1"]["recall"] == 0.7


def test_merging_nothing_is_an_empty_set_rather_than_an_error():
    assert ev.merge([]) == {}


def test_a_merged_set_is_still_refused_as_a_baseline_when_a_case_is_missing():
    """Resumability must not become a way to record a partial bar by accident — the same guard
    applies, now over the merged whole."""
    merged = ev.merge([{"leaves": {"c1": [{"precision": 1.0, "recall": 1.0, "f1": 1.0}]}}])
    assert ev.unscored(ev.means(merged), {"leaves": {"c1": [], "c2": []}}) == ["leaves/c2"]


def test_the_baseline_records_the_sample_count_it_was_measured_at():
    """A bar is a bar for ONE configuration. It already records the model, for exactly this reason:
    comparing a samples=3 run against a samples=1 bar measures the change in sampling, not a
    regression in the matcher — and sampling moved mean recall 0.715 -> 0.79, which would read as
    a spectacular improvement or, reversed, a spectacular loss."""
    import json
    recorded = json.loads((ROOT / ev.BASELINE).read_text())
    assert "samples" in recorded, "the baseline does not say how many samples it was measured at"


def test_record_from_refuses_when_a_case_on_disk_is_not_in_the_results():
    """The guard that catches a budget failure does NOT catch this one: `unscored` compares the
    scored means against the results it was GIVEN, and `--record-from` is given only the files that
    exist. Two result files therefore looked complete and recorded a two-case bar — the very defect
    this harness was fixed for, through a door opened by the fix.

    The authority for "what a full bar covers" is the cases DIRECTORY, so that is what it is
    checked against.
    """
    on_disk = ["appointment-no-show", "imaging-order-triage", "policy-qa"]
    merged = {"leaves": {"appointment-no-show": [], "imaging-order-triage": []}}
    assert ev.cases_missing(merged, on_disk) == ["policy-qa"]
    assert ev.cases_missing({"leaves": {c: [] for c in on_disk}}, on_disk) == []


def test_a_case_directory_that_is_empty_makes_no_claim():
    assert ev.cases_missing({"leaves": {"a": []}}, []) == []
