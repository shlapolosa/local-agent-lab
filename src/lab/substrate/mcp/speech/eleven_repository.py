"""The ElevenLabs speech ADAPTER — `ElevenTranscriber` satisfies `lab.core.speech.Transcriber`.

Synchronous: one multipart POST returns the whole transcript, so there is no job to poll. It is the
accuracy control in the bake-off — first on every Arabic-English pair of the only independent
code-switching benchmark — and it does NOT translate, so it answers requirement 2 and not 1.
"""
from __future__ import annotations

from lab.core.speech import (CAPABILITIES, AudioClip, SpeechError, SpeechNotConfigured,
                             SpeechUnavailable, SpeechUnsupportedMedia, Transcript)
from lab.substrate.mcp.speech import eleven_map as M
from lab.substrate.mcp.speech import refusal
from lab.substrate.mcp.speech.eleven_rest import ElevenClient, TRANSCRIBE
from lab.substrate.mcp.speech.http import ProviderError

__all__ = ["ElevenTranscriber", "SETTING", "build"]

SETTING = "ELEVENLABS_API_KEY"


class ElevenTranscriber:
    """The `Transcriber` port, served by ElevenLabs Scribe."""

    def __init__(self, client: ElevenClient) -> None:
        self._client = client

    def capabilities(self, deep: bool = False) -> dict[str, SpeechUnavailable | None]:
        if not self._client.configured:
            return {c: SpeechNotConfigured(SETTING) for c in CAPABILITIES}
        return {
            "transcription": None,
            "diarization": None,            # up to 32 speakers
            "code_switching": None,
            "timestamps": None,
            "speaker_hint": None,           # `num_speakers` — the one provider here that takes it
            "vocabulary": SpeechUnavailable(
                "vocabulary", "this provider takes no custom vocabulary on transcription",
                "spell unusual terms in the prompt of whatever reads the transcript"),
        }

    def warnings(self, languages: tuple[str, ...] = (), vocabulary: tuple[str, ...] = ()) -> tuple[str, ...]:
        if vocabulary:
            return ("custom vocabulary was dropped: this provider does not accept it",)
        return ()

    def transcribe(self, audio: AudioClip, *, languages: tuple[str, ...] = (), diarize: bool = True,
                   speaker_count: int | None = None,
                   vocabulary: tuple[str, ...] = ()) -> Transcript:
        if not self._client.configured:
            raise SpeechNotConfigured(SETTING)
        if audio.suffix not in M.ACCEPTED_MEDIA:
            raise SpeechUnsupportedMedia(audio.suffix or audio.name, M.ACCEPTED_MEDIA)
        if len(audio.data) > M.MAX_BYTES:
            raise SpeechError(f"the clip is {len(audio.data)} bytes, over this provider's "
                              f"{M.MAX_BYTES} byte limit")
        fields = M.form_fields(tuple(languages), diarize, speaker_count)
        try:
            body = self._client.post_audio(TRANSCRIBE, audio.name, audio.data, fields)
        except ProviderError as e:
            raise refusal.translate(e, setting=SETTING, accepted=M.ACCEPTED_MEDIA) from e
        return M.to_transcript(body, model=fields["model_id"], duration=audio.seconds or 0.0)


def build(*, api_key: str | None = None, base_url: str | None = None,
          transport=None, timeout: float | None = None) -> ElevenTranscriber:
    """The ONE place this adapter is assembled. Every value defaults to `lab.platform.config`."""
    from lab.platform import config
    from lab.substrate.mcp.speech.http import TIMEOUT

    def pick(given, default):
        return default if given is None else given

    return ElevenTranscriber(ElevenClient(
        api_key=pick(api_key, config.ELEVENLABS_API_KEY),
        base_url=pick(base_url, config.ELEVENLABS_BASE_URL),
        transport=transport, timeout=pick(timeout, TIMEOUT)))
