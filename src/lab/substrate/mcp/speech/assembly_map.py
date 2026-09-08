"""MAPPER: AssemblyAI payloads -> `lab.core.speech`. Pure; no I/O, no credential.

In the bake-off as the diarization control: its Universal model solves diarization jointly with
transcription and covers 95 languages. It has NO native speech translation, so it answers the
lab's second requirement only.

Two shape facts drive this file:
  * Times are MILLISECONDS. Converting late — or not at all — yields a transcript whose timeline is
    a thousand times too long, which no assertion about text would catch.
  * `utterances` are ready-made speaker turns and are preferred; `words` is the fallback when
    diarization was not requested, and is grouped like any other word stream.
"""
from __future__ import annotations

from typing import Any

from lab.core.speech import Segment, SpeechError, Transcript
from lab.substrate.mcp.speech.tokenmap import Tok, group_into_segments

__all__ = ["PROVIDER", "MODEL_DEFAULT", "to_transcript", "request_body", "TERMINAL", "ACCEPTED_MEDIA"]

PROVIDER = "assemblyai"
MODEL_DEFAULT = "universal"
TERMINAL = {"completed", "error"}
ACCEPTED_MEDIA = (".aac", ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".wav",
                  ".webm")


def request_body(audio_url: str, languages: tuple[str, ...] = (), diarize: bool = True,
                 speaker_count: int | None = None) -> dict:
    """The submit payload. Language DETECTION is on unless exactly one language is expected —
    same rule as every adapter here: a plural hint means detect, never pick the first."""
    body: dict[str, Any] = {"audio_url": audio_url, "speaker_labels": bool(diarize)}
    want = [l.strip().lower().split("-")[0] for l in languages if (l or "").strip()]
    if len(set(want)) == 1:
        body["language_code"] = want[0]
    else:
        body["language_detection"] = True
    if speaker_count:
        body["speakers_expected"] = int(speaker_count)
    return body


def to_transcript(payload: Any, model: str = MODEL_DEFAULT) -> Transcript:
    if not isinstance(payload, dict):
        raise SpeechError(f"unexpected response from {PROVIDER}: {type(payload).__name__}")
    if payload.get("status") == "error":
        raise SpeechError(str(payload.get("error") or "the provider reported an error"))
    language = str(payload.get("language_code") or "")
    utterances = payload.get("utterances") or []
    if utterances:
        segments = tuple(
            Segment(start=_s(u.get("start")), end=_s(u.get("end")),
                    text=str(u.get("text") or ""), speaker=_label(u.get("speaker")),
                    language=language)
            for u in utterances if isinstance(u, dict) and str(u.get("text") or "").strip())
    else:
        segments = group_into_segments([
            Tok(text=str(w.get("text") or ""), start=_s(w.get("start")), end=_s(w.get("end")),
                speaker=_label(w.get("speaker")), language=language)
            for w in (payload.get("words") or []) if isinstance(w, dict)])
    return Transcript(segments=segments,
                      duration=_s(payload.get("audio_duration_ms")) or _s_secs(payload),
                      model=model, provider=PROVIDER)


def _s(ms: Any) -> float:
    """Milliseconds -> seconds. The single conversion point, so it cannot be half-applied."""
    try:
        return round(float(ms) / 1000.0, 3)
    except (TypeError, ValueError):
        return 0.0


def _s_secs(payload: dict) -> float:
    """This provider also reports `audio_duration` in whole SECONDS on the completed transcript."""
    try:
        return float(payload.get("audio_duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _label(speaker: Any) -> str:
    """`A`, `B`… -> the port's anonymous form, so a human sees the same shape from every provider."""
    s = str(speaker or "").strip()
    if not s:
        return "SPEAKER_00"
    if len(s) == 1 and s.isalpha():
        return f"SPEAKER_{ord(s.upper()) - ord('A'):02d}"
    return s
