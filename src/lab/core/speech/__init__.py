"""The SPEECH bounded context: recorded talk becoming attributable words.

One import for the whole port — the value objects (`model`), the typed refusals (`errors`) and the
`Transcriber` Protocol (`port`). Pure domain: it names no provider and imports nothing outside
itself, so an adapter for any speech provider satisfies it and only the composition root learns
which one is wired.
"""
from lab.core.speech.errors import (SpeechError, SpeechNotConfigured, SpeechThrottled,
                                    SpeechTooLong, SpeechUnavailable, SpeechUnsupportedMedia)
from lab.core.speech.model import MAX_SAMPLES, AudioClip, Segment, SpeakerStat, Transcript
from lab.core.speech.port import CAPABILITIES, Transcriber

__all__ = ["Transcriber", "CAPABILITIES",
           "AudioClip", "Segment", "SpeakerStat", "Transcript", "MAX_SAMPLES",
           "SpeechError", "SpeechUnavailable", "SpeechNotConfigured", "SpeechThrottled",
           "SpeechUnsupportedMedia", "SpeechTooLong"]
