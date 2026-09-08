"""MAPPER: Soniox payloads -> `lab.core.speech`. Pure; no I/O, no credential.

This is the only provider in the bake-off that answers BOTH of the lab's requirements in ONE call:
`enable_speaker_diarization` together with `translation: {type: one_way, target_language: en}`
returns a single token stream carrying the original speech AND its translation, with the `speaker`
field preserved on both, distinguished by `translation_status`.

That unified stream is why this mapper has a `want` selector rather than returning one fixed thing.
The domain port returns ONE transcript, and the two halves are genuinely different artifacts: the
original is the verbatim audit record, the translation is what minutes should be written from. So
the adapter asks for the half it wants, and the bake-off runs this provider twice — once verbatim,
once English — and compares them as two entries. No port change, and the run keeps both.
"""
from __future__ import annotations

from typing import Any

from lab.core.speech import SpeechError, Transcript
from lab.substrate.mcp.speech.tokenmap import Tok, group_into_segments

__all__ = ["PROVIDER", "MODEL_DEFAULT", "to_transcript", "request_body", "ORIGINAL", "TRANSLATION",
           "TERMINAL", "ACCEPTED_MEDIA"]

PROVIDER = "soniox"
MODEL_DEFAULT = "stt-async-v5"
ORIGINAL, TRANSLATION = "original", "translation"
TERMINAL = {"completed", "error"}
ACCEPTED_MEDIA = (".aac", ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".wav",
                  ".webm")


def request_body(file_id: str = "", audio_url: str = "", languages: tuple[str, ...] = (),
                 diarize: bool = True, translate_to: str = "") -> dict:
    """The create-transcription payload.

    `language_hints` takes the WHOLE hint, plural — this provider is one of the few that accepts a
    list, which is exactly what the port promises and what makes mid-sentence switching work.
    """
    if bool(file_id) == bool(audio_url):
        raise SpeechError("give this provider a file id or an audio url, not both and not neither")
    body: dict[str, Any] = {"model": MODEL_DEFAULT,
                            "enable_speaker_diarization": bool(diarize)}
    body["file_id" if file_id else "audio_url"] = file_id or audio_url
    hints = [l.strip().lower().split("-")[0] for l in languages if (l or "").strip()]
    if hints:
        body["language_hints"] = sorted(set(hints))
    if translate_to:
        body["translation"] = {"type": "one_way", "target_language": translate_to}
    return body


def to_transcript(payload: Any, want: str = ORIGINAL, model: str = MODEL_DEFAULT,
                  duration: float = 0.0) -> Transcript:
    """One half of the unified token stream -> a domain `Transcript`.

    `want=ORIGINAL` keeps what was actually said; `want=TRANSLATION` keeps the rendering. A token
    with no `translation_status` is original — an untranslated run must not vanish from the verbatim
    record just because the provider left the field off.
    """
    if not isinstance(payload, dict):
        raise SpeechError(f"unexpected response from {PROVIDER}: {type(payload).__name__}")
    toks = []
    for t in payload.get("tokens") or []:
        if not isinstance(t, dict):
            continue
        if (str(t.get("translation_status") or ORIGINAL) == TRANSLATION) != (want == TRANSLATION):
            continue
        toks.append(Tok(text=str(t.get("text") or ""),
                        start=_s(t, "start_ms", "start"), end=_s(t, "end_ms", "end"),
                        speaker=_label(t.get("speaker")),
                        language=str(t.get("language") or "")))
    segments = group_into_segments(toks)
    return Transcript(segments=segments,
                      duration=duration or _num(payload.get("audio_duration_ms")) / 1000.0
                      or round(max((s.end for s in segments), default=0.0), 3),
                      model=model, provider=f"{PROVIDER}-{want}")


def _s(tok: dict, ms_key: str, s_key: str) -> float:
    """Milliseconds when the provider sends them, seconds when it sends those — one place, so the
    two cannot be mixed inside one transcript."""
    if tok.get(ms_key) is not None:
        return round(_num(tok.get(ms_key)) / 1000.0, 3)
    return round(_num(tok.get(s_key)), 3)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _label(speaker: Any) -> str:
    s = str(speaker or "").strip()
    if not s:
        return "SPEAKER_00"
    return f"SPEAKER_{int(s):02d}" if s.isdigit() else s
