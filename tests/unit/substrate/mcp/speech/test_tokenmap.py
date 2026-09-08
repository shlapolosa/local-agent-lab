"""Grouping a provider's word stream into speaker turns — shared by two mappers, so tested once."""
from lab.substrate.mcp.speech.tokenmap import Tok, group_into_segments


def test_consecutive_words_from_one_speaker_become_one_segment():
    segs = group_into_segments([Tok("hello", 0.0, 0.5, "A"), Tok("there", 0.5, 1.0, "A")])
    assert len(segs) == 1
    assert segs[0].text == "hello there" and segs[0].start == 0.0 and segs[0].end == 1.0


def test_a_change_of_speaker_breaks_the_run():
    segs = group_into_segments([Tok("hello", 0.0, 0.5, "A"), Tok("hi", 0.6, 1.0, "B"),
                                Tok("again", 1.1, 1.4, "A")])
    assert [(s.speaker, s.text) for s in segs] == [("A", "hello"), ("B", "hi"), ("A", "again")]


def test_a_change_of_language_breaks_the_run_because_that_is_the_switch_we_must_see():
    """Merging across it would erase the one piece of evidence this lab's port exists to carry."""
    segs = group_into_segments([Tok("we need", 0.0, 1.0, "A", "en"),
                                Tok("ان شاء الله", 1.0, 2.0, "A", "ar"),
                                Tok("to ship", 2.0, 3.0, "A", "en")])
    assert [s.language for s in segs] == ["en", "ar", "en"]


def test_blank_tokens_are_dropped_rather_than_padding_the_text():
    segs = group_into_segments([Tok("hello", 0.0, 0.5, "A"), Tok("   ", 0.5, 0.6, "A"),
                                Tok("there", 0.6, 1.0, "A")])
    assert segs[0].text == "hello there"


def test_a_provider_that_names_no_speaker_still_yields_an_attributed_segment():
    """`Segment` refuses an unattributed segment, so a mapper must not hand it a blank label."""
    segs = group_into_segments([Tok("hello", 0.0, 0.5)])
    assert segs[0].speaker == "SPEAKER_00"


def test_no_tokens_is_no_segments_not_an_error():
    assert group_into_segments([]) == ()
