"""transcript_to_minutes — keeping a voice, only on the consent tick, after a person answered.

What is pinned: no tick, no call (the speech service is not even asked); with a tick, the organiser is
recorded as whoever attested consent; and a failure to keep a voice never costs the minutes.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/transcript_to_minutes/test_keep_voices.py"""
from lab.platform.contracts import SpeechTools

from .test_workflow import MAP, _run, gw  # noqa: F401 - gw is a fixture

AUDIO = "art://r1/Meeting Recording.mp4"
TICKED = MAP | {"SPEAKER_01": {"tag": "the vendor's architect", "consent": "yes"}}


def test_without_a_consent_tick_the_speech_service_is_never_asked(gw):  # noqa: F811
    out = _run(audio=AUDIO)
    assert gw.args_for(SpeechTools.enrol) == []
    assert out["voiceprints"]["reason"] == "no speaker was ticked for consent"


def test_a_ticked_voice_is_sent_to_be_kept_with_the_organiser_as_who_attested_consent(gw):  # noqa: F811
    gw.answers[SpeechTools.enrol] = {"model": "ecapa", "enrolled": ["SPEAKER_01"], "skipped": {}}
    out = _run(audio=AUDIO, speaker_map=TICKED)
    (args,) = gw.args_for(SpeechTools.enrol)
    assert args["audio_ref"] == AUDIO and args["segments_ref"] == "art://t/x.json"
    assert args["consented_by"] == "maria@contoso.com"
    assert args["speaker_map"]["SPEAKER_01"]["consent"] == "yes"
    assert out["voiceprints"]["enrolled"] == ["SPEAKER_01"]


def test_without_the_recording_there_is_nothing_to_learn_from_and_it_says_so(gw):  # noqa: F811
    out = _run(speaker_map=TICKED)
    assert gw.args_for(SpeechTools.enrol) == [] and "no recording" in out["voiceprints"]["reason"]


def test_a_failure_to_keep_a_voice_never_costs_the_minutes(gw, monkeypatch):  # noqa: F811
    async def broken_for_enrol(headers, mcp_url, calls):
        if calls[0][0] == SpeechTools.enrol:
            raise RuntimeError("voiceprints is unavailable")
        return await type(gw).__call__(gw, headers, mcp_url, calls)
    from lab.workloads.transcript_to_minutes import workflow as W
    monkeypatch.setattr(W.gateway, "call_tools", broken_for_enrol)
    out = _run(audio=AUDIO, speaker_map=TICKED)
    assert out["minutes_ref"] and "unavailable" in out["voiceprints"]["reason"]
