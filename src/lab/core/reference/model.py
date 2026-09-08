"""The reference corpus's own vocabulary — a version, a pin, a citation, a consumption.

The one idea holding this together: **every read happens under a PIN**. A pin freezes the set of
versions a run will consult, so two reads in one run cannot straddle a release. Without it a run
that looks a price up at v3 and reads its rationale at v2 has produced a defect no test would
catch, because both reads succeeded.

`RunRef` carries the DERIVED FIELD, not just the run — FR-44 requires every derived field to record
the artifact versions consulted and the reasoning path, and "which field was this consulted for" is
the question that makes the reverse index (FR-45) worth having.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

__all__ = [
    "ArtifactHead", "ArtifactKind", "ArtifactVersion", "Citation", "Consumption", "Passage",
    "PassageResult", "Pin", "Record", "RecordResult", "RunRef",
]


class ArtifactKind(StrEnum):
    """How an artifact is retrieved, which follows from what it IS.

    A nearly-right predicate or price line is worse than a failed lookup, so derivation artifacts
    are RECORDs resolved exactly; explanatory content is PROSE resolved semantically."""
    RECORD = "record"
    PROSE = "prose"


@dataclass(frozen=True)
class ArtifactHead:
    """An artifact as the catalogue lists it, at the version this caller's ring resolves to."""
    artifact_id: str
    kind: ArtifactKind
    title: str
    owner: str
    version: str
    record_type: str = ""

    def __post_init__(self) -> None:
        if (self.kind is ArtifactKind.RECORD) != bool(self.record_type):
            raise ValueError(
                f"{self.artifact_id}: a record artifact declares a record_type and a prose one "
                f"does not; got kind={self.kind} record_type={self.record_type!r}")


@dataclass(frozen=True)
class ArtifactVersion:
    """One governed version — the unit that is signed, released and pinned."""
    artifact_id: str
    version: str
    kind: ArtifactKind
    title: str
    master_ref: str
    master_sha256: str
    agent_sha256: str
    derived_from: str
    signature_id: str
    signed_at: str
    ring: int
    published_at: str

    def __post_init__(self) -> None:
        if self.derived_from != self.master_sha256:
            raise ValueError(
                f"{self.artifact_id} {self.version}: the agent-readable form claims a master it "
                f"was not derived from. DR-02 makes that a defect, not a lag.")


@dataclass(frozen=True)
class Pin:
    """The frozen version set for one run. Every read takes it; an unpinned read is not expressible."""
    pin_id: str
    ring: int
    pinned_at: str
    expires_at: str
    versions: tuple[ArtifactVersion, ...] = ()

    def version_of(self, artifact_id: str) -> ArtifactVersion:
        for version in self.versions:
            if version.artifact_id == artifact_id:
                return version
        raise KeyError(f"{artifact_id!r} is not in this pin; it holds "
                       f"{[v.artifact_id for v in self.versions]}")


@dataclass(frozen=True)
class Citation:
    """What an answer cites, and what a person opens.

    `master_ref` is the HUMAN-READABLE signed master, so the citation an agent surfaces is directly
    openable through storage-mcp. That is DR-02 made visible at the point of use: the agent read
    the derived form, the human opens the same artifact at the same version."""
    artifact_id: str
    title: str
    version: str
    signature_id: str
    locator: str
    master_ref: str
    anchor: str = ""


@dataclass(frozen=True)
class Record:
    record_id: str
    record_type: str
    key: Mapping[str, Any]
    body: Mapping[str, Any]
    citation: Citation


@dataclass(frozen=True)
class Passage:
    passage_id: str
    text: str
    score: float
    heading_path: tuple[str, ...]
    citation: Citation


@dataclass(frozen=True)
class RecordResult:
    """Records, and — separately — what nearly matched.

    `near` is a different key from `records` on purpose and is documented as NOT an answer. A
    caller iterating `records` must never reach a near-miss: that is precisely the "nearly-right
    predicate" the exact side of the corpus exists to prevent."""
    records: tuple[Record, ...] = ()
    citations: tuple[Citation, ...] = ()
    near: tuple[Mapping[str, Any], ...] = ()

    @property
    def matched(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class PassageResult:
    passages: tuple[Passage, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class RunRef:
    """Who is consulting the corpus, and for WHICH derived field.

    Required on every read so `ref_consumption` is written inside the call. There is deliberately
    no "report your sources afterwards" step for a run to forget."""
    run_id: str
    process: str
    field: str

    def __post_init__(self) -> None:
        for name in ("run_id", "process", "field"):
            if not str(getattr(self, name)).strip():
                raise ValueError(
                    f"a reference read must name its {name}; FR-44 requires every derived field to "
                    f"record the artifact versions it consulted, and an unattributed read cannot")


@dataclass(frozen=True)
class Consumption:
    """One recorded read — the row the reverse index (FR-45) is built on."""
    run_id: str
    process: str
    field: str
    artifact_id: str
    version: str
    mode: str
    consulted_at: str
    locator: str = ""
    hit: bool = True
    extra: Mapping[str, Any] = dataclasses.field(default_factory=dict)
