"""Turning a provider's WORD/TOKEN stream into the domain's SEGMENTS. Pure; shared by two mappers.

Two of the four providers answer with a flat stream of words or tokens, each tagged with a speaker,
rather than with ready-made segments. Grouping that stream into speaker turns is the same operation
both times, and getting it wrong is silent — a run split on every word yields a transcript that
reads correctly and diarizes uselessly — so it is written once and tested once.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

from lab.core.speech import Segment

__all__ = ["Tok", "group_into_segments", "SPOKEN", "RENDERED"]

UNKNOWN = "SPEAKER_00"          # a provider that diarizes nothing still owes us one attributed voice

#: What a token IS, when a provider returns more than one kind. `SPOKEN` is words somebody said;
#: `RENDERED` is a translation the provider generated from them. They must never share a segment: a
#: segment is quoted to a human at the speaker-naming approval as "what this speaker said", and a
#: rendered sentence offered there as a verbatim utterance is exactly the confusion the adapter's
#: warning exists to prevent — a warning on the whole transcript cannot say WHICH span.
SPOKEN, RENDERED = "", "rendered"


class Tok(NamedTuple):
    """One provider token, normalised. Seconds, never milliseconds — converted by its own mapper."""

    text: str
    start: float
    end: float
    speaker: str = ""
    language: str = ""
    kind: str = SPOKEN


def group_into_segments(tokens: Iterable[Tok], *, concat: bool = False) -> tuple[Segment, ...]:
    """Consecutive tokens of the same speaker, language and KIND become one segment, in time order.

    The language break is there because a language change inside one speaker's turn is precisely the
    code-switch this lab exists to make visible, and merging across it would erase the evidence. The
    kind break is there for the same reason one step further on: a provider that returns a
    translation beside the speech returns both under the same speaker and, once translated, the same
    language — so kind is the only thing left that can hold them apart.

    `concat` is HOW the provider's tokens become words, and it differs per provider because the two
    stream shapes carry spacing in different places:

      `False`  a WORD stream. ElevenLabs emits whole words and drops its own `spacing` entries, so
               the spaces have to be put back. This is the default; it was the only behaviour.
      `True`   a SUB-WORD stream. Soniox emits token fragments that carry their own leading space —
               `"Ass"`, `"al"`, `"amu"`, `" al"`, `"a"`, `"ik"` — so the boundary is already in the
               text and concatenating is the whole job.

    Getting it backwards is silent and survives review: measured live 12 Sep 2026, the space join
    turned Soniox's "Peace be upon you" into "Pe ace be up on y ou" — a correct translation of
    `Salam alaikum` made unreadable on the way out, in a transcript that still looked like a
    transcript.
    """
    out: list[Segment] = []
    run: list[Tok] = []
    for tok in tokens:
        if not tok.text.strip():
            # A blank token carries no words, so it can neither open a run nor break one. In a WORD
            # stream that is all it is. In a SUB-WORD stream it is a word BOUNDARY, and dropping it
            # deletes a space: measured in shipped output, "going to the right direction" came back
            # as "going to theright direction" — one boundary in 212 words, and the only code path
            # that can remove one. So keep it, but only inside a run already open.
            if run and concat:
                run.append(tok)
            continue
        if run and (tok.speaker != run[-1].speaker or tok.language != run[-1].language
                    or tok.kind != run[-1].kind):
            out.append(_segment(run, concat))
            run = []
        run.append(tok)
    if run:
        out.append(_segment(run, concat))
    return tuple(out)


def _segment(run: list[Tok], concat: bool) -> Segment:
    # A word stream is stripped per token and re-spaced; a sub-word stream is concatenated verbatim,
    # because stripping it would destroy the only spacing information the provider sent.
    text = ("".join(t.text for t in run) if concat
            else " ".join(t.text.strip() for t in run if t.text.strip())).strip()
    spoken = [t for t in run if t.text.strip()] or run
    return Segment(
        start=min(t.start for t in spoken),
        end=max(t.end for t in spoken),
        text=text,
        speaker=run[0].speaker or UNKNOWN,
        language=run[0].language,
    )
