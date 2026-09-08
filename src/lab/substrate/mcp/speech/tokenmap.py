"""Turning a provider's WORD/TOKEN stream into the domain's SEGMENTS. Pure; shared by two mappers.

Two of the four providers answer with a flat stream of words or tokens, each tagged with a speaker,
rather than with ready-made segments. Grouping that stream into speaker turns is the same operation
both times, and getting it wrong is silent — a run split on every word yields a transcript that
reads correctly and diarizes uselessly — so it is written once and tested once.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

from lab.core.speech import Segment

__all__ = ["Tok", "group_into_segments"]

UNKNOWN = "SPEAKER_00"          # a provider that diarizes nothing still owes us one attributed voice


class Tok(NamedTuple):
    """One provider token, normalised. Seconds, never milliseconds — converted by its own mapper."""

    text: str
    start: float
    end: float
    speaker: str = ""
    language: str = ""


def group_into_segments(tokens: Iterable[Tok]) -> tuple[Segment, ...]:
    """Consecutive tokens from the SAME speaker become one segment, in time order.

    A run is broken by a change of speaker or of recognised language — the second because a
    language change inside one speaker's turn is precisely the code-switch this lab exists to make
    visible, and merging across it would erase the evidence.
    """
    out: list[Segment] = []
    run: list[Tok] = []
    for tok in tokens:
        if not tok.text.strip():
            continue
        if run and (tok.speaker != run[-1].speaker or tok.language != run[-1].language):
            out.append(_segment(run))
            run = []
        run.append(tok)
    if run:
        out.append(_segment(run))
    return tuple(out)


def _segment(run: list[Tok]) -> Segment:
    return Segment(
        start=min(t.start for t in run),
        end=max(t.end for t in run),
        text=" ".join(t.text.strip() for t in run).strip(),
        speaker=run[0].speaker or UNKNOWN,
        language=run[0].language,
    )
