"""The three bake-off ADAPTERS, driven through their injected transport — offline, no socket.

What these pin is the WIRE CONTRACT, because that is what a live call fails on and what a mapper
test cannot see: the auth header each provider wants, the paths, and — for the two asynchronous
ones — that a submit is followed by polling and that the tokens come from wherever that provider
actually keeps them.
"""
import pytest

from lab.core.speech import AudioClip, SpeechError, SpeechNotConfigured, SpeechUnsupportedMedia
from lab.substrate.mcp.speech import assembly_repository as AR
from lab.substrate.mcp.speech import eleven_repository as ER
from lab.substrate.mcp.speech import soniox_repository as SR
from lab.substrate.mcp.speech.http import Response

CLIP = AudioClip("meeting.mp3", b"audio-bytes")


class Recorder:
    """A transport that answers from a script and remembers every call."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.answers.pop(0) if self.answers else Response(200, {}, {})


def ok(body):
    return Response(200, {}, body)


# ------------------------------------------------------------------ ElevenLabs
def test_eleven_posts_the_clip_with_its_own_key_header_and_returns_a_transcript():
    t = Recorder([ok({"language_code": "en", "text": "hello",
                      "words": [{"text": "hello", "start": 0.0, "end": 0.5, "type": "word",
                                 "speaker_id": "speaker_0"}]})])
    got = ER.build(api_key="k", transport=t).transcribe(CLIP, languages=("ar", "en"))
    assert got.text == "hello" and got.provider == "elevenlabs"
    call = t.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/v1/speech-to-text")
    assert call["headers"]["xi-api-key"] == "k" and "Authorization" not in call["headers"]
    assert b'name="model_id"' in call["body"] and b"scribe_v2" in call["body"]
    assert b'name="diarize"' in call["body"] and b'name="file"' in call["body"]


def test_eleven_without_a_key_refuses_before_any_call():
    t = Recorder([])
    with pytest.raises(SpeechNotConfigured):
        ER.build(api_key="", transport=t).transcribe(CLIP)
    assert t.calls == []


def test_eleven_refuses_a_video_container_it_cannot_take_without_uploading_it():
    t = Recorder([])
    with pytest.raises(SpeechUnsupportedMedia):
        ER.build(api_key="k", transport=t).transcribe(AudioClip("meeting.vsdx", b"x"))
    assert t.calls == []


def test_eleven_turns_a_refused_credential_into_a_sentence_naming_its_setting():
    t = Recorder([Response(401, {}, {"detail": {"message": "invalid api key"}})])
    with pytest.raises(SpeechError, match="ELEVENLABS_API_KEY"):
        ER.build(api_key="k", transport=t).transcribe(CLIP)


# ------------------------------------------------------------------ AssemblyAI
def test_assembly_uploads_then_submits_then_polls_to_completion():
    t = Recorder([ok({"upload_url": "https://cdn/x"}),
                  ok({"id": "job1", "status": "queued"}),
                  ok({"id": "job1", "status": "processing"}),
                  ok({"id": "job1", "status": "completed", "audio_duration": 3,
                      "utterances": [{"start": 0, "end": 900, "text": "hello", "speaker": "A"}]})])
    got = AR.build(api_key="k", transport=t, sleep=lambda _s: None).transcribe(CLIP)
    assert got.text == "hello" and got.segments[0].end == 0.9
    assert [c["url"].rsplit("/", 1)[-1] for c in t.calls] == ["upload", "transcript", "job1", "job1"]
    assert t.calls[0]["headers"]["authorization"] == "k"      # raw key, NOT "Bearer k"
    assert t.calls[0]["body"] == b"audio-bytes"               # raw bytes, not multipart


def test_assembly_raises_the_providers_error_status_rather_than_an_empty_transcript():
    t = Recorder([ok({"upload_url": "https://cdn/x"}), ok({"id": "j", "status": "queued"}),
                  ok({"id": "j", "status": "error", "error": "corrupt audio"})])
    with pytest.raises(SpeechError, match="corrupt audio"):
        AR.build(api_key="k", transport=t, sleep=lambda _s: None).transcribe(CLIP)


def test_assembly_says_plainly_that_it_detects_one_dominant_language():
    """The caller asked for two; this provider will pick one. Silence there is how a lab concludes
    a meeting was monolingual when the provider simply never looked for the second language."""
    w = AR.build(api_key="k", transport=Recorder([])).warnings(languages=("ar", "en"))
    assert w and "ONE dominant language" in w[0]


# ------------------------------------------------------------------ Soniox
def test_soniox_uploads_creates_polls_and_then_fetches_the_tokens_from_their_own_endpoint():
    t = Recorder([ok({"id": "f1"}), ok({"id": "t1", "status": "pending"}),
                  ok({"id": "t1", "status": "completed"}),
                  ok({"tokens": [{"text": "hello", "start_ms": 0, "end_ms": 500, "speaker": "1",
                                  "language": "en"}]})])
    got = SR.build(api_key="k", transport=t, sleep=lambda _s: None).transcribe(
        CLIP, languages=("ar", "en"))
    assert got.text == "hello" and got.provider == "soniox-original"
    assert t.calls[0]["headers"]["Authorization"] == "Bearer k"
    assert t.calls[-1]["url"].endswith("/v1/transcriptions/t1/transcript")


def test_soniox_english_half_asks_for_the_translation_and_returns_only_it():
    t = Recorder([ok({"id": "f1"}), ok({"id": "t1", "status": "completed"}),
                  ok({"id": "t1", "status": "completed"}),
                  ok({"tokens": [
                      {"text": "ان شاء الله", "start_ms": 0, "end_ms": 500, "speaker": "1"},
                      {"text": "God willing", "start_ms": 0, "end_ms": 500, "speaker": "1",
                       "translation_status": "translation"}]})])
    box = SR.build(api_key="k", transport=t, want="translation", translate_to="en",
                   sleep=lambda _s: None)
    got = box.transcribe(CLIP, languages=("ar", "en"))
    assert got.text == "God willing" and got.provider == "soniox-translation"
    import json
    submitted = json.loads(t.calls[1]["body"])
    assert submitted["translation"] == {"type": "one_way", "target_language": "en"}
    assert submitted["enable_speaker_diarization"] is True
    assert submitted["language_hints"] == ["ar", "en"]


def test_soniox_translation_half_warns_that_it_is_not_what_was_said():
    """A translated transcript that does not SAY it is translated is the worst artifact here: it
    reads like a verbatim record and would be filed as one."""
    w = SR.build(api_key="k", transport=Recorder([]), want="translation",
                 translate_to="en").warnings()
    assert w and "TRANSLATION" in w[0]


def test_soniox_refuses_to_be_built_asking_for_a_translation_with_no_target():
    with pytest.raises(SpeechError):
        SR.build(api_key="k", transport=Recorder([]), want="translation", translate_to="")
