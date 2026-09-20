"""Each step's actual output reaches the board as it lands, not when the whole run ends.

The record was stored ONCE, at the end, and its ref reached the run board only through the
workflow's final output. So while a run was in flight — which is the entire window in which anybody
watches it — the roadmap could show a step's published prose and nothing it had actually produced.
And a run that never finished showed nothing at all, ever: measured on `wfr-c53cdaa27bdb`, which
died at step 7 with four steps' worth of real output that no surface could display.

`Derivation.record` is the one place every derived output passes through, which makes it the seam.
"""
import asyncio

import pytest

from lab.workloads.usecase.derivation import Derivation


class _Agent:
    def __init__(self, out): self.out = out
    async def run(self, message): return self.out


def _d(published, publish=None):
    """A Derivation that publishes its partial record wherever the caller says.

    `publish` is a COROUTINE: it goes through the gateway, because a workload holds no store
    credential, so the seam had to be awaitable. `record` stays synchronous.
    """
    async def keep(record):
        published.append(dict(record))
    return Derivation(available={}, publish=publish or keep)


def _record_and_announce(d, *entries):
    for key, out, number in entries:
        d.record(key, out, number)
        asyncio.run(d.announce())


def test_every_recorded_output_publishes_the_record_so_far():
    published = []
    d = _d(published)
    _record_and_announce(d, ("frame", {"problem": "referrals take too long"}, "3"),
                         ("elements", {"active": []}, "4"))
    assert len(published) == 2
    assert published[0] == {"frame": {"problem": "referrals take too long"}}
    assert published[1]["elements"] == {"active": []}
    assert published[1]["frame"], "the record GROWS; each publish is the whole story so far"


def test_a_defaulted_step_publishes_too_because_it_is_an_answer():
    """A declared default is validated and gated exactly like a derived answer, and a reader must
    be able to see WHAT stood in — that is the whole reason defaulted is its own state."""
    published = []
    d = _d(published)
    _record_and_announce(d, ("realisation_match", {"existing": False, "matched": []}, "6"))
    assert published[-1]["realisation_match"]["existing"] is False


def test_publishing_is_best_effort_and_never_costs_the_run_its_answer():
    """The record is the run's product; showing it early is a convenience. A store that is down
    must not turn a completed step into a failed run."""
    async def boom(_record):
        raise RuntimeError("artifact store unreachable")

    d = Derivation(available={}, publish=boom)
    _record_and_announce(d, ("frame", {"problem": "x"}, "3"))
    assert d.derived["frame"] == {"problem": "x"}, "the answer is kept whatever the store did"


def test_no_publisher_is_the_default_so_every_existing_caller_is_unchanged():
    d = Derivation(available={})
    _record_and_announce(d, ("frame", {"problem": "x"}, "3"))
    assert d.derived["frame"] == {"problem": "x"}


def test_the_published_record_carries_what_did_not_run_as_well_as_what_did():
    """`pending` and `defaulted` are how a reader judges the rest; a partial record without them
    would read as a run that simply has fewer steps."""
    published = []
    d = _d(published)
    d.defer("8", "quality attributes — needs ['service_levels']")
    d.defaulted["6"] = "match realisations — landscape is not published"
    _record_and_announce(d, ("frame", {"problem": "x"}, "3"))
    assert published[-1]["pending_steps"]["8"].startswith("quality attributes")
    assert published[-1]["defaulted_steps"]["6"].startswith("match realisations")


# ---------------------------------------------------------------- what a step SAYS it produced

def test_a_steps_output_is_described_by_shape_never_by_content():
    """The live view is reachable by anyone holding its gate, so what travels onto the run log is
    counts and types — what a span is allowed to carry in this lab, for the same reason. A reader
    watching a run wants to know a step produced 13 matches and 1 gap; the 13 matches themselves
    are the review app's business."""
    from lab.workloads.usecase.derivation import shape_of

    out = {"matched": [1, 2, 3], "gap_flags": [{"what": "x"}], "problem": "referrals take too long",
           "existing": False, "depth": 3}
    assert shape_of(out) == {"matched": 3, "gap_flags": 1, "problem": "str",
                             "existing": "bool", "depth": "int"}


def test_no_value_from_the_output_ever_reaches_the_shape():
    """The whole point: a shape that leaked a string would put model output on a page with a
    weaker gate than the one that decides on it."""
    from lab.workloads.usecase.derivation import shape_of

    secret = "a patient's name"
    assert secret not in str(shape_of({"problem": secret, "notes": [secret]}))


def test_a_nested_structure_is_counted_not_walked():
    from lab.workloads.usecase.derivation import shape_of
    assert shape_of({"model": {"elements": [1, 2], "relations": []}}) == {"model": 2}


def test_an_empty_or_odd_output_does_not_raise():
    from lab.workloads.usecase.derivation import shape_of
    assert shape_of({}) == {} and shape_of(None) == {} and shape_of([1, 2]) == {}
