"""A Soniox rendering carries NO timestamps, so it has to borrow the span it renders.

Measured on the live response (435 tokens, 12 Sep 2026): a translated run is emitted in STREAM
order, immediately after the original run it renders, and every one of its tokens has
`start_ms: 0, end_ms: 0`. Four such runs in one 91.8-second meeting.

That matters because `Transcript.__post_init__` refuses segments out of time order — a transcript is
a timeline. So `none` + `translation`, the rendering a person reads, was a stream that rewound to
zero on every translated span and the domain model threw it out. `translation` alone did NOT throw,
which is worse: every segment sat at 0.0, so nothing was out of order and a column that cannot be
aligned in time looked fine.

The rule: a timestamp-less rendering occupies exactly the span of the speech it renders. Borrowing,
not overriding — a provider that starts sending real timestamps keeps them.
"""
from lab.substrate.mcp.speech import soniox_map as S


def tok(text, status="none", speaker="1", lang="en", start=0, end=60):
    return {"text": text, "start_ms": start, "end_ms": end, "speaker": speaker,
            "language": lang, "translation_status": status}


ARABIC_SPAN = "حلو"          # the first word of the real Arabic span
ARABIC_SPAN_2 = "بس"

INTERLEAVED = {"audio_duration_ms": 91770, "tokens": [
    tok(" How", start=5000, end=5200), tok(" are", start=5200, end=5400),
    tok(" you?", start=5400, end=5600),
    tok(" " + ARABIC_SPAN, "original", "2", "ar", 52170, 52500),
    tok(" " + ARABIC_SPAN_2, "original", "2", "ar", 52500, 54690),
    tok("Nic", "translation", "2", "en", 0, 0), tok("e.", "translation", "2", "en", 0, 0),
    tok(" But", "translation", "2", "en", 0, 0),
    tok(" I", start=61590, end=61700), tok(" think", start=61700, end=62000),
]}


def test_the_rendering_borrows_the_span_of_the_speech_it_renders():
    t = S.to_transcript(INTERLEAVED, want=S.ENGLISH)     # must not raise
    rendered = [s for s in t.segments if "Nice" in s.text]
    assert rendered, [s.text for s in t.segments]
    assert (rendered[0].start, rendered[0].end) == (52.17, 54.69), \
        "a timestamp-less rendering must sit where the speech was, not at zero"
    starts = [round(s.start, 2) for s in t.segments]
    assert starts == sorted(starts)


def test_translation_only_is_also_placed_on_the_timeline():
    t = S.to_transcript(INTERLEAVED, want=S.TRANSLATION)
    assert t.segments and t.segments[0].start == 52.17


def test_a_rendering_that_does_carry_its_own_timestamps_keeps_them():
    """Borrowing is a fallback for a missing span, never an override."""
    payload = {"tokens": [tok(" " + ARABIC_SPAN, "original", "2", "ar", 1000, 2000),
                          tok(" Nice", "translation", "2", "en", 3000, 4000)]}
    t = S.to_transcript(payload, want=S.TRANSLATION)
    assert (t.segments[0].start, t.segments[0].end) == (3.0, 4.0)


def test_the_verbatim_record_is_unaffected_by_the_borrowing():
    """The original half already had its own timestamps; the fix must not move them."""
    t = S.to_transcript(INTERLEAVED, want=S.ORIGINAL)
    spans = [(round(s.start, 2), round(s.end, 2)) for s in t.segments]
    assert (52.17, 54.69) in spans and (5.0, 5.6) in spans


def test_a_rendering_with_no_preceding_speech_stays_where_the_provider_put_it():
    """Defensive, not observed: borrowing needs something to borrow from, and a stream that opens
    with a rendering must still produce a transcript rather than an IndexError."""
    t = S.to_transcript({"tokens": [tok(" Nice", "translation", "2", "en", 0, 0)]},
                        want=S.TRANSLATION)
    assert t.segments[0].start == 0.0
