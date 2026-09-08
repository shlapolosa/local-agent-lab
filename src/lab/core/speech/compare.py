"""How this lab JUDGES a transcript — the vocabulary of a provider bake-off, in the domain.

Pure: no I/O, no provider, no credential. The script that runs a bake-off is a probe and may be
thrown away; what "better" MEANS for this lab is not, so it lives here and is tested.

WHY SCRIPT MIX IS THE HEADLINE METRIC. The incumbent provider hears English correctly and writes it
in Arabic letters — measured 7 Sep 2026 against Microsoft's own transcript of the same recording,
where `اكشن ايتمز` is a faithful phonetic rendering of "action items". Every word right, every
letter wrong. The published benchmark for code-switched Arabic (arXiv 2605.19069) reports that WER
overstates such gaps by roughly 3x precisely because it scores semantically correct transliteration
as error — so the industry's default metric would rank providers on the thing we most need to
measure separately. A share-of-script number states it directly and needs no reference transcript,
which matters because for a real meeting there usually is not one.

What this deliberately does NOT do is score accuracy. That needs a reference and a semantic metric
(BERTScore, per the same paper), which needs a model; when a reference exists — Microsoft produces
one for any Teams meeting — feed both through `side_by_side` and let a person read them.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from lab.core.speech.model import Transcript

__all__ = ["ScriptMix", "script_mix", "digest", "side_by_side"]


@dataclass(frozen=True)
class ScriptMix:
    """How much of a text is written in each script. Counts LETTERS only.

    Digits, spaces and punctuation are excluded deliberately: they belong to no script, and
    including them would move the share when somebody read out a phone number.
    """

    arabic: int = 0
    latin: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.arabic + self.latin + self.other

    @property
    def arabic_share(self) -> float:
        """0.0 when there are no letters at all — an empty transcript is not 100% anything."""
        return self.arabic / self.total if self.total else 0.0


def script_mix(text: str) -> ScriptMix:
    """Classify every LETTER of `text` by script."""
    arabic = latin = other = 0
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:                      # unnamed codepoint: real, but not attributable
            other += 1
            continue
        if name.startswith("ARABIC"):
            arabic += 1
        elif name.startswith("LATIN"):
            latin += 1
        else:
            other += 1
    return ScriptMix(arabic, latin, other)


def digest(t: Transcript) -> dict:
    """One provider's answer, reduced to what a reviewer compares across providers.

    `coverage` — spoken seconds over the recording's length — is the quiet one to watch: a provider
    that returns beautiful text for half the meeting is worse than one that returns rough text for
    all of it, and nothing else in the digest would reveal that.
    """
    mix = script_mix(t.text)
    spoken = t.spoken
    return {
        "provider": t.provider, "model": t.model,
        "segments": len(t.segments), "spoken_segments": len(spoken),
        "speakers": len(t.speakers), "labels": list(t.labels),
        "words": len(t.text.split()),
        "spoken_seconds": round(sum(s.duration for s in spoken), 3),
        "duration": t.duration,
        "coverage": round(sum(s.duration for s in spoken) / t.duration, 3) if t.duration else 0.0,
        "languages": list(t.languages), "code_switched": t.code_switched,
        "arabic_share": round(mix.arabic_share, 3),
        "arabic_letters": mix.arabic, "latin_letters": mix.latin,
    }


def side_by_side(by_provider: dict[str, Transcript]) -> list[dict]:
    """Align several providers on the TIMELINE so a person can read them against each other.

    Aligning on segment INDEX would be meaningless: providers segment differently, so one's third
    row covers other seconds than another's. Rows come from the union of spoken segments; each row
    carries, per provider, the text of every segment overlapping that row's span — joined in time
    order, and EMPTY when a provider said nothing there, because a gap is itself a finding.
    """
    spans = sorted({(s.start, s.end) for t in by_provider.values() for s in t.spoken})
    rows: list[dict] = []
    for start, end in _merged(spans):
        row = {"start": round(start, 3), "end": round(end, 3), "by_provider": {}}
        for name, t in by_provider.items():
            hits = [s for s in t.spoken if s.start < end and s.end > start]
            row["by_provider"][name] = " ".join(s.text.strip() for s in hits).strip()
        rows.append(row)
    return rows


def _merged(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Overlapping spans collapsed into one row, so a row is a moment in the meeting rather than
    one provider's idea of a sentence."""
    out: list[tuple[float, float]] = []
    for start, end in spans:
        if out and start < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out
