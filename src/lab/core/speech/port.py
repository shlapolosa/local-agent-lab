"""`Transcriber` — the DOMAIN port for speech: turning recorded talk into attributable words.

A DOMAIN port states what the domain needs in the domain's own words and imports nothing. A concrete
provider is an ADAPTER living where its credentials do (the substrate, as an MCP server), with a
MAPPER translating that provider's payload into `model.py`; only the composition root names one. So
this file is a `Protocol` and nothing else: nothing to inherit, structural typing, so a test double
is a plain object and an adapter is free of us.

Four properties every implementation must honour:

  * **Languages are a HINT, plural.** `languages` says what is expected, never what it must be.
    Declaring a single language is the thing that breaks mid-sentence switching, and it is also the
    documented way to make some engines actively worse, so the port refuses to offer it.
  * **The recognised language comes back per segment.** Without it, a span rendered in the wrong
    language — or translated, or transliterated — is indistinguishable from a correct answer.
  * **Speaker labels are ANONYMOUS and per request.** `SPEAKER_00` means nothing beyond this call,
    and it is not stable across two calls. Mapping a label to a human is a separate, human-gated
    act, and re-linking labels across a split recording belongs to whoever split it.
  * **A refusal is typed.** Anything the provider will not do raises (or, from `capabilities()`,
    RETURNS) a `SpeechUnavailable` naming the capability, the reason and the remedy.

Summarisation is deliberately ABSENT. This port returns words and speaker labels; minutes, decisions
and keywords are produced by the lab's own governed model. Keeping that out of the port is what makes
"the vendor does not summarise our meetings" structural rather than a promise in a document.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from lab.core.speech.errors import SpeechUnavailable
from lab.core.speech.model import Transcript

__all__ = ["CAPABILITIES", "Transcriber"]

# The areas a probe reports on, one per thing a provider grants, prices or simply lacks.
# `code_switching` is first-class because it is this lab's driving requirement, and because it is
# routinely absent from a provider's own capability surface even when a model for it exists.
CAPABILITIES: tuple[str, ...] = ("transcription", "diarization", "code_switching", "timestamps",
                                 "vocabulary", "speaker_hint")


@runtime_checkable
class Transcriber(Protocol):
    """What the domain needs from a speech provider. Implementations are adapters."""

    def capabilities(self, deep: bool = False) -> dict[str, SpeechUnavailable | None]:
        """What this provider and plan will actually serve: one key per `CAPABILITIES` entry, mapped
        to `None` when available or to the `SpeechUnavailable` explaining why not. It REPORTS rather
        than raises, so one call renders the whole table. `deep=True` additionally makes one cheap
        live call per area, which catches a capability that is documented but not enabled."""

    def transcribe(self, audio, *, languages: tuple[str, ...] = (), diarize: bool = True,
                   speaker_count: int | None = None,
                   vocabulary: tuple[str, ...] = ()) -> Transcript:
        """Transcribe `audio`, returning segments with anonymous speaker labels and, where the
        provider reports it, the language recognised for each.

        `audio` is a readable binary stream or bytes with a name, never a path and never a URL: the
        adapter holds the credential and the workload holds only a reference.

        `languages` is the expected set as a HINT — for example Arabic and English together for a
        meeting that mixes them mid-sentence. Empty means let the provider decide.

        `speaker_count`, when known, helps an in-person recording where one device captured a room;
        providers that ignore it must still accept it rather than fail.

        `vocabulary` biases toward names a general model will not know. Note that some providers
        refuse it together with a code-switching model, in which case the adapter must prefer
        switching and say so through `capabilities()` rather than failing the call.

        Raises `SpeechUnsupportedMedia`, `SpeechTooLong`, `SpeechThrottled`, `SpeechUnavailable` or
        `SpeechNotConfigured` — never an opaque status code.
        """
