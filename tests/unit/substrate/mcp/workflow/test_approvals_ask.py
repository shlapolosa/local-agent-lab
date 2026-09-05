"""`approvals_ask` — the missing primitive, and the `answer` parameter on `approvals_decide`.

Why this tool has to exist: a workload cannot raise an approval today. `approvals.request()` is
called PRIVATELY inside the EA staging tool, and the tier rule forbids a workload from importing the
substrate at all — so the only reason `visio_to_archimate` ever gets an approval is that the EA port
happens to raise one as a side effect of staging. A process whose whole purpose is to ask a person a
question has no way to do it. This is the primitive that closes that, over the gateway, granted and
metered like anything else.

THREE GRANTS, NOT TWO. `READ` shows a human what is waiting. `RAISE` asks. `WRITE` answers. A
workload gets RAISE and never WRITE — it may ask a question, never answer its own.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/workflow/test_approvals_ask.py
"""
import asyncio

import pytest
from fastmcp import Client

from fixtures.fakes import FakeRedis
from lab.platform.contracts import ApprovalKind, ApprovalTools, Continuation, speaker_prompts
from lab.substrate.mcp.workflow import server as srv


class Unreachable:
    """A store that fails on ANY use — the approval tools must never touch an object store."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"workflow-mcp must hold no store: {name} was used")


@pytest.fixture
def tools():
    r = FakeRedis()
    with srv.server.container.redis.override(r), \
         srv.server.container.artifacts.override(Unreachable()), \
         srv.server.container.uploads.override(Unreachable()):
        yield srv.server, r


def call(server, _tool, **args):
    async def go():
        async with Client(server.mcp) as c:
            return (await c.call_tool(_tool, args)).data
    return asyncio.run(go())


def call_error(server, _tool, **args) -> str:
    async def go():
        async with Client(server.mcp) as c:
            r = await c.call_tool(_tool, args, raise_on_error=False)
            assert r.is_error, f"{_tool} should have failed"
            return r.content[0].text
    return asyncio.run(go())


# ------------------------------------------------------------------ the grant split
def test_asking_is_its_own_grant_separate_from_answering():
    assert ApprovalTools.ask in ApprovalTools.RAISE
    assert ApprovalTools.ask not in ApprovalTools.WRITE and ApprovalTools.ask not in ApprovalTools.READ
    assert set(ApprovalTools.READ) | set(ApprovalTools.RAISE) | set(ApprovalTools.WRITE) \
        == ApprovalTools.names()


def test_the_three_grants_are_disjoint():
    """Overlap would make a per-tool ACL meaningless — granting one would quietly grant another."""
    read, raise_, write = map(set, (ApprovalTools.READ, ApprovalTools.RAISE, ApprovalTools.WRITE))
    assert read & raise_ == read & write == raise_ & write == set()


# ------------------------------------------------------------------ asking
def test_asking_publishes_a_question_and_writes_nothing_else(tools):
    server, r = tools
    out = call(server, "approvals_ask", subject="weekly sync",
               prompt="Who is each speaker?",
               items=[{"label": "SPEAKER_00", "seconds": 40.0, "turns": 6,
                       "samples": ["we retire the legacy portal"]},
                      {"label": "SPEAKER_01", "seconds": 5.0, "turns": 2}],
               requester="wf-meeting")
    assert out["request_id"].startswith("apr-") and out["status"] == "pending"
    assert out["review_app"] and out["asked"] == 2

    from lab.substrate import approvals
    st = approvals.status(out["request_id"], client=r)
    assert st["kind"] == ApprovalKind.SPEAKER_MAPPING.value and st["requester"] == "wf-meeting"
    prompts = speaker_prompts(st["payload"])
    assert [p.label for p in prompts] == ["SPEAKER_00", "SPEAKER_01"]
    assert prompts[0].samples == ("we retire the legacy portal",)
    # the completeness contract the gate will enforce is DECLARED by the asker
    assert st["payload"]["answer_labels"] == ["SPEAKER_00", "SPEAKER_01"]
    assert st["payload"]["answer_required"] is True


def test_asking_nothing_is_refused(tools):
    server, _ = tools
    assert "at least one" in call_error(server, "approvals_ask", subject="s", prompt="p", items=[]).lower()


def test_duplicate_labels_are_refused_because_the_answer_is_keyed_on_them(tools):
    server, _ = tools
    msg = call_error(server, "approvals_ask", subject="s", prompt="p",
                     items=[{"label": "SPEAKER_00"}, {"label": "SPEAKER_00"}])
    assert "SPEAKER_00" in msg


def test_a_continuation_is_validated_when_it_is_asked_not_when_it_is_approved(tools):
    """A typo here would otherwise surface hours later, as a human approving and nothing happening."""
    server, _ = tools
    msg = call_error(server, "approvals_ask", subject="s", prompt="p",
                     items=[{"label": "SPEAKER_00"}],
                     continuation={"process": "no_such_process", "inputs": {}})
    assert "no_such_process" in msg


def test_a_valid_continuation_is_stored_for_whatever_acts_on_the_decision(tools):
    server, r = tools
    cont = Continuation(process="visio_to_archimate", inputs={"diagram": "art://a/b.vsdx"})
    out = call(server, "approvals_ask", subject="s", prompt="p", items=[{"label": "SPEAKER_00"}],
               continuation=cont.to_dict())
    from lab.platform.contracts import continuation_of
    from lab.substrate import approvals
    assert continuation_of(approvals.status(out["request_id"], client=r)["payload"]) == cont


def test_the_asker_cannot_answer_its_own_question(tools):
    """The whole control. Asking must never imply the ability to answer."""
    server, r = tools
    out = call(server, "approvals_ask", subject="s", prompt="p", items=[{"label": "SPEAKER_00"}])
    from lab.substrate import approvals
    assert approvals.status(out["request_id"], client=r)["status"] == "pending"


# ------------------------------------------------------------------ answering
def test_a_human_answer_reaches_the_request_through_the_decide_tool(tools):
    server, r = tools
    out = call(server, "approvals_ask", subject="s", prompt="p",
               items=[{"label": "SPEAKER_00"}, {"label": "SPEAKER_01"}])
    call(server, "approvals_decide", request_id=out["request_id"], decision="approve",
         actor="maria@contoso.com", channel="teams",
         answer={"SPEAKER_00": {"identity": "maria@contoso.com"}, "SPEAKER_01": {"tag": "guest"}})
    from lab.substrate import approvals
    st = approvals.status(out["request_id"], client=r)
    assert st["status"] == "approve" and st["answer"]["SPEAKER_01"] == {"tag": "guest"}
    assert st["decided_via"] == "mcp:teams", "a relay is never logged as the review app"


def test_an_incomplete_answer_is_refused_with_the_missing_label_named(tools):
    server, _ = tools
    out = call(server, "approvals_ask", subject="s", prompt="p",
               items=[{"label": "SPEAKER_00"}, {"label": "SPEAKER_01"}])
    msg = call_error(server, "approvals_decide", request_id=out["request_id"], decision="approve",
                     actor="maria@contoso.com", answer={"SPEAKER_00": {"tag": "x"}})
    assert "SPEAKER_01" in msg


def test_reading_an_approval_shows_the_question_a_low_code_flow_must_render(tools):
    """The question comes back FLAT, because the intended long-term surface is an adaptive card
    templated by a low-code flow, not our own renderer."""
    server, _ = tools
    out = call(server, "approvals_ask", subject="s", prompt="Who is each speaker?",
               items=[{"label": "SPEAKER_00", "seconds": 9.0}])
    got = call(server, "approvals_get", request_id=out["request_id"])
    assert got["question"]["prompt"] == "Who is each speaker?"
    assert got["question"]["items"][0]["label"] == "SPEAKER_00"
    assert got["answer_required"] is True


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


def test_artifacts_cannot_overwrite_the_fields_that_carry_the_approvals_meaning(tools):
    """`payload |= artifacts` resolves collisions in favour of artifacts, so without a guard an asker
    could pass `answer_labels: []` and make its OWN question approvable with no answer at all —
    `check_answer` drives completeness purely from that field. The reserved names are the same tuple
    the read side uses to decide what is not an artifact, so one list governs both ends."""
    server, r = tools
    for reserved in ("answer_labels", "answer_required", "question", "continuation",
                     "summary", "import_artifacts", "instructions"):
        msg = call_error(server, "approvals_ask", subject="s", prompt="p",
                         items=[{"label": "SPEAKER_00"}], artifacts={reserved: []})
        assert reserved in msg, msg
    from lab.substrate import approvals
    assert approvals.pending(client=r) == [], "nothing was published for any refused call"


def test_an_ordinary_artifact_still_rides_along(tools):
    """The guard must refuse only the reserved names — carrying refs a reviewer can open is the
    entire point of the field."""
    server, r = tools
    out = call(server, "approvals_ask", subject="s", prompt="p",
               items=[{"label": "SPEAKER_00"}],
               artifacts={"recording": "art://r/rec.mp4", "transcript": "art://t/x.json"})
    from lab.substrate import approvals
    payload = approvals.status(out["request_id"], client=r)["payload"]
    assert payload["recording"] == "art://r/rec.mp4" and payload["transcript"] == "art://t/x.json"
    assert payload["answer_labels"] == ["SPEAKER_00"], "and the approval's own fields are intact"


def test_candidates_ride_along_on_the_question_when_the_asker_knows_them(tools):
    server, r = tools
    out = call(server, "approvals_ask", subject="s", prompt="p", items=[{"label": "SPEAKER_00"}],
               candidates=[{"identity": "sam@contoso.com", "display": "Sam"},
                           {"identity": "SAM@contoso.com"},        # deduped by the typed reader
                           {"display": "unusable"}])               # dropped, not fatal
    from lab.substrate import approvals
    from lab.platform.contracts import speaker_candidates
    payload = approvals.status(out["request_id"], client=r)["payload"]
    assert [c.identity for c in speaker_candidates(payload)] == ["sam@contoso.com"]


def test_asking_without_candidates_is_unchanged(tools):
    """Every existing caller omits them, and the question must behave exactly as before."""
    server, r = tools
    out = call(server, "approvals_ask", subject="s", prompt="p", items=[{"label": "SPEAKER_00"}])
    from lab.substrate import approvals
    from lab.platform.contracts import speaker_candidates
    payload = approvals.status(out["request_id"], client=r)["payload"]
    assert speaker_candidates(payload) == []
    assert payload["answer_labels"] == ["SPEAKER_00"]
