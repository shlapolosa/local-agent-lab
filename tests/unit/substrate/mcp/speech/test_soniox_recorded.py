"""The Soniox mapper against BYTES THE PROVIDER ACTUALLY SENT — `tests/fixtures/soniox_response.json`.

This file exists because of how the three defects fixed on 12 Sep 2026 survived: every Soniox fixture
in this repo had been typed from the published schema, and three of its assumptions were wrong in the
same direction as the mapper — whole-word tokens (they are sub-word, carrying their own leading
space), `translation_status` omitted on untranslated speech (it is `"none"`, and `none` is the bulk),
and translated tokens carrying timestamps (they carry none at all). Code and fixture agreed with each
other, the tests were green, and the `soniox-en` lane returned 21 words of a 219-word meeting.

The fixture is the first 111 tokens of one real response, contiguous and unedited (only the response
id removed) — contiguous because a spliced slice invents word boundaries that the real stream does
not have, which is the same class of mistake again. It carries, in the provider's own shape:

    72 `none`/en · 20 `original`/ar · 19 `translation`/en, two speakers
    19 tokens with `start_ms == end_ms == 0` — every translated one
    1 whitespace-only token, which is a word BOUNDARY and not noise
"""
import json
import pathlib

import pytest

from lab.core.speech import SpeechError
from lab.substrate.mcp.speech import soniox_map as S

RECORDED = json.loads(
    (pathlib.Path(__file__).resolve().parents[4] / "fixtures" / "soniox_response.json").read_text())


def body(t):
    return " ".join(s.text for s in t.segments)


def arabic_share(t):
    from lab.core.speech import compare
    return compare.script_mix(body(t)).arabic_share


# ------------------------------------------------------------------ the shape itself
def test_the_fixture_still_carries_the_shape_the_tests_rely_on():
    """A guard on the FIXTURE, not the code: if somebody trims or regenerates it and the sub-word
    tokens, the `none` bulk or the timestamp-less renderings go away, every test below still passes
    while testing nothing. That is exactly how the typed fixtures failed."""
    toks = RECORDED["tokens"]
    kinds = {t.get("translation_status") for t in toks}
    assert kinds == {"none", "original", "translation"}
    assert sum(1 for t in toks if (t["start_ms"], t["end_ms"]) == (0, 0)) > 0, "no rendering"
    assert all(t.get("language") for t in toks), "language identification must be on"
    assert any(not t["text"].strip() for t in toks), "the whitespace boundary is gone"
    assert any(t["text"] and not t["text"][0].isspace() and len(t["text"]) < 4 for t in toks), \
        "these are supposed to be sub-word fragments"


# ------------------------------------------------------------------ the three renderings
def test_the_verbatim_record_keeps_the_arabic_as_spoken():
    t = S.to_transcript(RECORDED, want=S.ORIGINAL)
    assert "كنت عم أعمل" in body(t)
    assert "I was working" not in body(t)
    assert arabic_share(t) > 0


def test_the_english_rendering_has_no_arabic_script_and_keeps_the_english():
    t = S.to_transcript(RECORDED, want=S.ENGLISH)
    assert arabic_share(t) == 0.0, body(t)
    assert "I was working, I mean," in body(t), "the rendering must arrive"
    assert "Assalamu alaikum." in body(t), "the untranslated English bulk must survive"
    assert "speech AI, I think." in body(t)


def test_the_english_rendering_loses_no_speech():
    """Word counts, both renderings, off the same bytes: the English one must be about as long as the
    verbatim one. `want=translation` — what the lane used to ask for — is a fraction of it, and that
    is the defect this asserts against, not a style preference."""
    words = {w: len(body(S.to_transcript(RECORDED, want=w)).split())
             for w in (S.ORIGINAL, S.ENGLISH, S.TRANSLATION)}
    assert words[S.ENGLISH] >= 0.9 * words[S.ORIGINAL], words
    assert words[S.TRANSLATION] < 0.5 * words[S.ORIGINAL], words


# ------------------------------------------------------------------ the word boundary
def test_the_lone_whitespace_token_is_a_word_boundary():
    """Dropped, it deletes a space: this is the recorded span where shipped output read
    "going to theright direction". One boundary in 212 words, and the only code path that removes
    one."""
    assert "going to the right direction" in body(S.to_transcript(RECORDED, want=S.ORIGINAL))


def test_sub_word_tokens_come_back_as_words():
    assert "Assalamu alaikum." in body(S.to_transcript(RECORDED, want=S.ORIGINAL))


# ------------------------------------------------------------------ the timeline and the speakers
def test_no_rendering_is_left_at_zero():
    t = S.to_transcript(RECORDED, want=S.ENGLISH)
    assert all(s.start > 0 for s in t.segments), [(s.start, s.text) for s in t.segments]


def test_no_speaker_is_credited_with_more_time_than_the_recording():
    """The invariant that catches a mis-borrowed span. A rendering holding the wrong span inflates
    somebody's share silently — it raises nothing, because equal starts are in time order — and
    speaker seconds are what a human reads at the speaker-naming approval."""
    for want in (S.ORIGINAL, S.ENGLISH, S.TRANSLATION):
        t = S.to_transcript(RECORDED, want=want, duration=30.0)
        total = sum(s.seconds for s in t.speakers)
        assert total <= t.duration + 0.01, f"{want}: {total} of {t.duration}"


def test_a_rendering_is_never_merged_into_a_segment_of_speech():
    """A segment is quoted to a human as words that speaker said. In the recorded stream a rendering
    is immediately followed by more English from the same speaker, so without the kind break the two
    become one segment and a generated sentence is offered as a verbatim utterance."""
    t = S.to_transcript(RECORDED, want=S.ENGLISH)
    merged = [s.text for s in t.segments if "I was working" in s.text and "speech AI" in s.text]
    assert not merged, merged


def test_every_segment_names_the_language_it_was_recognised_in():
    """The port's promise, and the thing `enable_language_identification` buys. Without the flag the
    provider returns no language at all and this is empty for every segment."""
    t = S.to_transcript(RECORDED, want=S.ORIGINAL)
    assert {s.language for s in t.segments} == {"en", "ar"}
    assert t.code_switched


# ------------------------------------------------------------------ refusal
def test_a_timeline_the_mapper_cannot_place_is_a_TYPED_refusal():
    """`Transcript` refuses segments out of order with a ValueError — correctly, it is the domain
    invariant. But an adapter must translate that into the port's vocabulary: left as a ValueError it
    escapes the adapter, the governed tool's `except SpeechError` and the span's refusal attribute,
    and the run fails with nothing a person can act on."""
    backwards = {"tokens": [
        {"text": "b", "start_ms": 9000, "end_ms": 9100, "speaker": "1", "language": "en",
         "translation_status": "none"},
        {"text": "a", "start_ms": 1000, "end_ms": 1100, "speaker": "2", "language": "en",
         "translation_status": "none"},
    ]}
    with pytest.raises(SpeechError):
        S.to_transcript(backwards, want=S.ORIGINAL)
