"""src/lab/core/speech — the SPEECH domain port: what the domain needs from a transcription
provider, in the domain's own words. Pure: no I/O, no provider name, no credential.

The two requirements this port exists to serve, and which these tests pin:
  1. INTRA-SENTENTIAL CODE-SWITCHING. A request carries the languages EXPECTED (a hint, plural),
     never one declared language, and every segment reports the language actually RECOGNISED — so a
     span of Arabic returned as fluent English is VISIBLE rather than silent. A contract carrying
     only text cannot express that failure, which is why it is modelled here.
  2. SPEAKER ALLOCATION for an in-person meeting. One device, many voices: the provider's labels are
     anonymous and a human maps them later, so the port's job is to carry the labels, the evidence a
     human needs to tell them apart, and an honest speaker digest.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/speech/test_speech.py
"""
import pytest

from lab.core import speech as S


# ----------------------------------------------------------------- AudioClip: the input
def test_audio_clip_exposes_its_container_so_it_can_be_refused_before_upload():
    """The real failure this prevents: a meeting recording is video, the provider takes audio only,
    and finding that out after uploading gigabytes is the expensive way to learn it."""
    assert S.AudioClip("Meeting Recording.MP4", b"x").suffix == ".mp4"
    assert S.AudioClip("meeting.m4a", b"x").suffix == ".m4a"
    assert S.AudioClip("no-extension", b"x").suffix == ""


def test_audio_clip_needs_a_name():
    with pytest.raises(ValueError):
        S.AudioClip("  ", b"x")


def test_unknown_length_is_zero_not_empty():
    """0 seconds means "the length was not reported", never "there is no audio"."""
    assert S.AudioClip("a.wav", b"x").seconds == 0.0


# ----------------------------------------------------------------- Segment: the atom
def test_segment_carries_the_recognised_language_not_just_text():
    """The whole point of the port: a segment says WHICH language it was recognised as."""
    seg = S.Segment(speaker="SPEAKER_00", start=0.0, end=2.5, text="نبدأ الـ sprint review", language="ar")
    assert seg.language == "ar" and seg.speaker == "SPEAKER_00"
    assert seg.duration == pytest.approx(2.5)


def test_segment_language_is_optional_because_not_every_provider_reports_it():
    seg = S.Segment(speaker="SPEAKER_01", start=1.0, end=2.0, text="hello")
    assert seg.language == ""


@pytest.mark.parametrize("start,end", [(2.0, 1.0), (-1.0, 5.0)])
def test_segment_refuses_impossible_timings(start, end):
    with pytest.raises(ValueError):
        S.Segment(speaker="SPEAKER_00", start=start, end=end, text="x")


def test_segment_requires_a_speaker_label():
    with pytest.raises(ValueError):
        S.Segment(speaker="  ", start=0.0, end=1.0, text="x")


# ----------------------------------------------------------------- Transcript: the result
def _t(*segs, **kw):
    return S.Transcript(segments=tuple(segs), duration=kw.pop("duration", 30.0), **kw)


SEGS = (S.Segment("SPEAKER_00", 0.0, 4.0, "we agreed to retire the legacy portal", "en"),
        S.Segment("SPEAKER_01", 4.0, 6.0, "طيب", "ar"),
        S.Segment("SPEAKER_00", 6.0, 12.0, "خلينا نعمل migration بعد الـ review", "ar"))


def test_labels_are_first_appearance_ordered():
    """A human reads the mapping form top to bottom; order must be the order they first spoke."""
    assert _t(*SEGS).labels == ("SPEAKER_00", "SPEAKER_01")


def test_speaker_digest_is_derived_not_supplied():
    """Seconds and turns are FACTS about the segments — a provider must not be trusted to restate them."""
    stats = {s.label: s for s in _t(*SEGS).speakers}
    assert stats["SPEAKER_00"].turns == 2 and stats["SPEAKER_00"].seconds == pytest.approx(10.0)
    assert stats["SPEAKER_01"].turns == 1 and stats["SPEAKER_01"].seconds == pytest.approx(2.0)


def test_languages_seen_exposes_that_a_switch_actually_happened():
    """Requirement 1's observable: if a mixed recording comes back single-language, this says so."""
    assert _t(*SEGS).languages == ("ar", "en")
    assert _t(*SEGS).code_switched is True
    only_en = _t(S.Segment("SPEAKER_00", 0.0, 1.0, "hi", "en"))
    assert only_en.code_switched is False


def test_code_switched_is_false_when_no_language_is_reported():
    """Absent language labels are NOT evidence of a switch — silence must not read as success."""
    assert _t(S.Segment("SPEAKER_00", 0.0, 1.0, "hi")).code_switched is False


def test_text_joins_segments_in_time_order():
    assert _t(*SEGS).text.startswith("we agreed") and _t(*SEGS).text.endswith("review")


def test_a_transcript_with_no_segments_is_legal_but_says_so():
    """Silence is a real answer; the workflow gate — not the port — decides it is unusable."""
    empty = _t()
    assert empty.segments == () and empty.labels == () and empty.speakers == () and empty.text == ""


def test_transcript_refuses_segments_out_of_time_order():
    with pytest.raises(ValueError):
        _t(S.Segment("SPEAKER_00", 5.0, 6.0, "b"), S.Segment("SPEAKER_00", 0.0, 1.0, "a"))


def test_samples_for_gives_a_human_what_they_need_to_recognise_a_speaker():
    """The mapping approval shows verbatim utterances, ranked by how long the turn LASTED.

    Not by text length: Arabic renders the same speech in far fewer characters, so ranking on length
    would prefer the English turns of a mixed recording. Here SPEAKER_00's Arabic turn is 6 s and
    their English one 4 s, but the English string is the LONGER of the two — so this test fails if
    anyone reintroduces length ranking.
    """
    t = _t(*SEGS)
    assert t.samples_for("SPEAKER_00", limit=1) == ("خلينا نعمل migration بعد الـ review",)
    assert t.samples_for("nobody") == ()


def test_samples_skip_blank_text_so_a_human_is_never_shown_an_empty_quote():
    t = _t(S.Segment("SPEAKER_00", 0.0, 9.0, "   "), S.Segment("SPEAKER_00", 9.0, 10.0, "real"))
    assert t.samples_for("SPEAKER_00") == ("real",)


# ----------------------------------------------------------------- typed refusals
def test_every_refusal_renders_one_sentence_and_a_dict():
    e = S.SpeechUnavailable("diarization", "the plan does not include speaker separation",
                            "upgrade the plan or use a provider that separates speakers")
    assert e.sentence.endswith(".") and "Remedy:" in e.sentence
    assert e.to_dict()["capability"] == "diarization"


def test_not_configured_is_a_kind_of_unavailable_so_one_renderer_handles_both():
    e = S.SpeechNotConfigured("SPEECH_API_KEY")
    assert isinstance(e, S.SpeechUnavailable) and "SPEECH_API_KEY" in e.sentence


def test_unsupported_media_names_what_was_given_and_what_is_allowed():
    """The real failure we hit: a meeting recording is video and the provider takes audio only."""
    e = S.SpeechUnsupportedMedia(".mp4", (".m4a", ".wav"))
    assert ".mp4" in e.sentence and ".m4a" in e.sentence
    assert isinstance(e, S.SpeechError)


def test_too_long_names_the_cap_because_chunking_is_the_caller_s_problem():
    e = S.SpeechTooLong(5400.0, 3600.0)
    assert "5400" in e.sentence or "90" in e.sentence
    assert isinstance(e, S.SpeechError)


def test_the_base_error_still_renders_a_sentence_and_a_dict():
    """A bare SpeechError is what an adapter raises for something it cannot classify; it must still
    render like every other refusal rather than degrade to a bare traceback."""
    e = S.SpeechError("the provider returned an empty body")
    assert e.sentence == "the provider returned an empty body"
    assert e.to_dict() == {"capability": "", "sentence": "the provider returned an empty body"}


def test_an_unavailable_capability_must_name_the_capability():
    """An unnamed refusal cannot be rendered in a capability table, so it is refused at construction."""
    with pytest.raises(ValueError):
        S.SpeechUnavailable("  ", "because")


def test_unsupported_media_dict_carries_the_machine_readable_parts():
    d = S.SpeechUnsupportedMedia(".mp4", (".m4a", ".wav")).to_dict()
    assert d["given"] == ".mp4" and d["accepted"] == [".m4a", ".wav"] and d["sentence"]


def test_unsupported_media_without_a_known_allow_list_still_reads_as_a_sentence():
    e = S.SpeechUnsupportedMedia(".mp4")
    assert "Remedy:" not in e.sentence and e.to_dict()["accepted"] == []


def test_too_long_dict_carries_the_numbers_a_chunker_needs():
    d = S.SpeechTooLong(5400.0, 3600.0).to_dict()
    assert d["seconds"] == 5400.0 and d["limit"] == 3600.0


def test_throttled_carries_the_providers_own_hint():
    assert S.SpeechThrottled("transcription", retry_after=30).to_dict()["retry_after"] == 30


# ----------------------------------------------------------------- the port itself
def test_capabilities_names_the_two_requirements_that_drove_this_port():
    assert "diarization" in S.CAPABILITIES and "code_switching" in S.CAPABILITIES


class _FakeTranscriber:
    def capabilities(self, deep: bool = False): return {c: None for c in S.CAPABILITIES}
    def transcribe(self, audio, *, languages=(), diarize=True, speaker_count=None, vocabulary=()):
        return _t(*SEGS)


def test_a_plain_object_satisfies_the_port_structurally():
    """Protocol, not a base class: a test double is a plain object, and an adapter inherits nothing."""
    assert isinstance(_FakeTranscriber(), S.Transcriber)


def test_the_port_names_no_provider_and_imports_nothing_outside_the_domain():
    """CLAUDE.md: the vendor lives in the SERVICE, never in the port."""
    import pathlib
    root = pathlib.Path(S.__file__).parent
    banned = ("munsit", "cntxt", "speechmatics", "whisper", "deepgram", "assemblyai", "elevenlabs",
              "azure", "openai", "requests", "httpx", "urllib")
    for f in root.glob("*.py"):
        src = f.read_text(encoding="utf-8").lower()
        for b in banned:
            assert b not in src, f"{f.name} names {b!r} — the port must be provider-free"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
