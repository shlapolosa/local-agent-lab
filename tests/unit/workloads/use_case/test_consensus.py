"""Sampling step 5 and voting — the answer to a spread that decoding options cannot close.

Measured 20 Sep 2026 on step 5's real payload (74 candidates with definitions, ~22 KB): both
`gpt-5.4-mini` and `gpt-5.4-mini-think` at temperature=0 WITH a seed returned three distinct
answers out of three. So the step is sampled and the samples vote, and what the vote LEAVES OUT
travels with the record — a capability two runs of three chose is not a wrong answer, it is a
disagreement, and the approver is the one entitled to settle it.
"""
from lab.workloads.usecase import coverage


def m(function, ident, label="L", confidence="lookup"):
    return {"function": function, "capability_id": ident, "capability_label": label,
            "confidence": confidence}


#: A REAL step-5 answer — one that passes the completeness rule. The fixtures here used to be the
#: three fields these tests happened to read, which is how the voted object went ungated for a
#: session: a double that cannot pass the gate cannot show that the gate was never run.
def sample(*matches, **rest):
    out = {"matched": list(matches), "functions_without_capability": [],
           "capabilities_without_function": [],
           "heat_map": {"commodity": False, "mature": False, "meets_target": False,
                        "source": "the published map carries no heat-map position"},
           **rest}
    return out


def test_a_match_every_sample_made_is_kept_and_carries_its_full_vote():
    s = sample(m("intake a form", "c1"))
    agreed, excluded = coverage.vote([s, s, s], threshold=2)
    assert [x["capability_id"] for x in agreed["matched"]] == ["c1"]
    assert agreed["matched"][0]["votes"] == 3 and agreed["matched"][0]["of"] == 3
    assert excluded == []


def test_a_match_below_the_threshold_is_excluded_rather_than_dropped():
    """The whole point of the change for an approver: a capability one run of three chose is
    evidence of a disagreement, and deleting it silently is what made the spread invisible."""
    agreed, excluded = coverage.vote(
        [sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1")), sample(m("f", "c1"))],
        threshold=2)
    assert [x["capability_id"] for x in agreed["matched"]] == ["c1"]
    assert excluded == [{"function": "f", "capability_id": "c2", "capability_label": "L",
                         "confidence": "lookup", "votes": 1, "of": 3}]


def test_a_capability_matched_for_a_DIFFERENT_function_is_a_different_vote():
    """The unit is the PAIR. The same capability serving two functions is two claims, and pooling
    them would let one well-agreed function carry a second that nothing agreed on."""
    agreed, _ = coverage.vote([sample(m("f1", "c1"), m("f2", "c1")),
                               sample(m("f1", "c1")), sample(m("f1", "c1"))], threshold=2)
    assert {(x["function"], x["capability_id"]) for x in agreed["matched"]} == {("f1", "c1")}


def test_the_kept_match_keeps_the_fields_a_real_answer_carried():
    agreed, _ = coverage.vote([sample(m("f", "c1", label="Intake", confidence="assumption"))],
                              threshold=1)
    kept = agreed["matched"][0]
    assert kept["capability_label"] == "Intake" and kept["confidence"] == "assumption"


def test_the_gap_lists_are_voted_on_the_same_terms_as_the_matches():
    """A function reported as having no capability by ONE run of three is not a gap; it is the
    same disagreement seen from the other side."""
    agreed, _ = coverage.vote(
        [sample(functions_without_capability=["a", "b"]),
         sample(functions_without_capability=["a"]),
         sample(functions_without_capability=["a"])], threshold=2)
    assert agreed["functions_without_capability"] == ["a"]


def test_one_sample_is_the_behaviour_that_was_there_before():
    """`COVERAGE_SAMPLES=1` must be exactly today's run — a threshold of one, nothing excluded,
    so turning sampling off is a real off switch and not a differently-shaped answer."""
    s = sample(m("f", "c1"), m("f", "c2"), functions_without_capability=["x"])
    agreed, excluded = coverage.vote([s], threshold=1)
    assert [x["capability_id"] for x in agreed["matched"]] == ["c1", "c2"]
    assert agreed["functions_without_capability"] == ["x"] and excluded == []


def test_no_samples_votes_nothing_rather_than_raising():
    assert coverage.vote([], threshold=1) == ({}, [])


def test_the_majority_of_n_is_more_than_half_of_it():
    assert [coverage.majority(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 2, 3, 3]


def test_the_agreed_order_is_the_order_the_first_sample_gave():
    """Deterministic output from the vote itself, or the sampling would trade one kind of jitter
    for another."""
    a = sample(m("f", "c2"), m("f", "c1"))
    b = sample(m("f", "c1"), m("f", "c2"))
    agreed, _ = coverage.vote([a, b], threshold=1)
    assert [x["capability_id"] for x in agreed["matched"]] == ["c2", "c1"]


# ------------------------------------------------- the sampling loop that feeds the vote

class _Sampling:
    """A Derivation stand-in that answers DIFFERENTLY each call — which is the whole condition
    being designed for, and which a stand-in returning one fixed answer cannot exercise."""

    def __init__(self, answers):
        self.available, self.derived, self.pending = {}, {}, {}
        self.answers, self.calls, self.labels, self.candidates = list(answers), 0, [], []

    async def run_step(self, cfg, step, *, label="", context=None):
        self.labels.append(label)
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if answer is None:
            return False
        self.derived["coverage_map"] = answer
        return True

    def defer(self, number, why): self.pending[number] = why
    def record(self, key, out, number=""): self.derived[key] = out


CANDS = [{"id": f"c{n}", "label": f"Cap {n}", "path": f"Z > Cap {n}"} for n in (1, 2, 3, 9)]


def _run(d, **kw):
    import asyncio
    return asyncio.run(coverage._one_pass({}, d, CANDS, label="match capabilities", **kw))


def test_sampling_asks_the_step_n_times_and_records_the_VOTE_not_the_last_answer():
    """The last sample is an arbitrary one of n. Recording it would spend n times the tokens to
    get exactly the variance sampling was bought to remove."""
    d = _Sampling([sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1")), sample(m("f", "c1"))])
    out = _run(d, samples=3)
    assert d.calls == 3
    assert [x["capability_id"] for x in d.derived["coverage_map"]["matched"]] == ["c1"]
    assert out["coverage_trail"][0]["samples"] == 3


def test_what_the_vote_left_out_travels_on_the_outcome_for_the_approver():
    d = _Sampling([sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1")), sample(m("f", "c1"))])
    out = _run(d, samples=3)
    assert out["coverage_trail"][0]["excluded"] == [
        {"function": "f", "capability_id": "c2", "capability_label": "L",
         "confidence": "lookup", "votes": 1, "of": 3}]


def test_one_sample_asks_once_and_says_nothing_about_votes_in_the_label():
    d = _Sampling([sample(m("f", "c1"))])
    _run(d, samples=1)
    assert d.calls == 1 and d.labels == ["match capabilities"]


def test_each_sample_is_labelled_so_a_watcher_sees_three_asks_not_one_stall():
    d = _Sampling([sample(m("f", "c1"))])
    _run(d, samples=3)
    assert d.labels == [f"match capabilities — sample {i}/3" for i in (1, 2, 3)]


def test_a_sample_that_does_not_run_does_not_sink_the_ones_that_did():
    """A gate failure or an unwired agent on sample 3 of 3 must not discard samples 1 and 2 — the
    step's answer is what the runs that ANSWERED agreed on, and the threshold is of those."""
    d = _Sampling([sample(m("f", "c1")), sample(m("f", "c1")), None])
    out = _run(d, samples=3)
    assert d.derived["coverage_map"]["matched"][0]["votes"] == 2
    assert out["coverage_trail"][0]["samples"] == 2, "the count is what actually answered"


def test_no_sample_at_all_defers_exactly_as_a_single_failed_pass_did():
    d = _Sampling([None])
    assert _run(d, samples=3) == {}
    assert d.derived == {}


def test_the_threshold_defaults_to_a_majority_of_what_answered_not_of_what_was_asked():
    """Two samples of three answering, a threshold of 2: a match both made is agreed. Had the
    majority been taken of the three ASKED, the same two-of-two match would have needed a vote
    that could no longer be cast."""
    d = _Sampling([sample(m("f", "c1")), sample(m("f", "c1")), None])
    _run(d, samples=3)
    assert [x["capability_id"] for x in d.derived["coverage_map"]["matched"]] == ["c1"]


def test_a_configured_threshold_is_honoured_and_cannot_exceed_what_answered():
    """`COVERAGE_VOTES` is tuned on the frozen eval cases, so it must be settable — but a threshold
    above the number of samples that answered would agree on nothing at all and read as a step that
    found no capabilities, which is the one failure mode worse than a wide match."""
    d = _Sampling([sample(m("f", "c1")), sample(m("f", "c1"))])
    _run(d, samples=2, threshold=5)
    assert [x["capability_id"] for x in d.derived["coverage_map"]["matched"]] == ["c1"]

    strict = _Sampling([sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1"))])
    _run(strict, samples=2, threshold=2)
    assert [x["capability_id"] for x in strict.derived["coverage_map"]["matched"]] == ["c1"]


def test_the_run_log_is_stamped_with_the_VOTE_not_with_the_last_sample():
    """Each sample stamps `step_5` as it runs, so without a re-stamp the live view shows an
    arbitrary one of n while the record holds the agreed answer. An instrument that disagrees with
    the record is worse than no instrument."""
    import asyncio
    stamped = []
    d = _Sampling([sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1")), sample(m("f", "c1"))])
    asyncio.run(coverage._one_pass({"run_id": "r1"}, d, CANDS, label="match capabilities",
                                   samples=3, _stamp=lambda cfg, step, out: stamped.append(out)))
    assert [x["capability_id"] for x in stamped[-1]["matched"]] == ["c1"], "the vote, last word"


def test_the_re_stamp_goes_through_the_one_helper_that_knows_about_boards():
    """Injected only so the vote can be observed in a test. The DEFAULT must be the real helper,
    or the seam would quietly become a second place that decides what reaches the run log —
    including whether a run without a board is stamped at all."""
    import inspect
    from lab.workloads.usecase import derivation
    default = inspect.signature(coverage._one_pass).parameters["_stamp"].default
    assert default is derivation.stamp_shape

    import asyncio
    d = _Sampling([sample(m("f", "c1"))])          # no run_id: the helper returns, nothing raises
    asyncio.run(coverage._one_pass({}, d, CANDS, label="x", samples=1))
    assert d.derived["coverage_map"]["matched"][0]["votes"] == 1


# ------------------------------------------------ naming a match the corpus already named

def test_a_match_is_given_the_label_of_the_candidate_its_id_was_copied_from():
    """`capability_label` is optional and the model routinely omits it, so the record — and every
    reader of it — was left with `tec-cap-0031`. The id was COPIED character for character from a
    candidate this step was shown, and that candidate carries the label, so the name is a join the
    workload can do itself rather than a thing to ask a model for or to render around."""
    matched = [{"function": "f", "capability_id": "c1", "confidence": "lookup"}]
    named = coverage.named(matched, CANDS)
    assert named[0]["capability_label"] == "Cap 1"
    assert named[0]["capability_id"] == "c1", "the id is untouched — it is what joins"


def test_a_label_the_model_did_supply_is_not_overwritten():
    """The model saw the candidate too. If it chose different words, that is its answer and this
    is not the place to silently correct it."""
    matched = [{"function": "f", "capability_id": "c1", "capability_label": "its own words"}]
    assert coverage.named(matched, CANDS)[0]["capability_label"] == "its own words"


def test_an_id_no_candidate_carries_is_left_exactly_as_it_is():
    """A hallucinated or mistyped id must stay visible as one. Inventing a label for it would make
    an unjoinable row look like a good one — which the eval counts as `invalid_ids` precisely
    because it cannot be allowed to read as a match."""
    matched = [{"function": "f", "capability_id": "not-on-the-list"}]
    assert "capability_label" not in coverage.named(matched, CANDS)[0]


def test_the_vote_hands_back_matches_that_are_already_named():
    d = _Sampling([sample(m("f", "c1", label=""))])
    _run(d, samples=1)
    assert d.derived["coverage_map"]["matched"][0]["capability_label"] == "Cap 1"


# ------------------------------------- the vote must not produce what a single pass could not

def test_a_function_whose_matches_all_lose_becomes_an_uncovered_function():
    """The defect this closes, and it was mine. Three samples that each match function F to a
    DIFFERENT capability give three pairs at one vote, all below majority, all excluded — and no
    sample ever listed F as uncovered. F then appeared in neither list: not a match, not a gap, and
    the coverage check silently did not happen for it.

    Downstream that is worse than it sounds: `capability_matched` reads False rather than None
    (the step was not DEFAULTED), so step 16's reject rule fires on a use case nobody assessed."""
    samples = [sample(m("f", "c1"), m("g", "c9")),
               sample(m("f", "c2"), m("g", "c9")),
               sample(m("f", "c3"), m("g", "c9"))]
    agreed, excluded = coverage.vote(samples, threshold=2)
    assert [x["capability_id"] for x in agreed["matched"]] == ["c9"]
    assert "f" in agreed["functions_without_capability"], "f lost every match and must be a gap"
    assert "g" not in agreed["functions_without_capability"]
    assert {x["capability_id"] for x in excluded} == {"c1", "c2", "c3"}, "still adjudicable"


def test_a_function_that_kept_a_match_is_not_also_reported_as_uncovered():
    agreed, _ = coverage.vote([sample(m("f", "c1"), m("f", "c2")), sample(m("f", "c1")),
                               sample(m("f", "c1"))], threshold=2)
    assert agreed["functions_without_capability"] == []


def test_the_voted_answer_is_gated_before_it_is_recorded():
    """The gate ran per SAMPLE and never on the vote, so the invariants it exists to enforce did
    not hold of what was recorded. A vote is a new answer and is gated like one."""
    import asyncio
    gated = []
    d = _Sampling([sample(m("f", "c1")), sample(m("f", "c1")), sample(m("f", "c1"))])
    asyncio.run(coverage._one_pass({}, d, CANDS, label="x", samples=3,
                                   _gate=lambda out: gated.append(out) or []))
    assert gated, "the voted object was never gated"
    assert gated[-1]["matched"][0]["votes"] == 3


def test_a_vote_that_fails_the_gate_defers_rather_than_recording_it():
    import asyncio
    d = _Sampling([sample(m("f", "c1"))])
    out = asyncio.run(coverage._one_pass({}, d, CANDS, label="x", samples=1,
                                         _gate=lambda out: ["coverage was not checked"]))
    assert out == {} and "5" in d.pending
    assert "coverage_map" not in d.derived, "an answer that failed its gate must not be recorded"
