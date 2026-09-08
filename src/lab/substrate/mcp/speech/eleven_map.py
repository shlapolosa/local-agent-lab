"""MAPPER: ElevenLabs Scribe payloads -> `lab.core.speech`. Pure; no I/O, no credential.

Why this provider is in the bake-off: the only INDEPENDENT benchmark of code-switched Arabic-English
(arXiv 2605.19069, May 2026) puts Scribe v2 first on all four language pairs — 13.2% WER against
38.6% for the next system — including Egyptian and Gulf Arabic.

Two shape facts drive this file:
  * The answer is a flat WORD stream, not segments. Speaker turns are recovered by grouping on
    `speaker_id` (`tokenmap`), and entries typed `spacing` or `audio_event` are not speech.
  * The language is detected ONCE for the whole file, not per segment. It is therefore NOT stamped
    onto segments: a whole-file label copied down would assert that every segment was that language
    and make `code_switched` read False for a meeting that switched throughout — manufacturing
    exactly the false negative the port exists to prevent.
"""
from __future__ import annotations

from typing import Any

from lab.core.speech import SpeechError, Transcript
from lab.substrate.mcp.speech.tokenmap import Tok, group_into_segments

__all__ = ["PROVIDER", "MODEL_DEFAULT", "to_transcript", "form_fields", "ACCEPTED_MEDIA",
           "MAX_BYTES"]

PROVIDER = "elevenlabs"
MODEL_DEFAULT = "scribe_v2"
SPEECH_TYPES = {"word"}                 # 'spacing' is layout; 'audio_event' is laughter, not speech
ACCEPTED_MEDIA = (".aac", ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".wav",
                  ".webm")               # this provider accepts video containers too
MAX_BYTES = 5 * 1024 ** 3               # documented 5 GB cap
MAX_SPEAKERS = 32


def form_fields(languages: tuple[str, ...] = (), diarize: bool = True,
                speaker_count: int | None = None) -> dict[str, str]:
    """The multipart text fields for one request.

    A single `language_code` is sent ONLY when exactly one language is expected. Declaring one
    language for a bilingual meeting is the documented way to make a switching engine worse, and
    the port's whole contract is that `languages` is a plural hint — so several hints mean: detect.
    """
    fields = {"model_id": MODEL_DEFAULT, "diarize": "true" if diarize else "false",
              "timestamps_granularity": "word", "tag_audio_events": "false"}
    want = [l.strip().lower().split("-")[0] for l in languages if (l or "").strip()]
    if len(set(want)) == 1:
        fields["language_code"] = want[0]
    if speaker_count:
        fields["num_speakers"] = str(min(int(speaker_count), MAX_SPEAKERS))
    return fields


def to_transcript(payload: Any, model: str = MODEL_DEFAULT, duration: float = 0.0) -> Transcript:
    """One Scribe response -> a domain `Transcript`."""
    if not isinstance(payload, dict):
        raise SpeechError(f"unexpected response from {PROVIDER}: {type(payload).__name__}")
    words = payload.get("words") or []
    toks = [Tok(text=str(w.get("text") or ""),
                start=float(w.get("start") or 0.0), end=float(w.get("end") or 0.0),
                speaker=str(w.get("speaker_id") or ""))
            for w in words if isinstance(w, dict) and w.get("type", "word") in SPEECH_TYPES]
    segments = group_into_segments(toks)
    if not segments and str(payload.get("text") or "").strip():
        # text but no usable word stream: keep the words rather than return an empty transcript
        segments = group_into_segments([Tok(str(payload["text"]), 0.0, duration)])
    return Transcript(segments=segments, duration=duration or _span(segments),
                      model=model, provider=PROVIDER)


def _span(segments) -> float:
    return round(max((s.end for s in segments), default=0.0), 3)
