"""Grouping a provider's word stream into speaker turns — shared by two mappers, so tested once."""
from lab.substrate.mcp.speech.tokenmap import RENDERED, Tok, group_into_segments


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


# ------------------------------------------------------------- the sub-word (concat) stream
def test_a_sub_word_stream_is_concatenated_because_the_space_is_already_in_the_token():
    """Soniox emits fragments carrying their own leading space. Stripped and re-spaced, "Peace be
    upon you" came back as "Pe ace be up on y ou" — a correct translation made unreadable on the way
    out, in a transcript that still looked like a transcript."""
    segs = group_into_segments([Tok("Pe", 0.0, 0.1, "A"), Tok("ace", 0.1, 0.2, "A"),
                                Tok(" be", 0.2, 0.3, "A"), Tok(" up", 0.3, 0.4, "A"),
                                Tok("on", 0.4, 0.5, "A"), Tok(" y", 0.5, 0.6, "A"),
                                Tok("ou", 0.6, 0.7, "A")], concat=True)
    assert segs[0].text == "Peace be upon you"


def test_a_whitespace_only_token_is_a_word_boundary_in_a_sub_word_stream():
    """In a WORD stream a blank token carries nothing. In a SUB-WORD stream it IS the boundary, and
    dropping it deletes a space: shipped output read "going to theright direction" — one boundary in
    212 words, and this filter is the only code path that can remove one."""
    segs = group_into_segments([Tok("the", 0.0, 0.1, "A"), Tok(" ", 0.1, 0.2, "A"),
                                Tok("right", 0.2, 0.3, "A")], concat=True)
    assert segs[0].text == "the right"


def test_a_leading_blank_token_still_neither_opens_a_segment_nor_shifts_its_start():
    """It is kept INSIDE an open run only. Opening a run with one would put a segment's start at a
    silence and let a blank token carry a speaker label of its own."""
    segs = group_into_segments([Tok(" ", 0.0, 0.05, "A"), Tok("hi", 1.0, 1.2, "A")], concat=True)
    assert len(segs) == 1 and segs[0].text == "hi" and segs[0].start == 1.0


def test_a_word_stream_still_gets_its_spaces_put_back():
    """The default must not move: ElevenLabs and AssemblyAI drop their own spacing entries, so they
    regress the moment the other provider is fixed in the shared helper."""
    segs = group_into_segments([Tok("hello", 0.0, 0.4, "A"), Tok("there", 0.5, 0.9, "A")])
    assert segs[0].text == "hello there"


# ------------------------------------------------------------- spoken vs rendered
def test_a_rendering_is_its_own_segment_even_from_the_same_speaker_in_the_same_language():
    """Speech and a translation of other speech share a speaker and — once translated — a language,
    so KIND is the only thing left that can hold them apart. A segment is quoted to a human at the
    speaker-naming approval as words that speaker said; a generated sentence must not arrive inside
    one."""
    segs = group_into_segments([Tok("I think", 0.0, 1.0, "A", "en"),
                                Tok("Praise be to God.", 1.0, 2.0, "A", "en", RENDERED),
                                Tok("Good", 2.0, 3.0, "A", "en")])
    assert [s.text for s in segs] == ["I think", "Praise be to God.", "Good"]
