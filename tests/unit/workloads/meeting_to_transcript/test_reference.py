"""meeting_to_transcript — the tenant's own transcript of THIS occurrence, kept as the yardstick.

A recurring meeting keeps one id and accumulates one transcript per occurrence (measured 29 Sep 2026:
the 28th's and the 29th's under one id), so the right one is chosen by time. A wrong pick would score
every lane against a different meeting, which reads exactly like a bad provider.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/meeting_to_transcript/test_reference.py"""
from lab.platform.contracts import ApprovalTools, CollabTools, continuation_of
from lab.workloads.meeting_to_transcript import workflow as W

from .test_workflow import _run, gw  # noqa: F401 - gw is a fixture

YESTERDAY = {"handle": "collab://transcript/m/T28", "created": "2026-09-28T08:29:39Z"}
TODAY = {"handle": "collab://transcript/m/T29", "created": "2026-09-29T07:22:00Z"}


def test_the_transcript_of_the_same_occurrence_is_chosen_by_time():
    assert W._occurrence_transcript([YESTERDAY, TODAY], "2026-09-29T07:24:10Z") is TODAY
    assert W._occurrence_transcript([YESTERDAY, TODAY], "2026-09-28T08:30:00Z") is YESTERDAY


def test_nothing_is_chosen_when_no_transcript_is_near_this_recording():
    assert W._occurrence_transcript([YESTERDAY], "2026-09-30T09:00:00Z") is None


def test_without_a_recording_time_only_an_unambiguous_single_transcript_is_taken():
    assert W._occurrence_transcript([TODAY], "") is TODAY
    assert W._occurrence_transcript([YESTERDAY, TODAY], "") is None


def test_the_reference_is_fetched_and_carried_to_the_minutes_run(gw, monkeypatch):  # noqa: F811
    async def owning(cfg, state):
        return {"id": "m", "chat_id": "", "participants": [], "recorded_at": "2026-09-29T07:24:10Z"}
    monkeypatch.setattr(W, "_owning_meeting", owning)
    monkeypatch.setitem(gw.answers, CollabTools.transcripts, {"items": [YESTERDAY, TODAY]})
    real_fetch = gw.answers[CollabTools.fetch]

    async def route(headers, mcp_url, calls):
        out = []
        for tool, args in calls:
            gw.calls.append((tool, args))
            if tool == CollabTools.fetch and args["handle"].startswith("collab://transcript/"):
                out.append({"ref": "art://v/teams.vtt"})
            elif tool == CollabTools.fetch:
                out.append(real_fetch)
            else:
                a = gw.answers[tool]
                if isinstance(a, Exception):
                    raise a
                out.append(a)
        return out
    monkeypatch.setattr(W.gateway, "call_tools", route)
    _run()
    assert gw.args_for(CollabTools.transcripts) == {"meeting_id": "m"}
    cont = continuation_of({"continuation": gw.args_for(ApprovalTools.ask)["continuation"]})
    assert cont.inputs["reference"] == "art://v/teams.vtt"


def test_no_tenant_transcript_still_asks_the_question(gw):  # noqa: F811
    """No meeting resolves in the default harness — the reference is a yardstick, never a precondition."""
    out = _run()
    cont = continuation_of({"continuation": gw.args_for(ApprovalTools.ask)["continuation"]})
    assert out["approval_id"] and not cont.inputs.get("reference")
    assert CollabTools.transcripts not in W.REQUIRED_TOOLS
