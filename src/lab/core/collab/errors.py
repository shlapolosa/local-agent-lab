"""Why a collaboration capability did not answer — TYPED, so the caller can say a SENTENCE.

A collaboration provider answers "no" for reasons that are administratively distinct and that a
human can act on: the app was never granted the permission, the lab was never configured with a
credential, or the provider is asking us to slow down. Collapsing all three into an opaque `403`
is what makes such an integration miserable to operate, so each is its own type and each renders
one sentence: WHAT is unavailable, WHY, and WHAT TO DO about it.

Nothing here knows a provider. An adapter supplies the prose ("the app has no meeting-recording
grant", "ask an administrator to grant it and re-run the probe"); this module only guarantees the
shape, so every surface — an MCP tool result, a log line, a capability table — renders it the same
way. `to_dict()` is that surface's JSON form.
"""
from __future__ import annotations

__all__ = ["CollabError", "CollabUnavailable", "CollabNotConfigured", "CollabThrottled"]


def _sentence(head: str, tail: str = "") -> str:
    """One sentence, punctuated exactly once however the adapter wrote its prose."""
    out = head.strip().rstrip(".") + "."
    return f"{out} Remedy: {tail.strip().rstrip('.')}." if tail.strip() else out


class CollabError(Exception):
    """Base of every collaboration failure — catch this to handle "the provider did not answer".

    Every subclass exposes `sentence` (what a human is told) and `to_dict()` (what a tool returns).
    """

    capability: str = ""

    @property
    def sentence(self) -> str:
        return str(self)

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "sentence": self.sentence}


class CollabUnavailable(CollabError):
    """A capability the port declares, which THIS provider/tenant will not serve right now.

    `capability` is the area that failed (one of `port.CAPABILITIES`), `reason` is why in the
    adapter's own words, and `remedy` is the administrative step that would fix it — the missing
    grant, the policy that has to be applied, the switch that is off. A capability probe returns
    these as values rather than raising them, so one call can report the whole table.
    """

    def __init__(self, capability: str, reason: str, remedy: str = "") -> None:
        if not (capability or "").strip():
            raise ValueError("an unavailable capability must name the capability")
        self.capability, self.reason, self.remedy = capability.strip(), reason.strip(), (remedy or "").strip()
        super().__init__(_sentence(f"{self.capability} is unavailable: {self.reason}", self.remedy))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "reason": self.reason, "remedy": self.remedy,
                "sentence": self.sentence}


class CollabNotConfigured(CollabUnavailable):
    """The LAB's own side is missing — no credential, no endpoint — so nothing was even attempted.

    Deliberately a kind of `CollabUnavailable`: a caller that renders one renders both, and the
    difference (our configuration vs the tenant's grant) is visible in the sentence.
    """

    def __init__(self, setting: str, remedy: str = "") -> None:
        super().__init__("configuration", f"{setting} is not configured",
                         remedy or f"set {setting} for the collaboration service")


class CollabThrottled(CollabError):
    """The provider asked us to back off. `retry_after` is its hint in seconds, when it gave one."""

    def __init__(self, capability: str, retry_after: float | None = None) -> None:
        self.capability, self.retry_after = capability, retry_after
        when = f"retry in {retry_after} s" if retry_after is not None else "retry later"
        super().__init__(_sentence(f"{capability} is throttled by the provider: {when}"))

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "retry_after": self.retry_after, "sentence": self.sentence}
