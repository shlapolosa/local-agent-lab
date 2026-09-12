"""`enable_language_identification` is the request field this provider's whole contract rests on.

Measured 12 Sep 2026, the SAME recording, two calls that differed only by this boolean:

    without it   410 tokens, `language` absent on every one of them, and the Arabic returned under
                 `translation_status: none` in Arabic script with a `translation` run after it —
                 a payload in which nothing says which words the rendering replaces
    with it      435 tokens, 335 `none`/en + 53 `original`/ar + 47 `translation`/en, strictly
                 alternating, every token carrying its recognised language

Two separate promises were broken by its absence. The port states that the recognised language comes
back PER SEGMENT — without the field there is none. And `tokenmap` breaks a speaker's run at a change
of language, so the code-switch this lab exists to make visible was invisible: one 138-token run
where there should have been several.

So this is not a nice-to-have flag, and it is not a defaulted option either — there is no request
this adapter should ever send without it.
"""
from lab.substrate.mcp.speech import soniox_map as M


def test_every_request_asks_for_the_recognised_language():
    body = M.request_body(file_id="f1", languages=("ar", "en"), diarize=True, translate_to="en")
    assert body["enable_language_identification"] is True


def test_it_is_asked_for_even_with_no_translation_and_no_hints():
    """The language is part of the transcript, not part of the translation feature: a monolingual
    request still has to say which language it decided on."""
    body = M.request_body(file_id="f1")
    assert body["enable_language_identification"] is True


def test_a_rendering_after_an_unmarked_run_still_lands_on_the_timeline():
    """The shape seen with the flag OFF: translated speech marked `none`, its rendering following.
    We no longer send that request, but a lane must degrade rather than fail — the rendering borrows
    the span of whatever run precedes it, so the transcript is merely imprecise instead of refused.
    Before this, `Transcript.__post_init__` rejected the whole run and the lane reported nothing."""
    payload = {"tokens": [
        {"text": "As-salaam", "start_ms": 5970, "end_ms": 6300, "speaker": "1"},
        {"text": " alaykum.", "start_ms": 6300, "end_ms": 6690, "speaker": "1"},
        {"text": "Peace", "start_ms": 0, "end_ms": 0, "speaker": "1",
         "translation_status": "translation"},
        {"text": " be upon you.", "start_ms": 0, "end_ms": 0, "speaker": "1",
         "translation_status": "translation"},
        {"text": " How are you?", "start_ms": 7470, "end_ms": 8000, "speaker": "2"},
    ]}
    t = M.to_transcript(payload, want=M.ENGLISH)          # must not raise
    assert [round(s.start, 2) for s in t.segments] == [5.97, 5.97, 7.47]
    # And this is what the degraded shape COSTS, stated rather than hidden: the speech the provider
    # failed to mark is kept AND its rendering is kept, so the utterance appears twice, at the same
    # second. Only the `original` marker can say which words to drop — which is the argument for
    # sending the flag, not for a heuristic that guesses the boundary. What the kind break does buy
    # is that the two are separate segments rather than one run of words nobody can attribute.
    assert [s.text for s in t.segments[:2]] == ["As-salaam alaykum.", "Peace be upon you."]


def test_a_borrowed_span_is_the_run_before_and_not_every_word_before_it():
    """The span pools per RUN. Keyed on 'has anything been spoken yet' instead, a rendering after a
    long English stretch borrowed from the start of that stretch — placing a 54-second sentence at
    5 seconds and reordering the transcript around it."""
    payload = {"tokens": [
        {"text": "a", "start_ms": 5000, "end_ms": 5200, "speaker": "1"},
        {"text": " b", "start_ms": 5200, "end_ms": 5600, "speaker": "1"},
        {"text": " c", "start_ms": 52170, "end_ms": 54690, "speaker": "2",
         "translation_status": "original", "language": "ar"},
        {"text": " d", "start_ms": 0, "end_ms": 0, "speaker": "2",
         "translation_status": "translation", "language": "en"},
    ]}
    t = M.to_transcript(payload, want=M.TRANSLATION)
    assert (t.segments[0].start, t.segments[0].end) == (52.17, 54.69)
