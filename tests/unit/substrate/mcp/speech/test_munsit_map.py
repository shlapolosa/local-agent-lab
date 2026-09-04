"""The MAPPER — provider payload -> `lab.core.speech` objects. Tested ALONE, apart from any
transport, because CLAUDE.md puts correctness here: a domain adapter needs a mapper between the
external model and ours, and that mapper is where a wrong answer would be born.

Every fixture below is the SHAPE OF A REAL RESPONSE, taken from a live call made 4 Sep 2026, not
from documentation. Two facts about this provider are pinned here because they change the design:
it reports NO per-segment language even when running its code-switching model, and it returns
segments with empty text.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/speech/test_munsit_map.py
"""
import pytest

from lab.core import speech
from lab.substrate.mcp.speech import munsit_map as M

# The live response, trimmed. `merged` is the only part we map; the rest is provider bookkeeping.
LIVE = {
    "statusCode": 200, "message": "Success",
    "data": {
        "transcriptionId": "b1f0-…", "transcription": "this is a voice recording",
        "originalTranscript": "this is a voice recording", "attributes": {},
        "diarization": {"segments": [{"start": 7.844094, "end": 10.780344, "speaker": "SPEAKER_00"}]},
        "merged": [
            {"start": 7.844094, "end": 10.780344, "speaker": "SPEAKER_00", "text": "this is a voice recording"},
            {"start": 19.116594, "end": 19.977219, "speaker": "SPEAKER_00", "text": ""},
            {"start": 23.132844, "end": 25.512219, "speaker": "SPEAKER_00", "text": ""},
        ],
        "duration": 26.94, "audioUrl": "https://…",
        "stats": {"fileName": "meeting.m4a", "fileSize": "0.04 MB", "mimeType": "audio/x-m4a",
                  "creditsConsumed": 44},
    },
}


def test_maps_a_real_response_to_a_transcript():
    t = M.to_transcript(LIVE, model="munsit-en-ar")
    assert isinstance(t, speech.Transcript)
    assert t.duration == pytest.approx(26.94)
    assert t.model == "munsit-en-ar" and t.provider
    assert len(t.segments) == 3 and t.labels == ("SPEAKER_00",)
    assert t.text == "this is a voice recording"


def test_this_provider_reports_no_per_segment_language_and_we_do_not_invent_one():
    """The port wants the language RECOGNISED per segment so a mistranslated span is visible. This
    provider does not report one, even on its code-switching model. The mapper must leave it EMPTY
    rather than stamp in the requested language, which would manufacture false evidence of a switch
    and defeat the one check the port exists to provide."""
    t = M.to_transcript(LIVE, model="munsit-en-ar")
    assert all(s.language == "" for s in t.segments)
    assert t.languages == () and t.code_switched is False


def test_empty_text_segments_are_kept_because_they_are_real_speaker_time():
    """A silent-but-attributed span is diarization evidence: it counts toward a speaker's share even
    though it contributes no words. Dropping it would understate how long someone spoke."""
    t = M.to_transcript(LIVE, model="munsit-en-ar")
    assert len(t.segments) == 3
    assert t.speakers[0].turns == 3
    assert t.samples_for("SPEAKER_00") == ("this is a voice recording",)   # but never quoted blank


def test_falls_back_to_the_diarization_segments_when_merged_is_absent():
    """`merged` is the convenient view; `diarization.segments` is the authoritative one. If a future
    response omits the former we still produce a usable, if wordless, transcript."""
    payload = {"data": {"diarization": LIVE["data"]["diarization"], "duration": 11.0}}
    t = M.to_transcript(payload, model="munsit")
    assert len(t.segments) == 1 and t.segments[0].speaker == "SPEAKER_00" and t.segments[0].text == ""


def test_segments_are_sorted_into_time_order():
    """A Transcript is a timeline and refuses to be built out of order, so the mapper must sort —
    the provider gives no ordering guarantee."""
    payload = {"data": {"duration": 10.0, "merged": [
        {"start": 5.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "second"},
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "first"}]}}
    t = M.to_transcript(payload, model="munsit")
    assert [s.text for s in t.segments] == ["first", "second"]
    assert t.labels == ("SPEAKER_00", "SPEAKER_01")


def test_a_missing_speaker_label_is_named_not_guessed():
    """An unlabelled segment means diarization did not happen. Inventing a label would hide that."""
    payload = {"data": {"duration": 5.0, "merged": [{"start": 0.0, "end": 1.0, "text": "hi"}]}}
    with pytest.raises(speech.SpeechError):
        M.to_transcript(payload, model="munsit")


def test_an_empty_result_is_a_transcript_with_no_segments_not_a_crash():
    t = M.to_transcript({"data": {"duration": 3.0, "merged": []}}, model="munsit")
    assert t.segments == () and t.duration == pytest.approx(3.0)


def test_a_body_that_is_not_a_result_at_all_is_a_typed_refusal():
    with pytest.raises(speech.SpeechError):
        M.to_transcript({"nonsense": True}, model="munsit")


def test_a_malformed_timing_degrades_to_zero_rather_than_killing_the_run():
    """A provider that sends null or a string where a number belongs must not lose the whole
    transcript. The segment survives with a zero timing, which is visibly wrong on the timeline
    rather than silently absent."""
    payload = {"data": {"duration": None, "merged": [
        {"start": "oops", "end": None, "speaker": "SPEAKER_00", "text": "hi"}]}}
    t = M.to_transcript(payload, model="munsit")
    assert t.duration == 0.0 and t.segments[0].start == 0.0 and t.segments[0].end == 0.0


# ------------------------------------------------------------------ request side
def test_the_code_switching_model_is_chosen_by_the_LANGUAGE_HINT_not_by_a_flag():
    """The port speaks languages, not model names. Asking for Arabic AND English is what selects the
    provider's mixed model; one language selects its default. This is the single mapping that makes
    requirement one work, so it is pinned."""
    assert M.model_for(("ar", "en")) == "munsit-en-ar"
    assert M.model_for(("en", "ar")) == "munsit-en-ar"
    assert M.model_for(("ar",)) == "munsit"
    assert M.model_for(()) == "munsit"


def test_an_unsupported_language_pair_is_refused_rather_than_silently_downgraded():
    """Asking for French and English against an Arabic engine must fail loudly. Silently running the
    Arabic model would return confident nonsense, which is the worst possible outcome."""
    with pytest.raises(speech.SpeechUnavailable):
        M.model_for(("fr", "en"))


def test_form_fields_carry_timestamps_because_they_default_off():
    f = M.form_fields(("ar", "en"), vocabulary=())
    assert f["model"] == "munsit-en-ar" and f["return_timestamps"] == "true"


def test_vocabulary_is_dropped_with_the_code_switching_model_and_the_caller_is_told():
    """The provider refuses custom vocabulary together with its mixed model. The adapter prefers
    switching — the driving requirement — and must report the loss rather than fail or pretend."""
    f = M.form_fields(("ar", "en"), vocabulary=("Malaffi", "Riayati"))
    assert "hotwords" not in f
    assert f is not None and M.vocabulary_dropped(("ar", "en"), ("Malaffi",)) is True
    assert M.vocabulary_dropped(("ar",), ("Malaffi",)) is False


def test_vocabulary_is_passed_through_on_the_monolingual_model():
    f = M.form_fields(("ar",), vocabulary=("Malaffi", "Riayati"))
    assert f["hotwords"] == "Malaffi,Riayati"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
