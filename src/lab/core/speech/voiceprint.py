"""Voiceprints — recognising a voice the lab has met before. Pure rules: no model, no store, no I/O.

WHAT A VOICEPRINT IS. A speaker-embedding model turns a few seconds of someone's voice into a short
vector; two recordings of one person land close together, two people land apart. This module never
sees audio or a model. It is handed vectors (from `SpeakerEmbedder`) and stored voiceprints (from
`VoiceprintGallery`), and it decides three things: which label sounds like whom, which vectors may be
trusted to speak for a label, and which answers may be kept.

EVERY NUMBER HERE WAS MEASURED, not chosen — ECAPA-TDNN on a real three-person meeting recorded on one
laptop microphone, 29 Sep 2026 (docs/speech-voiceprint-gallery.md):
  * THRESHOLD 0.40 — at this score no line was ever given the wrong person, including when the real
    speaker was absent from the gallery. Below it a suggestion is withheld and the human answers.
    The threshold is tuned against FALSE ACCEPTS, not for recall: a miss costs the organiser one
    question, a wrong name puts words and decisions in the wrong mouth.
  * PURITY_FLOOR 0.25 — a diarizer label MIXES people (the approved attribution of that meeting was
    right for only ~half its words). A segment that does not sound like the rest of its label is
    dropped before the label is matched or stored, or one person would be enrolled with another's voice.
  * MIN_IDENTIFY_S 3 / MIN_ENROL_S 5 — below a few seconds an embedding is mostly noise; pooling
    ≥5 s gave 100 % correct identification. Storing needs more than suggesting, because a bad
    voiceprint is permanent and a bad suggestion is one click.

CONSENT IS PART OF THE DATA. A voiceprint is biometric data. It is stored only when the organiser
ticks consent for that person, and it records who attested it (`consented_by`). Naming someone is not
their consent, so the two are separate fields on the card and separate checks here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from lab.core.meetings.model import Speakers

__all__ = ["Voiceprint", "Suggestion", "SpeakerEmbedder", "VoiceprintGallery", "KINDS", "THRESHOLD",
           "PURITY_FLOOR", "MIN_IDENTIFY_S", "MIN_ENROL_S", "unit", "cosine", "centroid", "purify",
           "identify", "to_enrol", "enrolment", "key_of"]

KINDS = ("identity", "tag")          # the two shapes an answer takes; a voiceprint is keyed the same way
THRESHOLD = 0.40
PURITY_FLOOR = 0.25
MIN_IDENTIFY_S = 3.0
MIN_ENROL_S = 5.0

Vector = tuple[float, ...]
Sample = tuple[Vector, float]        # one segment's embedding and how many seconds of speech made it


def unit(v: Sequence[float]) -> Vector:
    n = math.sqrt(sum(x * x for x in v))
    if not n:
        raise ValueError("a zero vector has no direction — it cannot be a voice")
    return tuple(x / n for x in v)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(unit(a), unit(b)))


def centroid(vectors: Sequence[Sequence[float]]) -> Vector:
    return unit([sum(col) / len(vectors) for col in zip(*vectors)])


def key_of(kind: str, key: str) -> str:
    """One person, one key: a directory identity is an address and compares case-insensitively; a tag
    is what the organiser typed and keeps its spelling, compared without case."""
    return key.strip().lower() if kind == "identity" else key.strip()


@dataclass(frozen=True)
class Voiceprint:
    """One stored vector for one person, from one enrolment."""

    kind: str                          # "identity" | "tag"
    key: str
    vector: Vector
    model: str                         # vectors compare only within the model that made them
    consented_by: str                  # who attested this person's consent — the audit trail
    source: str = ""                   # the approval that released it
    seconds: float = 0.0               # how much clean speech it was built from
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"a voiceprint is keyed by one of {KINDS}, not {self.kind!r}")
        if not (self.key or "").strip():
            raise ValueError("a voiceprint needs the key it belongs to")
        if not (self.model or "").strip():
            raise ValueError("a voiceprint needs the model that made it — vectors from two models do not compare")
        if not (self.consented_by or "").strip():
            raise ValueError("a voiceprint must record who attested consent — it is biometric data")
        object.__setattr__(self, "key", key_of(self.kind, self.key))
        object.__setattr__(self, "vector", unit(self.vector))


@dataclass(frozen=True)
class Suggestion:
    """Who a label sounds like, and how sure. A SUGGESTION: the organiser confirms or corrects it."""

    kind: str
    key: str
    score: float
    display: str = field(default="")

    def __post_init__(self) -> None:
        if not self.display:
            object.__setattr__(self, "display", self.key if self.kind == "tag" else self.key.split("@")[0])

    def to_dict(self) -> dict:
        """The answer shape a card prefills — `identity` or `tag`, exactly as the human would type it."""
        return {self.kind: self.key, "display": self.display, "score": round(self.score, 2)}


class SpeakerEmbedder(Protocol):
    """Audio clips (16 kHz mono WAV bytes) in, one unit vector per clip out."""

    model: str

    def embed(self, clips: Sequence[bytes]) -> list[Vector]: ...


class VoiceprintGallery(Protocol):
    """Where voiceprints are kept. Vectors only — never audio."""

    def voiceprints(self, model: str) -> list[Voiceprint]: ...

    def add(self, voiceprint: Voiceprint) -> None: ...


def purify(samples: Sequence[Sample], floor: float = PURITY_FLOOR) -> list[Sample]:
    """The segments that sound like the rest of their label.

    LEAVE-ONE-OUT: each segment is judged against the centroid of the OTHERS. Judging it against a
    centroid it helped build lets an outlier vote for itself — with three segments one intruder
    drags the shared centroid ~30° towards its own voice and survives (the first version did exactly
    that, and a test caught it)."""
    if len(samples) < 2:
        return list(samples)
    return [s for i, s in enumerate(samples)
            if cosine(s[0], centroid([v for j, (v, _) in enumerate(samples) if j != i])) >= floor]


def _profiles(gallery: Sequence[Voiceprint], model: str) -> dict[tuple[str, str], Vector]:
    """One average voice per person, from every voiceprint of THIS model."""
    grouped: dict[tuple[str, str], list[Vector]] = {}
    for vp in gallery:
        if vp.model == model:
            grouped.setdefault((vp.kind, vp.key), []).append(vp.vector)
    return {k: centroid(vs) for k, vs in grouped.items()}


def _speech(samples: Sequence[Sample]) -> float:
    return sum(s for _, s in samples)


def identify(labels: dict[str, Sequence[Sample]], gallery: Sequence[Voiceprint], *, model: str = "m1",
             threshold: float = THRESHOLD, min_seconds: float = MIN_IDENTIFY_S) -> dict[str, Suggestion | None]:
    """A suggestion per label, or None. Every label is answered, so a caller never has to tell
    "not recognised" from "not asked"."""
    people = _profiles(gallery, model)
    out: dict[str, Suggestion | None] = {}
    for label, samples in labels.items():
        kept = purify(samples)
        if not people or _speech(kept) < min_seconds:
            out[label] = None
            continue
        voice = centroid([v for v, _ in kept])
        (kind, key), score = max(((k, cosine(voice, p)) for k, p in people.items()), key=lambda x: x[1])
        out[label] = Suggestion(kind=kind, key=key, score=score) if score >= threshold else None
    return out


def to_enrol(answer: Speakers, suggestions: dict[str, Suggestion | None]) -> dict[str, tuple[str, str]]:
    """Which labels to store, and under which key.

    Only with the consent tick, and only where the gallery did not already know the answer: no
    suggestion, or a suggestion the organiser corrected. A confirmed match is left alone.
    """
    out: dict[str, tuple[str, str]] = {}
    for sp in answer.entries:
        if not sp.consent:
            continue
        kind, key = ("identity", sp.identity) if sp.identity.strip() else ("tag", sp.tag)
        key = key_of(kind, key)
        s = suggestions.get(sp.label)
        if s is not None and (s.kind, key_of(s.kind, s.key).lower()) == (kind, key.lower()):
            continue
        out[sp.label] = (kind, key)
    return out


def enrolment(kind: str, key: str, samples: Sequence[Sample], *, model: str, source: str,
              consented_by: str, min_seconds: float = MIN_ENROL_S) -> Voiceprint | None:
    """One voiceprint from one label's clean speech, or None when there is too little to trust."""
    kept = purify(samples)
    seconds = _speech(kept)
    if seconds < min_seconds:
        return None
    return Voiceprint(kind=kind, key=key, vector=centroid([v for v, _ in kept]), model=model,
                      consented_by=consented_by, source=source, seconds=round(seconds, 1))
