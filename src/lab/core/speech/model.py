"""The value objects of the SPEECH context: what a transcription IS, in the domain's own words.

Two ideas earn their place here, and both come straight from what this lab actually has to solve.

**A segment reports the language it was RECOGNISED as, not just its text.** Speakers switch between
languages inside a single sentence. Every provider we surveyed either declares one language per
request or classifies at segment boundaries, and the characteristic failure is silent: a span in one
language comes back as fluent, plausible text in the other, or as a transliteration. A contract that
carries only words cannot express that, so it cannot detect it. Carrying the recognised language per
segment is what makes the failure VISIBLE, and `code_switched` is the one-line observable.

**A speaker digest is DERIVED, never restated by the provider.** Who spoke, for how long and how
often are facts about the segments. Recomputing them here means a provider cannot flatter itself,
and it gives the human-mapping approval exactly the evidence it needs.

Pure domain: no provider, no transport, no credential.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AudioClip", "Segment", "SpeakerStat", "Transcript", "MAX_SAMPLES"]

MAX_SAMPLES = 3          # verbatim utterances shown per speaker on the mapping approval


@dataclass(frozen=True)
class AudioClip:
    """The audio to transcribe: its bytes, the NAME it arrived under, and its length when known.

    The name is not decoration. A provider accepts some containers and not others, and a meeting
    recording arrives as VIDEO, so the container has to be checkable before a large upload is paid
    for. `seconds` is the same story for the per-request length cap: knowing it lets an adapter
    refuse with a sentence instead of after a slow failure. Both are optional-ish — `seconds` of 0
    means "unknown", never "empty".

    A clip is bytes, never a path and never a URL: the workload holds a reference, the substrate
    holds the credential, and this object is what crosses between them.
    """

    name: str
    data: bytes = b""
    seconds: float = 0.0

    def __post_init__(self) -> None:
        if not (self.name or "").strip():
            raise ValueError("audio needs a name — the container decides whether a provider accepts it")

    @property
    def suffix(self) -> str:
        """The lower-cased container suffix, with its dot, or empty when the name has none."""
        _, dot, ext = self.name.rpartition(".")
        return f".{ext.lower()}" if dot and ext else ""


@dataclass(frozen=True)
class Segment:
    """One diarized utterance: who (anonymously), when, what, and in which language.

    `speaker` is the provider's ANONYMOUS label (`SPEAKER_00`), never a person — mapping a label to
    a human is a separate, human-gated act. `language` is the language actually recognised, empty
    when the provider does not report one; an empty value is NOT evidence of anything.
    """

    speaker: str
    start: float
    end: float
    text: str = ""
    language: str = ""

    def __post_init__(self) -> None:
        if not (self.speaker or "").strip():
            raise ValueError("a segment needs a speaker label — an unattributed segment is not diarized")
        if self.start < 0:
            raise ValueError(f"a segment cannot start before the recording ({self.start})")
        if self.end < self.start:
            raise ValueError(f"a segment cannot end before it starts ({self.start} -> {self.end})")

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class SpeakerStat:
    """How much one anonymous speaker said. Derived from the segments, never supplied."""

    label: str
    seconds: float
    turns: int


@dataclass(frozen=True)
class Transcript:
    """A diarized transcription: the segments, plus what can be derived from them.

    `duration` is the recording's length as the provider reported it, which is not the same as the
    sum of the segments — silence and unattributed audio live in the gap, and that gap is itself
    diagnostic.
    """

    segments: tuple[Segment, ...] = ()
    duration: float = 0.0
    model: str = ""                       # which of the provider's models produced this
    provider: str = ""                    # for the run log; the PORT still names no vendor

    def __post_init__(self) -> None:
        last = None
        for s in self.segments:
            if last is not None and s.start < last:
                raise ValueError("segments must be in time order — a transcript is a timeline")
            last = s.start

    @property
    def labels(self) -> tuple[str, ...]:
        """Every speaker label, in the order they FIRST spoke — the order a human reads them in."""
        seen: dict[str, None] = {}
        for s in self.segments:
            seen.setdefault(s.speaker, None)
        return tuple(seen)

    @property
    def speakers(self) -> tuple[SpeakerStat, ...]:
        """The per-speaker digest, derived. Same order as `labels`."""
        secs: dict[str, float] = {}
        turns: dict[str, int] = {}
        for s in self.segments:
            secs[s.speaker] = secs.get(s.speaker, 0.0) + s.duration
            turns[s.speaker] = turns.get(s.speaker, 0) + 1
        return tuple(SpeakerStat(l, secs[l], turns[l]) for l in self.labels)

    @property
    def languages(self) -> tuple[str, ...]:
        """The distinct languages actually recognised, sorted. Empty when none were reported."""
        return tuple(sorted({s.language for s in self.segments if s.language}))

    @property
    def code_switched(self) -> bool:
        """Whether more than one language was recognised.

        False when the provider reported no languages at all: absence of labels is not evidence of a
        single language, and silence must never read as success.
        """
        return len(self.languages) > 1

    @property
    def text(self) -> str:
        """The whole transcript in time order, for a reader or a downstream model."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def samples_for(self, label: str, limit: int = MAX_SAMPLES) -> tuple[str, ...]:
        """Verbatim utterances that best help a human recognise this speaker.

        Ranked by how long the turn LASTED, not by how much text it produced. That picks the
        substantial turns over the backchannels ("mm", "na'am") that carry no identifying content,
        and it is script-neutral: Arabic renders the same speech in far fewer characters than
        English, so ranking by text length would quietly prefer the English turns of a mixed
        recording — exactly the wrong bias for the meetings this exists to serve. Ties break on
        length, then on time, so the order is fully deterministic. Blank text is skipped so the
        mapping form never shows an empty quote.
        """
        mine = [s for s in self.segments if s.speaker == label and s.text.strip()]
        best = sorted(mine, key=lambda s: (-s.duration, -len(s.text.strip()), s.start))
        return tuple(s.text.strip() for s in best[:max(0, limit)])
