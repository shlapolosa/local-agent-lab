"""An in-memory `ReferenceLibrary` — the double every caller above the adapter tests against.

It exists so the intake workload's tests never need Postgres or an embedding model, and it is
written to fail closed in the same places the real adapter must: no release for the ring, an
unindexed version, an unverified signature, a pin that has expired. A double that answered `[]`
where the real thing raises would let a test pass on behaviour that fails in production, which is
the lesson `tests/fixtures/workflow.py` already records for the gateway router.

`search` here ranks by naive word overlap. That is not a pretence at semantics — it is a stand-in
that is DETERMINISTIC, so a test asserting "this passage came back" is asserting the plumbing, not
a model's mood.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from lab.core.reference.errors import (
    ArtifactUnverified,
    IndexUnavailable,
    PinExpired,
    ReferenceUnavailable,
    UnknownRecordType,
)
from lab.core.reference.model import (
    ArtifactHead,
    ArtifactKind,
    ArtifactVersion,
    Citation,
    Consumption,
    Passage,
    PassageResult,
    Pin,
    Record,
    RecordResult,
    RunRef,
)

__all__ = ["FakeReferenceLibrary", "SeededArtifact"]


def _now() -> datetime:
    return datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


@dataclass
class SeededArtifact:
    artifact_id: str
    kind: ArtifactKind
    title: str = "An artifact"
    owner: str = "an owning body"
    version: str = "2026.09.1"
    record_type: str = ""
    ring: int = 0
    records: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    indexed: bool = True
    verified: bool = True
    embed_model: str = "test-embed"


class FakeReferenceLibrary:
    """Satisfies `lab.core.reference.port.ReferenceLibrary` over dictionaries."""

    def __init__(self, artifacts: list[SeededArtifact] | None = None, *, ring: int = 0,
                 query_model: str = "test-embed", pin_ttl: timedelta = timedelta(hours=1)) -> None:
        self.artifacts = {a.artifact_id: a for a in (artifacts or [])}
        self.ring = ring
        self.query_model = query_model
        self.pin_ttl = pin_ttl
        self.consumption: list[Consumption] = []
        self._pins: dict[str, Pin] = {}

    # ---------------------------------------------------------------- catalogue and pin

    def _visible(self) -> list[SeededArtifact]:
        return [a for a in self.artifacts.values() if a.ring <= self.ring]

    def catalogue(self) -> list[ArtifactHead]:
        visible = self._visible()
        if not visible:
            raise ReferenceUnavailable("(any)", self.ring,
                                       "publish and release at least one artifact to this ring")
        return [ArtifactHead(a.artifact_id, a.kind, a.title, a.owner, a.version, a.record_type)
                for a in visible]

    def _version(self, artifact: SeededArtifact) -> ArtifactVersion:
        digest = f"{artifact.artifact_id}-master"
        return ArtifactVersion(
            artifact_id=artifact.artifact_id, version=artifact.version, kind=artifact.kind,
            title=artifact.title, master_ref=f"art://{artifact.artifact_id}/master.md",
            master_sha256=digest, agent_sha256=f"{artifact.artifact_id}-agent",
            derived_from=digest, signature_id="k1", signed_at=_now().isoformat(),
            ring=artifact.ring, published_at=_now().isoformat())

    def pin(self, artifact_ids=()) -> Pin:
        wanted = list(artifact_ids) or [a.artifact_id for a in self._visible()]
        versions = []
        for artifact_id in wanted:
            artifact = self.artifacts.get(artifact_id)
            if artifact is None or artifact.ring > self.ring:
                raise ReferenceUnavailable(artifact_id, self.ring)
            if not artifact.verified:
                raise ArtifactUnverified(artifact_id, artifact.version,
                                         "the signature does not verify")
            versions.append(self._version(artifact))
        started = _now()
        pin = Pin(pin_id=f"pin-{len(self._pins)}", ring=self.ring,
                  pinned_at=started.isoformat(),
                  expires_at=(started + self.pin_ttl).isoformat(), versions=tuple(versions))
        self._pins[pin.pin_id] = pin
        return pin

    def pin_by_id(self, pin_id: str) -> Pin:
        """The double remembers the pins it minted, as the server's own record."""
        pin = self._pins.get(pin_id)
        if pin is None:
            raise PinExpired(pin_id)
        self._check_pin(pin)
        return pin

    def _check_pin(self, pin: Pin) -> None:
        if datetime.fromisoformat(pin.expires_at) <= _now():
            raise PinExpired(pin.pin_id)

    def _citation(self, artifact: SeededArtifact, locator: str, anchor: str = "") -> Citation:
        return Citation(artifact_id=artifact.artifact_id, title=artifact.title,
                        version=artifact.version, signature_id="k1", locator=locator,
                        master_ref=f"art://{artifact.artifact_id}/master.md", anchor=anchor)

    def _record(self, run: RunRef, artifact: SeededArtifact, mode: str, locator: str,
                hit: bool) -> None:
        self.consumption.append(Consumption(
            run_id=run.run_id, process=run.process, field=run.field,
            artifact_id=artifact.artifact_id, version=artifact.version, mode=mode,
            consulted_at=_now().isoformat(), locator=locator, hit=hit))

    # ---------------------------------------------------------------- the two verbs

    def lookup(self, pin: Pin, *, record_type: str, key, run: RunRef, limit: int = 20
               ) -> RecordResult:
        self._check_pin(pin)
        matching = [a for a in self._visible() if a.record_type == record_type]
        if not matching:
            raise UnknownRecordType(record_type,
                                    sorted({a.record_type for a in self._visible() if a.record_type}))
        found: list[Record] = []
        near: list[dict] = []
        for artifact in matching:
            pin.version_of(artifact.artifact_id)          # an unpinned read is not expressible
            for row in artifact.records:
                row_key = {k: row.get(k) for k in key}
                if row_key == dict(key):
                    found.append(Record(
                        record_id=row.get("record_id", str(row_key)), record_type=record_type,
                        key=row_key, body=row,
                        citation=self._citation(artifact, row.get("record_id", str(row_key)))))
                elif any(row.get(k) == v for k, v in key.items()):
                    near.append({"key": row_key, "why": "matched some but not all key fields"})
            self._record(run, artifact, "lookup", str(dict(key)), bool(found))
        return RecordResult(records=tuple(found[:limit]),
                            citations=tuple(r.citation for r in found[:limit]),
                            near=tuple(near))

    def search(self, pin: Pin, *, question: str, run: RunRef, artifact_ids=(), k: int = 5
               ) -> PassageResult:
        self._check_pin(pin)
        wanted = list(artifact_ids) or [a.artifact_id for a in self._visible()
                                        if a.kind is ArtifactKind.PROSE]
        scored: list[tuple[float, Passage]] = []
        for artifact_id in wanted:
            artifact = self.artifacts[artifact_id]
            pin.version_of(artifact_id)
            if not artifact.indexed or not artifact.passages:
                raise IndexUnavailable(artifact_id, artifact.version,
                                       "the version has no completed index")
            if artifact.embed_model != self.query_model:
                raise IndexUnavailable(
                    artifact_id, artifact.version,
                    f"indexed with {artifact.embed_model!r} but the query embeds with "
                    f"{self.query_model!r}")
            terms = set(question.lower().split())
            for row in artifact.passages:
                overlap = len(terms & set(row["text"].lower().split()))
                if overlap:
                    anchor = " > ".join(row.get("heading_path", ()))
                    scored.append((overlap, Passage(
                        passage_id=row["passage_id"], text=row["text"], score=float(overlap),
                        heading_path=tuple(row.get("heading_path", ())),
                        citation=self._citation(artifact, row["passage_id"], anchor))))
            self._record(run, artifact, "search", question[:40], bool(scored))
        best = [p for _, p in sorted(scored, key=lambda pair: -pair[0])][:k]
        return PassageResult(passages=tuple(best), citations=tuple(p.citation for p in best))

    def record(self, pin: Pin, *, artifact_id: str, record_id: str, run: RunRef) -> Record:
        self._check_pin(pin)
        artifact = self.artifacts[artifact_id]
        pin.version_of(artifact_id)
        for row in artifact.records:
            if row.get("record_id") == record_id:
                self._record(run, artifact, "record", record_id, True)
                return Record(record_id=record_id, record_type=artifact.record_type,
                              key={k: row[k] for k in row if k != "record_id"}, body=row,
                              citation=self._citation(artifact, record_id))
        self._record(run, artifact, "record", record_id, False)
        raise KeyError(f"no record {record_id!r} in {artifact_id!r} at {artifact.version}")

    def consumers(self, *, artifact_id: str, version: str) -> list[Consumption]:
        return [c for c in self.consumption
                if c.artifact_id == artifact_id and c.version == version]
