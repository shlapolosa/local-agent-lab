"""Soniox's unified stream has THREE kinds of token, and the mapper only ever knew about two.

Measured against the live API on 12 Sep 2026, one 91.8-second bilingual meeting, 435 tokens:

    translation_status = "none"           335   English speech, nothing to translate
    translation_status = "original"        53   the Arabic, as spoken
    translation_status = "translation"     47   its English rendering

`want=ORIGINAL` was right — it keeps `none` + `original`, the verbatim record. `want=TRANSLATION`
kept ONLY the 36, so a mostly-English meeting came back as 21 words out of 219 and the English bulk
was silently discarded. The artifact this lab actually wants — a fully English transcript — is
`none` + `translation`, which was in the response all along.

The second defect is the JOIN. Soniox emits SUB-WORD tokens carrying their own leading spaces
(`"Ass"`, `"al"`, `"amu"`, `" al"`, `"a"`, `"ik"`), so concatenating gives "Assalamu alaik" while
strip-and-space-joining gives "Ass al amu al a ik". That is what produced "Pe ace be up on y ou"
from "Peace be upon you" — a real translation, made unreadable on the way out.
"""
import pytest

from lab.core.speech import SpeechError
from lab.substrate.mcp.speech import soniox_map as S
from lab.substrate.mcp.speech.tokenmap import Tok, group_into_segments


def tok(text, status="none", speaker="1", lang="en", start=0, end=60):
    return {"text": text, "start_ms": start, "end_ms": end, "speaker": speaker,
            "language": lang, "translation_status": status}


# the real shape, trimmed: English, then an Arabic span, then its rendering, then English again
PAYLOAD = {"audio_duration_ms": 80000, "tokens": [
    tok("Ass", start=0, end=60), tok("al", start=60, end=120), tok("amu", start=120, end=180),
    tok(" al", start=180, end=240), tok("a", start=240, end=300), tok("ik", start=300, end=360),
    tok("um.", start=360, end=420),
    tok(" حلو", "original", "2", "ar", 52000, 52300),
    tok(" بس", "original", "2", "ar", 52300, 52600),
    tok(" Nice", "translation", "2", "en", 52000, 52300),
    tok(".", "translation", "2", "en", 52300, 52600),
    tok(" But", "translation", "2", "en", 52600, 52900),
    tok(" Thanks", start=70000, end=70300),
]}


def text_of(t):
    return " ".join(s.text for s in t.segments)


# ------------------------------------------------------------------ the join
def test_sub_word_tokens_are_concatenated_not_space_joined():
    """`"Ass" + "al" + "amu" + " al" + "a" + "ik"` is one word and a bit, not six words. The leading
    space IS the word boundary; stripping it throws away the only spacing information there is."""
    got = group_into_segments([Tok("Ass", 0, 0.1), Tok("al", 0.1, 0.2), Tok("amu", 0.2, 0.3),
                               Tok(" al", 0.3, 0.4), Tok("a", 0.4, 0.5), Tok("ik", 0.5, 0.6)],
                              concat=True)
    assert got[0].text == "Assalamu alaik"


def test_a_word_stream_still_joins_with_spaces():
    """ElevenLabs emits WORDS with no embedded spacing — it drops its own `spacing` entries — so the
    default must stay a space join or that provider regresses the moment this one is fixed."""
    got = group_into_segments([Tok("hello", 0, 0.4), Tok("there", 0.5, 0.9)])
    assert got[0].text == "hello there"


# ------------------------------------------------------------------ the three modes
def test_verbatim_keeps_what_was_said_including_the_arabic():
    t = S.to_transcript(PAYLOAD, want=S.ORIGINAL)
    body = text_of(t)
    assert "حلو" in body and "Nice" not in body
    assert "Assalamu alaik" in body, "the sub-word join must apply here too"


def test_english_keeps_the_untranslated_english_AND_the_rendering():
    """The mode this lab actually wants, and the one that did not exist. A mostly-English meeting
    must not come back as only the few sentences that happened to need translating."""
    t = S.to_transcript(PAYLOAD, want=S.ENGLISH)
    body = text_of(t)
    assert "Nice" in body and "But" in body, "the Arabic must arrive rendered"
    assert "Assalamu alaik" in body and "Thanks" in body, "the English bulk must survive"
    assert "حلو" not in body and "بس" not in body, "no Arabic script in a fully English rendering"


def test_translation_only_is_still_reachable_and_still_narrow():
    """Kept deliberately: it is what a side-by-side of 'what was rendered' needs. It is simply not
    what a reader wants, which is why it must not be what `soniox-en` asks for."""
    t = S.to_transcript(PAYLOAD, want=S.TRANSLATION)
    body = text_of(t)
    assert "Nice" in body and "Assalamu" not in body


def test_every_mode_names_itself_on_the_transcript():
    for want in (S.ORIGINAL, S.TRANSLATION, S.ENGLISH):
        assert S.to_transcript(PAYLOAD, want=want).provider == f"{S.PROVIDER}-{want}"


def test_an_unknown_mode_is_refused_rather_than_silently_empty():
    """A typo used to fall through the status comparison and return a transcript of whatever
    happened not to match — an empty or half transcript that looks like a bad recording. `SpeechError`
    and not `Exception`: the port's promise is a TYPED refusal, and a bare `Exception` here passes on
    the `KeyError` that promise forbids."""
    with pytest.raises(SpeechError):
        S.to_transcript(PAYLOAD, want="engish")


# ------------------------------------------------------------------ the speaker survives both halves
def test_the_rendering_keeps_the_speaker_the_arabic_was_spoken_by():
    """Soniox preserves `speaker` on translated tokens, which is what makes a translated transcript
    still attributable — lose it and the minutes cannot say who asked the question."""
    t = S.to_transcript(PAYLOAD, want=S.ENGLISH)
    said_by = {s.speaker for s in t.segments if "Nice" in s.text}
    assert said_by == {"SPEAKER_02"}, f"the rendered span lost its speaker: {said_by}"


# ------------------------------------------------------------------ the adapter, not just the mapper
def test_the_adapter_accepts_the_english_mode():
    """The mapper knowing a mode is not enough — the adapter validated `want` against its own pair
    and would have refused the very rendering the `soniox-en` lane now asks for."""
    from lab.substrate.mcp.speech import soniox_repository as SR
    box = SR.build(api_key="k", transport=object(), want=S.ENGLISH, translate_to="en")
    assert box.warnings()  # it must SAY the Arabic arrives rendered


def test_the_english_mode_refuses_to_be_built_with_no_target_language():
    """With no target the provider translates nothing, so this mode would quietly return the
    verbatim record — Arabic script and all — under a name that promises English."""
    from lab.core.speech import SpeechError
    from lab.substrate.mcp.speech import soniox_repository as SR
    with pytest.raises(SpeechError):
        SR.build(api_key="k", transport=object(), want=S.ENGLISH, translate_to="")


def test_the_english_warning_is_not_the_translation_warning():
    """'This is a translation' overstates a mostly-verbatim transcript; saying nothing would let a
    rendered sentence be quoted as words somebody said. Both are wrong in different directions."""
    from lab.substrate.mcp.speech import soniox_repository as SR
    en = SR.build(api_key="k", transport=object(), want=S.ENGLISH, translate_to="en").warnings()
    tr = SR.build(api_key="k", transport=object(), want=S.TRANSLATION, translate_to="en").warnings()
    assert "RENDERED" in en[0] and "TRANSLATION" in tr[0] and en != tr


def test_the_lane_named_soniox_en_asks_for_english():
    """The registry line is the only thing that decides what a deployed lane returns, so it is the
    line worth pinning: `soniox-en` pointed at `translation` for its whole life."""
    from lab.substrate.container import SPEECH_PROVIDER_OPTIONS
    assert SPEECH_PROVIDER_OPTIONS["soniox-en"]["want"] == S.ENGLISH


# ------------------------------------------------------------------ nothing vanishes
def test_speech_that_was_never_rendered_stays_in_the_english_transcript():
    """An `original` run is dropped from the English rendering because its translation takes its
    place — so a run the provider never translated would disappear with no trace. Worse, the mode's
    success metric is "no Arabic script", so losing it reads as a WIN. Keeping it makes the gap
    visible in the digest instead, which is the honest failure for a transcript minutes are written
    from."""
    payload = {"tokens": [
        tok(" Hello", start=0, end=500),
        tok(" ان شاء الله", "original", "1", "ar", 1000, 2000),      # no rendering follows
        tok(" bye", start=3000, end=3500),
    ]}
    t = S.to_transcript(payload, want=S.ENGLISH)
    assert "ان شاء الله" in " ".join(s.text for s in t.segments)


def test_speech_that_WAS_rendered_is_not_kept_twice():
    """The other side of the same rule: when the rendering is there, the original must go, or the
    English transcript says everything once in Arabic and again in English."""
    payload = {"tokens": [
        tok(" ان شاء الله", "original", "1", "ar", 1000, 2000),
        tok(" God willing", "translation", "1", "en", 0, 0),
    ]}
    body = " ".join(s.text for s in S.to_transcript(payload, want=S.ENGLISH).segments)
    assert body == "God willing"
