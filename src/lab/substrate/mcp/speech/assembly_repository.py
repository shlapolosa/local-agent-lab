"""The AssemblyAI speech ADAPTER — `AssemblyTranscriber` satisfies `lab.core.speech.Transcriber`.

Asynchronous: upload, submit, poll. In the bake-off as the diarization control — diarization solved
jointly with transcription across 95 languages — and it does NOT translate, so like ElevenLabs it
answers requirement 2 only.
"""
from __future__ import annotations

from lab.core.speech import (CAPABILITIES, AudioClip, SpeechNotConfigured, SpeechUnavailable,
                             SpeechUnsupportedMedia, Transcript)
from lab.substrate.mcp.speech import assembly_map as M
from lab.substrate.mcp.speech import refusal
from lab.substrate.mcp.speech.assembly_rest import AssemblyClient
from lab.substrate.mcp.speech.http import ProviderError

__all__ = ["AssemblyTranscriber", "SETTING", "build"]

SETTING = "ASSEMBLYAI_API_KEY"


class AssemblyTranscriber:
    """The `Transcriber` port, served by AssemblyAI."""

    def __init__(self, client: AssemblyClient, sleep=None) -> None:
        self._client = client
        self._sleep = sleep

    def capabilities(self, deep: bool = False) -> dict[str, SpeechUnavailable | None]:
        if not self._client.configured:
            return {c: SpeechNotConfigured(SETTING) for c in CAPABILITIES}
        return {
            "transcription": None,
            "diarization": None,
            "timestamps": None,
            "speaker_hint": None,               # `speakers_expected`
            "vocabulary": None,                 # word boost, on the same submit
            "code_switching": SpeechUnavailable(
                "code_switching",
                "this provider detects a dominant language per file; its documented code-switching "
                "strength is English with Spanish or German, not Arabic",
                "compare it against a provider with a mixed-language model before relying on it "
                "for an Arabic meeting"),
        }

    def warnings(self, languages: tuple[str, ...] = (), vocabulary: tuple[str, ...] = ()) -> tuple[str, ...]:
        want = {(l or "").strip().lower().split("-")[0] for l in languages if (l or "").strip()}
        if len(want) > 1:
            return ("this provider detects ONE dominant language per file: a span in the other "
                    "language may come back transcribed as the dominant one",)
        return ()

    def transcribe(self, audio: AudioClip, *, languages: tuple[str, ...] = (), diarize: bool = True,
                   speaker_count: int | None = None,
                   vocabulary: tuple[str, ...] = ()) -> Transcript:
        if not self._client.configured:
            raise SpeechNotConfigured(SETTING)
        if audio.suffix not in M.ACCEPTED_MEDIA:
            raise SpeechUnsupportedMedia(audio.suffix or audio.name, M.ACCEPTED_MEDIA)
        try:
            url = self._client.upload(audio.data)
            body = M.request_body(url, tuple(languages), diarize, speaker_count)
            if vocabulary:
                body["word_boost"] = list(vocabulary)
            done = self._client.transcribe(body, terminal=M.TERMINAL, sleep=self._sleep)
        except ProviderError as e:
            raise refusal.translate(e, setting=SETTING, accepted=M.ACCEPTED_MEDIA) from e
        return M.to_transcript(done)


def build(*, api_key: str | None = None, base_url: str | None = None,
          transport=None, timeout: float | None = None, sleep=None) -> AssemblyTranscriber:
    """The ONE place this adapter is assembled. Every value defaults to `lab.platform.config`."""
    from lab.platform import config
    from lab.substrate.mcp.speech.http import TIMEOUT

    def pick(given, default):
        return default if given is None else given

    return AssemblyTranscriber(AssemblyClient(
        api_key=pick(api_key, config.ASSEMBLYAI_API_KEY),
        base_url=pick(base_url, config.ASSEMBLYAI_BASE_URL),
        transport=transport, timeout=pick(timeout, TIMEOUT)), sleep=sleep)
