"""meeting_to_transcript — voiceprint SUGGESTIONS on the speaker question.

The rule pinned here: a recognised voice arrives pre-filled for the organiser to confirm, an
unrecognised one arrives exactly as before, and a missing or broken voiceprint service changes nothing
at all — the question still goes out.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/meeting_to_transcript/test_voiceprints.py"""
from lab.platform.contracts import ApprovalTools, SpeechTools, continuation_of
from lab.workloads.meeting_to_transcript import workflow as W

from .test_workflow import FETCHED, TRANSCRIBED, _run, gw  # noqa: F401 - gw is a fixture

IDENTIFIED = {"model": "ecapa", "speakers": [
    {"label": "SPEAKER_00", "seconds": 60.0, "suggestion": {"tag": "Nabeel", "display": "Nabeel", "score": 0.52}},
    {"label": "SPEAKER_01", "seconds": 30.0, "suggestion": {}},
    {"label": "SPEAKER_02", "seconds": 4.0, "suggestion": {}}]}


def items(gw):  # noqa: F811
    return {i["label"]: i for i in gw.args_for(ApprovalTools.ask)["items"]}


def test_a_recognised_voice_is_pre_filled_and_the_rest_are_asked_as_before(gw, monkeypatch):  # noqa: F811
    monkeypatch.setitem(gw.answers, SpeechTools.identify, IDENTIFIED)
    _run()
    got = items(gw)
    assert got["SPEAKER_00"]["suggestion"]["tag"] == "Nabeel"
    assert "suggestion" not in got["SPEAKER_01"] and "suggestion" not in got["SPEAKER_02"]


def test_identify_is_asked_by_reference_for_this_recording_and_its_transcript(gw, monkeypatch):  # noqa: F811
    monkeypatch.setitem(gw.answers, SpeechTools.identify, IDENTIFIED)
    _run()
    assert gw.args_for(SpeechTools.identify) == {"audio_ref": FETCHED["ref"],
                                                  "segments_ref": TRANSCRIBED["transcript_ref"]}


def test_a_broken_voiceprint_service_still_asks_the_question(gw, monkeypatch):  # noqa: F811
    monkeypatch.setitem(gw.answers, SpeechTools.identify, RuntimeError("voiceprints is unavailable"))
    out = _run()
    assert out["approval_id"] and all("suggestion" not in i for i in items(gw).values())


def test_identify_is_a_convenience_never_a_precondition():
    """Not in REQUIRED_TOOLS: a deployment without the grant degrades to no suggestions instead of
    being refused by preflight."""
    assert SpeechTools.identify not in W.REQUIRED_TOOLS


def test_the_prompt_tells_the_organiser_to_check_a_suggestion_and_what_consent_means(gw):  # noqa: F811
    _run()
    prompt = gw.args_for(ApprovalTools.ask)["prompt"]
    assert "check it" in prompt and "consent" in prompt.lower()


def test_approving_releases_the_recording_so_a_consented_voice_can_be_kept(gw):  # noqa: F811
    _run()
    cont = continuation_of({"continuation": gw.args_for(ApprovalTools.ask)["continuation"]})
    assert cont.inputs["audio"] == FETCHED["ref"]
