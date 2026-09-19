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
