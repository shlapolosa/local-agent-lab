"""The Soniox speech ADAPTER — `SonioxTranscriber` satisfies `lab.core.speech.Transcriber`.

The only provider in the bake-off that answers BOTH of this lab's requirements in ONE call:
diarization and Arabic->English translation together, returned as a single token stream that keeps
the speaker on the translated tokens as well as the original ones.

`want` is the adapter's own setting, not the port's: the port returns ONE transcript, and the
verbatim record and the English rendering are different artifacts. Building the adapter twice — once
for each — is how the bake-off compares them, and it keeps the port free of a vendor's idea of
a dual answer. THREE renderings are reachable (`soniox_map.WANTED`), and the middle one is the whole
point: `english` is untranslated speech plus the rendered Arabic, which is the transcript a person
reads. `translation` alone is a bake-off column, not a transcript — asking for it by mistake is what
made this lane return 21 words of a 219-word meeting.
"""
from __future__ import annotations

from lab.core.speech import (CAPABILITIES, AudioClip, SpeechError, SpeechNotConfigured,
                             SpeechUnavailable, SpeechUnsupportedMedia, Transcript)
from lab.substrate.mcp.speech import refusal
from lab.substrate.mcp.speech import soniox_map as M
from lab.substrate.mcp.speech.http import ProviderError
from lab.substrate.mcp.speech.soniox_rest import SonioxClient

__all__ = ["SonioxTranscriber", "SETTING", "build"]

SETTING = "SONIOX_API_KEY"


class SonioxTranscriber:
    """The `Transcriber` port, served by Soniox."""

    def __init__(self, client: SonioxClient, *, want: str = M.ORIGINAL, translate_to: str = "",
                 sleep=None) -> None:
        if want not in M.WANTED:
            raise SpeechError(f"want must be one of {sorted(M.WANTED)}, not {want!r}")
        if want in (M.TRANSLATION, M.ENGLISH) and not translate_to:
            # ENGLISH is untranslated speech PLUS the rendering, so it needs the rendering to exist:
            # with no target language the provider translates nothing and this mode silently
            # degrades to the verbatim record under a name that promises English.
            raise SpeechError("asking for the translation without a target language returns nothing")
        self._client, self._want, self._to, self._sleep = client, want, translate_to, sleep

    def capabilities(self, deep: bool = False) -> dict[str, SpeechUnavailable | None]:
        if not self._client.configured:
            return {c: SpeechNotConfigured(SETTING) for c in CAPABILITIES}
        return {
            "transcription": None,
            "diarization": None,
            "code_switching": None,         # plural `language_hints`, per-token language
            "timestamps": None,
            "vocabulary": None,             # `context.translation_terms`
            "speaker_hint": SpeechUnavailable(
                "speaker_hint", "this provider takes no speaker-count hint",
                "for an in-person meeting, improve the recording instead — a microphone array, "
                "speakers close and equidistant, less overlapping talk"),
        }

    def warnings(self, languages: tuple[str, ...] = (), vocabulary: tuple[str, ...] = ()) -> tuple[str, ...]:
        if self._want == M.TRANSLATION:
            return (f"these segments are a TRANSLATION into {self._to!r}, not what was said — "
                    "the verbatim record is the same run asked for its original half",)
        if self._want == M.ENGLISH:
            # Not the same warning, and the difference matters to a reader: this transcript is
            # mostly verbatim, with the spans that were spoken in another language rendered into
            # this one. Saying "this is a translation" would overstate it; saying nothing would
            # let a rendered sentence be quoted as words somebody said.
            return (f"the spans not spoken in {self._to!r} appear here RENDERED into it, not as "
                    "said — the verbatim record is the same run asked for its original half",)
        return ()

    def transcribe(self, audio: AudioClip, *, languages: tuple[str, ...] = (), diarize: bool = True,
                   speaker_count: int | None = None,
                   vocabulary: tuple[str, ...] = ()) -> Transcript:
        if not self._client.configured:
            raise SpeechNotConfigured(SETTING)
        if audio.suffix not in M.ACCEPTED_MEDIA:
            raise SpeechUnsupportedMedia(audio.suffix or audio.name, M.ACCEPTED_MEDIA)
        try:
            file_id = self._client.upload(audio.name, audio.data)
            body = M.request_body(file_id=file_id, languages=tuple(languages), diarize=diarize,
                                  translate_to=self._to)
            done = self._client.transcribe(body, terminal=M.TERMINAL, sleep=self._sleep)
        except ProviderError as e:
            raise refusal.translate(e, setting=SETTING, accepted=M.ACCEPTED_MEDIA) from e
        if done.get("status") == "error":
            raise SpeechError(str(done.get("error_message") or "the provider reported an error"))
        return M.to_transcript(done, want=self._want, duration=audio.seconds or 0.0)


def build(*, api_key: str | None = None, base_url: str | None = None, want: str = M.ORIGINAL,
          translate_to: str | None = None, transport=None, timeout: float | None = None,
          sleep=None) -> SonioxTranscriber:
    """The ONE place this adapter is assembled. Every value defaults to `lab.platform.config`."""
    from lab.platform import config
    from lab.substrate.mcp.speech.http import TIMEOUT

    def pick(given, default):
        return default if given is None else given

    return SonioxTranscriber(
        SonioxClient(api_key=pick(api_key, config.SONIOX_API_KEY),
                     base_url=pick(base_url, config.SONIOX_BASE_URL),
                     transport=transport, timeout=pick(timeout, TIMEOUT)),
        want=want, translate_to=pick(translate_to, config.SONIOX_TRANSLATE_TO), sleep=sleep)
