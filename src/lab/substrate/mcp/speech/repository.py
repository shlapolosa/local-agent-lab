"""The speech ADAPTER: `MunsitTranscriber` satisfies `lab.core.speech.Transcriber`.

This is where the provider's world becomes the domain's. It holds the credential, it decides which
of the provider's models a language HINT selects, and it turns every provider status into a typed
refusal that renders as one sentence. Above it, nothing knows a vendor; below it, nothing knows the
domain.

Three behaviours here are deliberate and are the reason this class exists rather than a function:

  * **Refuse locally before paying.** A meeting recording is video and the provider takes audio; a
    real meeting outruns the per-request cap. Both are knowable from the clip, so both are refused
    without an upload rather than after a slow, expensive failure.
  * **Never quietly give less than was asked.** This provider will not accept custom vocabulary
    together with its mixed-language model. Switching wins, because it is the driving requirement —
    but the caller is TOLD through `warnings()`, because silently dropping what someone asked for is
    how trust in an integration dies.
  * **Report what it cannot do.** `capabilities()` names the missing speaker-count hint outright.
    For an in-person meeting on one microphone that is the best lever there is, and its absence has
    to be visible rather than discovered.
"""
from __future__ import annotations

from lab.core.speech import (CAPABILITIES, AudioClip, SpeechError, SpeechNotConfigured,
                             SpeechThrottled, SpeechTooLong, SpeechUnavailable,
                             SpeechUnsupportedMedia, Transcript)
from lab.substrate.mcp.speech import munsit_map as M
from lab.substrate.mcp.speech.munsit_rest import DIARIZE, TRANSCRIBE, MunsitClient, MunsitError

__all__ = ["MunsitTranscriber", "SETTING"]

SETTING = "MUNSIT_API_KEY"          # what an operator sets; the only place the name appears


class MunsitTranscriber:
    """The `Transcriber` port, served by this provider. Wired by the composition root, nowhere else."""

    def __init__(self, client: MunsitClient) -> None:
        self._client = client

    # ------------------------------------------------------------------ what it can do
    def capabilities(self, deep: bool = False) -> dict[str, SpeechUnavailable | None]:
        """One entry per `CAPABILITIES`, `None` when available. Reports, never raises.

        `deep` is accepted for the port's sake and currently changes nothing: every live call to
        this provider costs credits and uploads audio, so there is no cheap probe to make. Saying so
        is better than pretending a shallow answer was verified.
        """
        if not self._client.configured:
            return {c: SpeechNotConfigured(SETTING) for c in CAPABILITIES}
        return {
            "transcription": None,
            "diarization": None,
            "code_switching": None,     # a dedicated mixed-language model; the driving requirement
            "timestamps": None,
            "vocabulary": None,         # available, but not together with the mixed model — warnings()
            "speaker_hint": SpeechUnavailable(
                "speaker_hint",
                "this provider takes no speaker-count hint",
                "for an in-person meeting, improve the recording instead — a microphone array, "
                "speakers close and equidistant, less overlapping talk"),
        }

    def warnings(self, languages: tuple[str, ...] = (), vocabulary: tuple[str, ...] = ()) -> tuple[str, ...]:
        """What this request will not honour, in the caller's terms. Empty when nothing was lost."""
        if M.vocabulary_dropped(tuple(languages), tuple(vocabulary)):
            return ("custom vocabulary was dropped: this provider does not accept it together with "
                    "the mixed-language model, and mixed-language transcription was preferred",)
        return ()

    # ------------------------------------------------------------------ the work
    def transcribe(self, audio: AudioClip, *, languages: tuple[str, ...] = (), diarize: bool = True,
                   speaker_count: int | None = None,
                   vocabulary: tuple[str, ...] = ()) -> Transcript:
        """Transcribe one clip. `speaker_count` is accepted and ignored — see `capabilities()`."""
        if not self._client.configured:
            raise SpeechNotConfigured(SETTING)
        if audio.suffix not in M.ACCEPTED_MEDIA:
            # Known locally, so never uploaded: a meeting recording is video and this is where that
            # is caught, with the extraction step named by the caller's own error text.
            raise SpeechUnsupportedMedia(audio.suffix or audio.name, M.ACCEPTED_MEDIA)
        if audio.seconds and audio.seconds > M.MAX_SECONDS:
            raise SpeechTooLong(audio.seconds, M.MAX_SECONDS)

        languages = tuple(languages)
        fields = M.form_fields(languages, tuple(vocabulary))      # raises for an unservable hint
        try:
            body = self._client.post_audio(DIARIZE if diarize else TRANSCRIBE,
                                           audio.name, audio.data, fields)
        except MunsitError as e:
            raise _translate(e) from e
        return M.to_transcript(body, model=fields["model"])


def _translate(e: MunsitError) -> SpeechError:
    """Provider status -> the domain's typed refusal, each carrying the provider's own words.

    A caller chasing a failure needs the status and the message, so they are quoted rather than
    swallowed; what never happens is a bare status with no sentence explaining it.
    """
    message = e.message or "no message"
    if e.status == 429:
        return SpeechThrottled("transcription", e.retry_after)
    if e.status in (401, 403):
        return SpeechUnavailable("transcription", f"the provider refused the credential ({message})",
                                 f"check {SETTING} and that the account is active")
    if e.status == 400 and "unsupported audio format" in message.lower():
        return SpeechUnsupportedMedia(message, M.ACCEPTED_MEDIA)
    return SpeechError(f"the speech provider failed ({e.status}): {message}")


def build(*, api_key: str | None = None, base_url: str | None = None,
          transport=None, timeout: float | None = None) -> MunsitTranscriber:
    """The ONE place this adapter is assembled — what a composition root names. Every value defaults
    to `lab.platform.config` (the single env reader) and can be overridden for a test or a second
    account; nothing below this function reads configuration."""
    from lab.platform import config
    from lab.substrate.mcp.speech.munsit_rest import TIMEOUT

    def pick(given, default):
        return default if given is None else given

    return MunsitTranscriber(MunsitClient(
        api_key=pick(api_key, config.MUNSIT_API_KEY),
        base_url=pick(base_url, config.MUNSIT_BASE_URL),
        transport=transport, timeout=pick(timeout, TIMEOUT)))
