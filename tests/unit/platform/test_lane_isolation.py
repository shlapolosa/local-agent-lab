"""One lane fails; the others finish. Composed, not stage by stage.

Every stage already guards itself and every guard has its own test — submit, the run, the
continuation, delivery, the announcement. What none of them shows is the thing actually claimed:
that a meeting run through several providers survives ONE of them failing, all the way to the
message a person receives. The stages are individually correct and the composition is what a person
relies on, so it is asserted here.

The failure this rules out is quiet, and it is the one that makes a bake-off worthless: three lanes
submitted, one provider unpaid or throttled, and the whole meeting reported as failed — or, worse,
the two good lanes silently never announced because the failed one poisoned the shared step.
"""
from lab.platform import contracts, workflows
from lab.platform.contracts import WorkflowStatus
from lab.substrate import meeting_notifier
from fixtures.fakes import FakeRedis

PROC = contracts.MEETING_TO_TRANSCRIPT.name
MINUTES = contracts.TRANSCRIPT_TO_MINUTES.name
LANES = ("munsit", "elevenlabs", "assemblyai")
RECORDING = {"owner": "maria@contoso.com", "recording": "collab://recording/m1/r1"}


def test_one_failed_lane_leaves_the_others_finishing_and_announced():
    r = FakeRedis()
    rows = workflows.submit_lanes(PROC, dict(RECORDING), "flow", lanes=LANES,
                                  idempotency_key="rec-r1", client=r)
    assert len(rows) == 3 and all(row["request_id"] for row in rows)
    by_lane = {row["provider"]: row["request_id"] for row in rows}

    # elevenlabs' provider refuses the credential mid-run — the shape of an unfunded account
    workflows.mark(by_lane["elevenlabs"], WorkflowStatus.FAILED, client=r,
                   error="the provider refused the credential (balance exhausted)")
    for lane in ("munsit", "assemblyai"):
        workflows.mark(by_lane[lane], WorkflowStatus.DONE, client=r,
                       approval_id=f"apr-{lane}")

    states = {lane: workflows.status(rid, client=r) for lane, rid in by_lane.items()}
    assert states["elevenlabs"]["status"] == WorkflowStatus.FAILED.value
    assert "balance exhausted" in states["elevenlabs"]["error"]
    # ...and the other two are untouched: their status, their own approval, their own inputs
    for lane in ("munsit", "assemblyai"):
        assert states[lane]["status"] == WorkflowStatus.DONE.value
        assert states[lane]["approval_id"] == f"apr-{lane}"
        assert states[lane]["inputs"]["provider"] == lane
        assert "error" not in states[lane]


def test_the_failed_lane_is_retryable_on_its_own_without_disturbing_the_others():
    """The idempotency claim is released by a FAILED run, so funding the account and resubmitting
    re-runs ONLY that lane. If the claim were shared, retrying the failure would either be refused
    for the whole day or would re-run all three."""
    r = FakeRedis()
    first = workflows.submit_lanes(PROC, dict(RECORDING), "flow", lanes=LANES,
                                   idempotency_key="rec-r1", client=r)
    by_lane = {row["provider"]: row["request_id"] for row in first}
    workflows.mark(by_lane["elevenlabs"], WorkflowStatus.FAILED, client=r, error="unpaid")
    for lane in ("munsit", "assemblyai"):
        workflows.mark(by_lane[lane], WorkflowStatus.DONE, client=r)

    again = workflows.submit_lanes(PROC, dict(RECORDING), "flow", lanes=LANES,
                                   idempotency_key="rec-r1", client=r)
    got = {row["provider"]: row for row in again}
    assert got["elevenlabs"]["request_id"] != by_lane["elevenlabs"], "a failed lane must re-run"
    assert not got["elevenlabs"]["duplicate"]
    for lane in ("munsit", "assemblyai"):
        assert got[lane]["request_id"] == by_lane[lane] and got[lane]["duplicate"], \
            f"{lane} already did the work; retrying the failed lane must not repeat it"


def test_only_the_lanes_that_delivered_are_announced_and_each_names_its_own_files():
    """The notifier is the last shared step, and the one where a failed lane could still silence the
    good ones. Each announcement is built from its OWN run, so three lanes produce three messages
    whose files are named for their provider — which is what makes them distinguishable in the one
    chat they all land in."""
    def state(lane, status, delivered):
        return {"status": status.value, "chat_id": "19:meeting_x@thread.v2",
                "request_id": f"wfr-{lane}", "provider": lane,
                "delivered": [{"name": f"rec.{lane}.{kind}", "url": f"https://x/{lane}.{kind}",
                               "handle": f"collab://item/d/{lane}"} for kind in delivered],
                "summary": {"decisions": 1, "actions": 2, "speakers": 2}}

    said = {lane: meeting_notifier.announcement(
        state(lane, WorkflowStatus.DONE, ("transcript.md", "minutes.json"))) for lane in LANES}
    assert all(s is not None for s in said.values())
    names = [f["name"] for s in said.values() for f in s["files"]]
    assert len(set(names)) == 6, "six distinct filenames — no lane can overwrite another's output"

    # the failed lane says NOTHING rather than announcing an empty delivery
    assert meeting_notifier.announcement(state("elevenlabs", WorkflowStatus.FAILED, ())) is None
    # ...and so does a lane that ran but delivered nothing: there is no link to offer
    assert meeting_notifier.announcement(state("munsit", WorkflowStatus.DONE, ())) is None


def test_a_single_submit_acknowledges_the_provider_it_actually_runs():
    """The acknowledgement must describe the run, or it is worse than saying nothing.

    Measured live 9 Sep 2026: `meeting_to_transcript_submit` with `provider: "elevenlabs"` answered
    `lanes: [{"provider": ""}]` while the run correctly used elevenlabs — the caller was told its
    choice had been dropped. That reads exactly like the lane defect this file exists for, where the
    provider really WAS dropped, so a reader checking the acknowledgement could not tell a working
    run from a broken one. A field that lies in the safe case teaches people to ignore it in the
    unsafe one.
    """
    r = FakeRedis()
    named = workflows.submit_lanes(PROC, {**RECORDING, "provider": "elevenlabs"}, "cli", client=r)
    assert len(named) == 1
    assert named[0]["provider"] == "elevenlabs", "the acknowledgement dropped the caller's choice"
    assert workflows.status(named[0]["request_id"], client=r)["inputs"]["provider"] == "elevenlabs"

    # ...and a submission that named none still says none, rather than inventing a default
    plain = workflows.submit_lanes(contracts.VISIO_TO_ARCHIMATE.name,
                                   {"diagram": "art://d/x.vsdx"}, "cli", client=r)
    assert plain[0]["provider"] == ""
