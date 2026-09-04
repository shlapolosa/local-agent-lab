"""MAPPER: this provider's payloads <-> `lab.core.speech`.

A domain port needs a mapper between the external model and ours, and the mapper is where
correctness lives — so it is pure, it does no I/O, and it is tested on its own apart from any
transport. Nothing here opens a socket or reads a credential.

Two properties of THIS provider drive the whole file, both established from live calls rather than
documentation:

  * **It reports no per-segment language**, even running its mixed-language model. The port wants
    the language recognised per segment so that a span rendered in the wrong language is visible.
    We therefore leave it EMPTY rather than stamping in whatever was requested, because stamping
    would manufacture false evidence of a switch and destroy the only check the port offers.
  * **The language HINT selects the model.** The port speaks languages, never model names, so
    asking for Arabic and English together is what selects the mixed model. That single mapping is
    what makes intra-sentential switching work at all.
"""
from __future__ import annotations

from typing import Any

from lab.core.speech import Segment, SpeechError, SpeechUnavailable, Transcript

__all__ = ["PROVIDER", "MODEL_DEFAULT", "MODEL_MIXED", "to_transcript", "model_for", "form_fields",
           "vocabulary_dropped", "ACCEPTED_MEDIA", "MAX_SECONDS"]

PROVIDER = "munsit"
MODEL_DEFAULT = "munsit"            # Arabic, and the only model that accepts custom vocabulary
MODEL_MIXED = "munsit-en-ar"        # Arabic + English, documented for switching WITHIN an utterance

# The engine is Arabic-first: `ar` alone, or `ar` with `en`. Anything else must fail loudly rather
# than be downgraded, because running the Arabic model on French would return confident nonsense.
SUPPORTED = frozenset({"ar", "en"})

# Verified live: posting an .mp4 is refused and the provider lists exactly these.
ACCEPTED_MEDIA = (".aac", ".amr", ".flac", ".m4a", ".m4r", ".mp2", ".mp3", ".ogg", ".opus",
                  ".wav", ".webm", ".wma")
MAX_SECONDS = 3600.0                # documented cap on a single request


def model_for(languages: tuple[str, ...]) -> str:
    """Which provider model serves this language hint. Empty hint takes the default.

    Raises `SpeechUnavailable` for a hint this engine cannot serve — a silent downgrade to the
    Arabic model would produce fluent, plausible, wrong text, which is worse than an error.
    """
    want = {(l or "").strip().lower().split("-")[0] for l in languages if (l or "").strip()}
    if not want:
        return MODEL_DEFAULT
    if not want <= SUPPORTED:
        raise SpeechUnavailable(
            "code_switching",
            f"this provider serves {sorted(SUPPORTED)}, not {sorted(want)}",
            "ask for Arabic and English, or wire an adapter for another provider")
    return MODEL_MIXED if want == {"ar", "en"} else MODEL_DEFAULT


def vocabulary_dropped(languages: tuple[str, ...], vocabulary: tuple[str, ...]) -> bool:
    """Whether custom vocabulary had to be discarded for this request.

    The provider refuses custom vocabulary together with its mixed model, so the two cannot both be
    had. The adapter prefers SWITCHING, because that is the driving requirement, and reports the
    loss through this predicate instead of failing or pretending it was applied.
    """
    return bool(vocabulary) and model_for(languages) == MODEL_MIXED


def form_fields(languages: tuple[str, ...], vocabulary: tuple[str, ...] = ()) -> dict[str, str]:
    """The multipart fields for one transcription request (the file itself is added by the caller).

    `return_timestamps` is set explicitly because it defaults OFF on the mixed model, and a
    transcript without timings cannot be diarized into a timeline or evidenced by offset.
    """
    model = model_for(languages)
    fields = {"model": model, "return_timestamps": "true"}
    if vocabulary and model != MODEL_MIXED:
        fields["hotwords"] = ",".join(v.strip() for v in vocabulary if v.strip())
    return fields


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The segment rows: the convenient merged view, else the authoritative diarization one."""
    merged = data.get("merged")
    if isinstance(merged, list):
        return [r for r in merged if isinstance(r, dict)]
    seg = (data.get("diarization") or {}).get("segments")
    return [r for r in seg if isinstance(r, dict)] if isinstance(seg, list) else []


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def to_transcript(body: dict[str, Any], model: str = "") -> Transcript:
    """One provider response -> a `Transcript`.

    Segments are SORTED, because a `Transcript` is a timeline and the provider gives no ordering
    guarantee. Segments with empty text are KEPT: an attributed but wordless span is real speaker
    time and dropping it would understate how long someone held the floor. A row with no speaker
    label is refused rather than given an invented one, because an unlabelled segment means
    diarization did not happen and that must not be hidden.
    """
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise SpeechError("the provider returned no result body")

    segments = []
    for r in _rows(data):
        speaker = str(r.get("speaker") or "").strip()
        if not speaker:
            raise SpeechError("the provider returned a segment with no speaker label — "
                              "the audio was transcribed but not diarized")
        start = _num(r.get("start"))
        end = max(start, _num(r.get("end")))
        # language is deliberately NOT set: this provider does not report one, and inventing it
        # would fabricate the very evidence the port exists to check.
        segments.append(Segment(speaker=speaker, start=start, end=end,
                                text=str(r.get("text") or "")))

    segments.sort(key=lambda s: (s.start, s.end))
    return Transcript(segments=tuple(segments), duration=_num(data.get("duration")),
                      model=model or MODEL_DEFAULT, provider=PROVIDER)
