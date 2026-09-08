"""Provider status -> the domain's typed refusal. One rule set, four providers.

Every adapter here needs the same translation and each one differs only in which setting names its
credential and which media it accepts. Writing it once means a new provider inherits the behaviour
that matters: the provider's OWN words are quoted rather than swallowed, because a caller chasing a
failure needs the sentence, not a bare status.
"""
from __future__ import annotations

from lab.core.speech import (SpeechError, SpeechThrottled, SpeechUnavailable,
                             SpeechUnsupportedMedia)
from lab.substrate.mcp.speech.http import ProviderError

__all__ = ["translate"]


def translate(e: ProviderError, *, setting: str, accepted: tuple[str, ...],
              capability: str = "transcription") -> SpeechError:
    message = e.message or "no message"
    if e.status == 429:
        return SpeechThrottled(capability, e.retry_after)
    if e.status in (401, 403):
        return SpeechUnavailable(capability, f"the provider refused the credential ({message})",
                                 f"check {setting} and that the account is active")
    if e.status in (400, 415) and _about_media(message):
        return SpeechUnsupportedMedia(message, accepted)
    if e.status == 0 and e.code == "timeout":
        return SpeechError(f"the speech provider did not finish: {message}")
    return SpeechError(f"the speech provider failed ({e.status}): {message}")


def _about_media(message: str) -> bool:
    low = message.lower()
    return any(w in low for w in ("audio format", "unsupported", "codec", "media type",
                                 "file type", "cannot decode"))
