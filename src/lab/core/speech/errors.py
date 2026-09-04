"""Why a transcription did not happen — TYPED, so the caller can say a SENTENCE.

Mirrors `lab.core.collab.errors` deliberately: one shape for every refusal, so an MCP tool result, a
log line and a capability table all render it identically. A provider says "no" for reasons that are
administratively distinct and that a human can act on, and collapsing them into an opaque status is
what makes an integration miserable to operate.

Two of these are not generic politeness — they are failures this lab has actually hit. A meeting
recording is video and a speech provider takes audio only, and a provider caps how long a single
request may be while a real meeting runs longer. Both are the caller's problem to solve and both
must name exactly what is wrong.

Nothing here knows a provider. The adapter supplies the prose; this module guarantees the shape.
"""
from __future__ import annotations

__all__ = ["SpeechError", "SpeechUnavailable", "SpeechNotConfigured", "SpeechThrottled",
           "SpeechUnsupportedMedia", "SpeechTooLong"]


def _sentence(head: str, tail: str = "") -> str:
    """One sentence, punctuated exactly once however the adapter wrote its prose."""
    out = head.strip().rstrip(".") + "."
    return f"{out} Remedy: {tail.strip().rstrip('.')}." if tail.strip() else out


class SpeechError(Exception):
    """Base of every transcription failure — catch this for "the provider did not answer"."""

    capability: str = ""

    @property
    def sentence(self) -> str:
        return str(self)

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "sentence": self.sentence}


class SpeechUnavailable(SpeechError):
    """A capability the port declares which THIS provider or plan will not serve.

    `capability` is one of `port.CAPABILITIES`, `reason` is why in the adapter's words, `remedy` is
    the step that would fix it. A capability probe RETURNS these rather than raising, so one call
    reports the whole table.
    """

    def __init__(self, capability: str, reason: str, remedy: str = "") -> None:
        if not (capability or "").strip():
            raise ValueError("an unavailable capability must name the capability")
        self.capability, self.reason = capability.strip(), reason.strip()
        self.remedy = (remedy or "").strip()
        super().__init__(_sentence(f"{self.capability} is unavailable: {self.reason}", self.remedy))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "reason": self.reason, "remedy": self.remedy,
                "sentence": self.sentence}


class SpeechNotConfigured(SpeechUnavailable):
    """The LAB's own side is missing, so nothing was attempted. A kind of `SpeechUnavailable` on
    purpose: one renderer handles both, and the difference stays visible in the sentence."""

    def __init__(self, setting: str, remedy: str = "") -> None:
        super().__init__("configuration", f"{setting} is not configured",
                         remedy or f"set {setting} for the speech service")


class SpeechUnsupportedMedia(SpeechError):
    """The audio is in a container the provider will not take.

    Real and load-bearing: a meeting recording arrives as video, and a speech provider takes audio
    only, so the pipeline needs an extraction step. Naming BOTH what was given and what is accepted
    is what turns that from a mystery into a one-line fix.
    """

    capability = "transcription"

    def __init__(self, given: str, accepted: tuple[str, ...] = ()) -> None:
        self.given, self.accepted = given, tuple(accepted)
        allowed = f"accepted: {', '.join(self.accepted)}" if self.accepted else ""
        super().__init__(_sentence(f"{given!r} is not an audio format this provider accepts", allowed))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "given": self.given,
                "accepted": list(self.accepted), "sentence": self.sentence}


class SpeechTooLong(SpeechError):
    """The audio is longer than one request may carry.

    The caller must split it, and splitting is not free: speaker labels are assigned PER REQUEST by
    every provider we surveyed, so the same person can be a different label in each piece. Whoever
    chunks also owns re-linking them.
    """

    capability = "transcription"

    def __init__(self, seconds: float, limit: float) -> None:
        self.seconds, self.limit = float(seconds), float(limit)
        super().__init__(_sentence(
            f"the audio is {self.seconds:.0f} s, longer than the {self.limit:.0f} s this provider accepts",
            "split it into shorter pieces, and re-link the speaker labels across the boundary"))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "seconds": self.seconds, "limit": self.limit,
                "sentence": self.sentence}


class SpeechThrottled(SpeechError):
    """The provider asked us to back off. `retry_after` is its hint in seconds, when it gave one."""

    def __init__(self, capability: str, retry_after: float | None = None) -> None:
        self.capability, self.retry_after = capability, retry_after
        when = f"retry in {retry_after} s" if retry_after is not None else "retry later"
        super().__init__(_sentence(f"{capability} is throttled by the provider: {when}"))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "retry_after": self.retry_after,
                "sentence": self.sentence}
