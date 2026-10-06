"""The organiser's speaker-card submission, as the approval gate's answer.

The wire shape is the one the review app and the Power Automate card already produce —
`{label: {"identity", "tag", "consent"}}` — so `Speakers.from_answer` reads one answer whichever
surface it came from. Field names are shared with those surfaces too: `identity_<label>`,
`pick_<label>`, `tag_<label>`, `consent_<label>`."""
from __future__ import annotations

from typing import Iterable

__all__ = ["from_card", "unanswered"]


def _text(data: dict, key: str) -> str:
    return str(data.get(key) or "").strip()


def from_card(data: dict, labels: Iterable[str]) -> dict[str, dict[str, str]]:
    """One entry per label the question asked about: `identity` OR `tag` (whichever was given, an
    identity winning) plus `consent`. A TYPED identity beats a picked one (a person who typed over a
    suggestion meant it), and consent is "yes" only when the toggle sent exactly that — for biometric
    data an ambiguous answer is a refusal."""
    out = {}
    for label in labels:
        identity = _text(data, f"identity_{label}") or _text(data, f"pick_{label}")
        consent = "yes" if _text(data, f"consent_{label}").lower() == "yes" else "no"
        tag = _text(data, f"tag_{label}")
        # ONLY the field given: the minutes process refuses an empty one (measured 6 Oct 2026 — the
        # answer was recorded and the minutes run was refused, so a submitted card produced nothing)
        out[label] = {"identity": identity} if identity else ({"tag": tag} if tag else {})
        out[label]["consent"] = consent
    return out


def unanswered(answer: dict[str, dict[str, str]]) -> list[str]:
    """The labels with neither an identity nor a tag — the gate refuses those, so the card says which
    instead of letting a person submit and wonder why nothing happened."""
    return [label for label, a in answer.items() if not (a.get("identity") or a.get("tag"))]
