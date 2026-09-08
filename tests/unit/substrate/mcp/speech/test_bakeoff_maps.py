"""The three bake-off provider MAPPERS, each pinned to its own documented response shape.

A mapper is where correctness lives, so each is tested apart from any transport. The payloads below
follow each provider's published schema: ElevenLabs returns a flat word stream with `speaker_id` and
SECONDS; AssemblyAI returns `utterances` in MILLISECONDS with single-letter speakers; Soniox returns
ONE token stream carrying original and translated tokens together, told apart by `translation_status`.
"""
import pytest

from lab.core.speech import SpeechError
from lab.substrate.mcp.speech import assembly_map as A
from lab.substrate.mcp.speech import eleven_map as E
from lab.substrate.mcp.speech import soniox_map as S


# ------------------------------------------------------------------ ElevenLabs
ELEVEN = {
    "language_code": "en", "language_probability": 0.98,
    "text": "hello there action items",
    "words": [
        {"text": "hello", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
        {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing", "speaker_id": "speaker_0"},
        {"text": "there", "start": 0.5, "end": 0.9, "type": "word", "speaker_id": "speaker_0"},
        {"text": "(laughter)", "start": 0.9, "end": 1.1, "type": "audio_event"},
        {"text": "action", "start": 1.2, "end": 1.6, "type": "word", "speaker_id": "speaker_1"},
        {"text": "items", "start": 1.6, "end": 2.0, "type": "word", "speaker_id": "speaker_1"},
    ],
}


def test_eleven_groups_the_word_stream_into_speaker_turns():
    t = E.to_transcript(ELEVEN)
    assert [(s.speaker, s.text) for s in t.segments] == [
        ("speaker_0", "hello there"), ("speaker_1", "action items")]
    assert t.segments[0].start == 0.0 and t.segments[0].end == 0.9
    assert t.provider == "elevenlabs" and t.duration == 2.0


def test_eleven_drops_spacing_and_audio_events_because_neither_is_speech():
    t = E.to_transcript(ELEVEN)
    assert "laughter" not in t.text and "  " not in t.text


def test_eleven_does_not_stamp_the_whole_file_language_onto_every_segment():
    """It detects ONE language for the file. Copying that down would assert every segment was that
    language and make `code_switched` read False for a meeting that switched throughout."""
    t = E.to_transcript(ELEVEN)
    assert all(s.language == "" for s in t.segments)
    assert t.languages == () and t.code_switched is False


def test_eleven_sends_a_single_language_code_only_when_exactly_one_is_expected():
    assert E.form_fields(("ar",))["language_code"] == "ar"
    assert "language_code" not in E.form_fields(("ar", "en"))     # plural hint means DETECT
    assert "language_code" not in E.form_fields(())


def test_eleven_caps_the_speaker_hint_at_what_the_provider_accepts():
    assert E.form_fields((), speaker_count=99)["num_speakers"] == "32"


def test_eleven_refuses_a_response_that_is_not_an_object():
    with pytest.raises(SpeechError):
        E.to_transcript(["nope"])


# ------------------------------------------------------------------ AssemblyAI
ASSEMBLY = {
    "status": "completed", "language_code": "ar", "audio_duration": 12,
    "utterances": [
        {"start": 0, "end": 900, "text": "hello there", "speaker": "A", "confidence": 0.9},
        {"start": 1200, "end": 2000, "text": "action items", "speaker": "B", "confidence": 0.9},
        {"start": 2100, "end": 2200, "text": "   ", "speaker": "B"},
    ],
}


def test_assembly_converts_milliseconds_to_seconds():
    """The failure this catches is silent: a timeline a thousand times too long still reads fine."""
    t = A.to_transcript(ASSEMBLY)
    assert t.segments[0].start == 0.0 and t.segments[0].end == 0.9
    assert t.segments[1].start == 1.2 and t.segments[1].end == 2.0


def test_assembly_renames_letter_speakers_to_the_ports_anonymous_form():
    t = A.to_transcript(ASSEMBLY)
    assert [s.speaker for s in t.segments] == ["SPEAKER_00", "SPEAKER_01"]


def test_assembly_drops_a_wordless_utterance():
    assert len(A.to_transcript(ASSEMBLY).segments) == 2


def test_assembly_falls_back_to_words_when_diarization_was_not_requested():
    t = A.to_transcript({"status": "completed", "words": [
        {"text": "hello", "start": 0, "end": 500, "speaker": None},
        {"text": "there", "start": 500, "end": 900, "speaker": None}]})
    assert len(t.segments) == 1 and t.segments[0].text == "hello there"


def test_assembly_raises_the_providers_own_error_rather_than_returning_an_empty_transcript():
    with pytest.raises(SpeechError, match="bad audio"):
        A.to_transcript({"status": "error", "error": "bad audio"})


def test_assembly_asks_for_detection_unless_exactly_one_language_is_expected():
    assert A.request_body("u", ("ar",))["language_code"] == "ar"
    assert A.request_body("u", ("ar", "en"))["language_detection"] is True


# ------------------------------------------------------------------ Soniox
SONIOX = {
    "tokens": [
        {"text": "action", "start_ms": 0, "end_ms": 400, "speaker": "1", "language": "en"},
        {"text": "items", "start_ms": 400, "end_ms": 800, "speaker": "1", "language": "en"},
        {"text": "ان شاء الله", "start_ms": 800, "end_ms": 1200, "speaker": "1", "language": "ar"},
        {"text": "God willing", "start_ms": 800, "end_ms": 1200, "speaker": "1", "language": "en",
         "translation_status": "translation"},
        {"text": "yes", "start_ms": 1300, "end_ms": 1600, "speaker": "2", "language": "en"},
    ],
}


def test_soniox_original_keeps_what_was_actually_said():
    t = S.to_transcript(SONIOX, want=S.ORIGINAL)
    assert t.text == "action items ان شاء الله yes"
    assert t.provider == "soniox-original"


def test_soniox_translation_keeps_only_the_rendering():
    t = S.to_transcript(SONIOX, want=S.TRANSLATION)
    assert t.text == "God willing" and t.provider == "soniox-translation"


def test_soniox_splits_a_speakers_turn_at_the_language_switch():
    """The whole point of this provider for this lab: the switch must stay visible, not be merged."""
    t = S.to_transcript(SONIOX, want=S.ORIGINAL)
    assert [(s.speaker, s.language) for s in t.segments] == [
        ("SPEAKER_01", "en"), ("SPEAKER_01", "ar"), ("SPEAKER_02", "en")]
    assert t.code_switched is True


def test_soniox_converts_milliseconds_and_normalises_numeric_speakers():
    t = S.to_transcript(SONIOX, want=S.ORIGINAL)
    assert t.segments[0].start == 0.0 and t.segments[0].end == 0.8
    assert t.segments[0].speaker == "SPEAKER_01"


def test_soniox_asks_for_both_languages_and_english_translation_in_one_request():
    body = S.request_body(file_id="f1", languages=("ar", "en"), translate_to="en")
    assert body["language_hints"] == ["ar", "en"]        # the plural hint the port promises
    assert body["enable_speaker_diarization"] is True
    assert body["translation"] == {"type": "one_way", "target_language": "en"}
    assert body["file_id"] == "f1" and "audio_url" not in body


def test_soniox_refuses_both_a_file_and_a_url_because_they_are_mutually_exclusive():
    with pytest.raises(SpeechError):
        S.request_body(file_id="f1", audio_url="https://x/y.mp3")
    with pytest.raises(SpeechError):
        S.request_body()
