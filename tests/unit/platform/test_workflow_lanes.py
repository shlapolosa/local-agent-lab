"""`workflows.submit_lanes` — one recording becomes one run PER PROVIDER.

A lane is not new orchestration: it is the existing process, submitted once per provider. That is
the whole design, and it is why four providers get four run ids, four approvals, four continuations
and four sets of minutes without a second workflow engine.

Two things here are easy to get wrong and expensive to discover live:
  * the idempotency key must be PER LANE, or one key de-duplicates four lanes into one run and the
    comparison silently becomes a single provider;
  * a lane that cannot be submitted must not take the others down with it.
"""
import pytest

from lab.platform import contracts, workflows
from fixtures.fakes import FakeRedis

PROC = contracts.MEETING_TO_TRANSCRIPT.name
GOOD = {"owner": "maria@contoso.com", "recording": "collab://recording/m1/r1"}


def test_one_submission_becomes_one_run_per_lane_each_naming_its_provider():
    r = FakeRedis()
    got = workflows.submit_lanes(PROC, dict(GOOD), "flow", lanes=("munsit", "elevenlabs"), client=r)
    assert [g["provider"] for g in got] == ["munsit", "elevenlabs"]
    assert len({g["request_id"] for g in got}) == 2, "each lane is its own run"
    for g in got:
        state = workflows.status(g["request_id"], client=r)
        assert state["inputs"]["provider"] == g["provider"]
        assert state["inputs"]["recording"] == GOOD["recording"]


def test_no_lanes_means_exactly_one_run_and_no_provider_at_all():
    """A deployment running a single provider must behave precisely as it did before lanes existed —
    including not writing a `provider` input its consumer would then have to interpret."""
    r = FakeRedis()
    got = workflows.submit_lanes(PROC, dict(GOOD), "flow", lanes=(), client=r)
    assert len(got) == 1 and got[0]["provider"] == ""
    assert "provider" not in workflows.status(got[0]["request_id"], client=r)["inputs"]


def test_the_idempotency_key_is_per_lane_or_four_lanes_collapse_into_one():
    """THE bug this test exists for: one key across four lanes means the second lane is handed the
    first lane's run id with duplicate=True, and a four-provider comparison quietly becomes one."""
    r = FakeRedis()
    lanes = ("munsit", "elevenlabs", "assemblyai")
    first = workflows.submit_lanes(PROC, dict(GOOD), "flow", lanes=lanes,
                                   idempotency_key="recording-r1", client=r)
    assert len({g["request_id"] for g in first}) == 3
    assert not any(g["duplicate"] for g in first)

    # ...and the whole fan-out is still retry-safe: the same key returns the same three runs
    again = workflows.submit_lanes(PROC, dict(GOOD), "flow", lanes=lanes,
                                   idempotency_key="recording-r1", client=r)
    assert [g["request_id"] for g in again] == [g["request_id"] for g in first]
    assert all(g["duplicate"] for g in again)


def test_a_lane_that_cannot_be_submitted_does_not_take_the_others_down():
    """One unknown provider must cost one lane, not the comparison. The failure is REPORTED on that
    lane rather than raised, because the run that matters may be one of the others."""
    r = FakeRedis()
    got = workflows.submit_lanes(PROC, dict(GOOD), "flow",
                                 lanes=("munsit", "not-a-provider", "elevenlabs"), client=r)
    assert [g["provider"] for g in got] == ["munsit", "not-a-provider", "elevenlabs"]
    assert got[1]["request_id"] == "" and "not-a-provider" in got[1]["error"]
    assert got[0]["request_id"] and got[2]["request_id"]


def test_a_process_with_no_lane_field_refuses_to_be_fanned_out():
    """Fanning out a process that cannot say which lane it is would submit N identical runs."""
    with pytest.raises(ValueError, match="provider"):
        workflows.submit_lanes(contracts.VISIO_TO_ARCHIMATE.name,
                               {"diagram": "art://a/b.vsdx"}, "flow",
                               lanes=("munsit",), client=FakeRedis())
