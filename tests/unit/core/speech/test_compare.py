"""`lab.core.speech.compare` — how this lab JUDGES one transcript against another.

Pure, and in the domain, because the thing being measured IS the driving requirement. The bake-off
script that calls it is a probe and may be thrown away; the definition of "this provider wrote our
English in the wrong alphabet" is not.

The metric that matters here is SCRIPT MIX. Measured 7 Sep 2026 on a real meeting: the incumbent
provider heard English correctly and rendered it in Arabic letters (`اكشن ايتمز` = "action items"),
and the published benchmark for code-switched Arabic (arXiv 2605.19069) found WER overstates such
gaps ~3x by scoring semantically correct transliteration as error. So WER would rank a provider
badly for the very thing we must measure directly, and a share-of-script number says it plainly.
"""
from lab.core import speech as S
from lab.core.speech import compare as C


def test_script_mix_separates_arabic_from_latin():
    m = C.script_mix("action items اكشن ايتمز")
    assert m.latin == len("actionitems") and m.arabic == len("اكشنايتمز")
    assert 0.0 < m.arabic_share < 1.0


def test_script_mix_ignores_digits_spaces_and_punctuation_so_shares_mean_something():
    """A share of ALL characters would move when someone read out a phone number."""
    m = C.script_mix("hello, 123 world!")
    assert m.arabic == 0 and m.latin == len("helloworld") and m.arabic_share == 0.0


def test_script_mix_of_nothing_is_not_a_division_by_zero():
    m = C.script_mix("   123  ")
    assert m.total == 0 and m.arabic_share == 0.0


def test_english_spoken_but_written_in_arabic_letters_scores_as_arabic():
    """The exact failure this exists to expose: every word is English, every letter is Arabic."""
    assert C.script_mix("وي هاد اكشن ايتمز").arabic_share == 1.0


def test_digest_reports_what_a_reviewer_compares_across_providers():
    t = S.Transcript(
        segments=(S.Segment(start=0.0, end=2.0, text="hello there", speaker="SPEAKER_00"),
                  S.Segment(start=2.0, end=3.0, text="", speaker="SPEAKER_01"),
                  S.Segment(start=3.0, end=6.0, text="اكشن ايتمز", speaker="SPEAKER_00", language="ar")),
        duration=10.0, model="m", provider="p")
    d = C.digest(t)
    assert d["provider"] == "p" and d["model"] == "m"
    assert d["segments"] == 3 and d["spoken_segments"] == 2
    assert d["speakers"] == 1                      # the empty segment mints nobody
    assert d["spoken_seconds"] == 5.0
    assert d["duration"] == 10.0 and d["coverage"] == 0.5
    assert d["languages"] == ["ar"] and d["words"] == 4
    assert 0.0 < d["arabic_share"] < 1.0


def test_digest_of_an_empty_transcript_says_so_instead_of_dividing_by_zero():
    d = C.digest(S.Transcript(segments=(), duration=0.0))
    assert d["segments"] == 0 and d["speakers"] == 0 and d["coverage"] == 0.0
    assert d["arabic_share"] == 0.0


def test_side_by_side_pairs_segments_that_overlap_in_time():
    """Providers segment differently, so a comparison must align on the TIMELINE, not on index —
    otherwise row 3 of one transcript is read against row 3 of another that covers other seconds."""
    a = S.Transcript(segments=(S.Segment(start=0.0, end=5.0, text="hello there", speaker="SPEAKER_00"),
                               S.Segment(start=6.0, end=8.0, text="goodbye", speaker="SPEAKER_00")))
    b = S.Transcript(segments=(S.Segment(start=0.5, end=2.0, text="hello", speaker="A"),
                               S.Segment(start=2.5, end=4.5, text="there", speaker="A"),
                               S.Segment(start=9.0, end=9.5, text="later", speaker="B")))
    rows = C.side_by_side({"a": a, "b": b})
    assert [r["start"] for r in rows] == [0.0, 6.0, 9.0]
    assert rows[0]["by_provider"]["b"] == "hello there"      # both overlapping segments, in order
    assert rows[1]["by_provider"]["b"] == ""                 # nothing overlaps: visible as a gap
    assert rows[2]["by_provider"]["a"] == "" and rows[2]["by_provider"]["b"] == "later"
