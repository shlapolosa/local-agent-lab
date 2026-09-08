"""The Postgres realisation of `lab.core.reference.port.ReferenceLibrary`.

Reads only. The server is configured with the READER role, so DR-03 ("no instance writes to a
shared store under any condition") is a database GRANT rather than a promise this module makes
about itself — the only form of that rule a compromised service cannot talk its way out of. The
publisher is a separate operator CLI with its own DSN and the signing key.

Everything here funnels through `pin()`. Every read joins `ref_pin_entry`, so there is no SQL path
that reads a record without a pinned version and an unpinned read is not expressible — which is how
two reads in one run are stopped from straddling a release. Verification happens at PIN, every
time, not once at publish, and one failure fails the WHOLE pin: a run must not begin with a
partially trustworthy corpus.

`connect` is injected, the seam `artifacts.PostgresStore` already established, so the fail-closed
matrix is testable offline against a fake connection.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from lab.core.reference.errors import (  # noqa: I001
    ReferenceError,
    ArtifactUnverified,
    CorpusUnreachable,
    IndexUnavailable,
    PinExpired,
    ReferenceUnavailable,
    UnknownRecordType,
)
from lab.core.reference.manifest import ManifestError, manifest, verify
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
from lab.platform import config

__all__ = ["PostgresReferenceLibrary", "build"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trust_keys(raw: str) -> dict[str, str]:
    """`key_id:base64,key_id:base64` — public material only."""
    out: dict[str, str] = {}
    for entry in (raw or "").split(","):
        key_id, _, material = entry.strip().partition(":")
        if key_id and material:
            out[key_id] = material
    return out


class PostgresReferenceLibrary:
    """A governed corpus over the `ref_*` tables."""

    def __init__(self, *, dsn: str, connect: Callable[..., Any], ring: int,
                 trust_keys: Mapping[str, str], embedder: Any = None,
                 pin_ttl_s: int = 86400) -> None:
        self.dsn = dsn
        self._connect = connect
        self.ring = int(ring)
        self.trust_keys = dict(trust_keys)
        self.embedder = embedder
        self.pin_ttl = timedelta(seconds=pin_ttl_s)

    # ---------------------------------------------------------------- plumbing

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        try:
            with self._connect(self.dsn) as conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return list(cur.fetchall())
        except ReferenceError:
            raise
        except Exception as exc:                      # noqa: BLE001 — every driver error, one shape
            raise CorpusUnreachable(f"{type(exc).__name__}: {exc}") from exc

    def _write(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        try:
            with self._connect(self.dsn) as conn, conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, tuple(params))
                conn.commit()
        except ReferenceError:
            raise
        except Exception as exc:                      # noqa: BLE001
            raise CorpusUnreachable(f"{type(exc).__name__}: {exc}") from exc

    # ---------------------------------------------------------------- catalogue

    _CATALOGUE = """
        SELECT a.artifact_id, a.kind, a.record_type, a.title, a.owner, r.version
          FROM ref_artifact a
          JOIN ref_release r ON r.artifact_id = a.artifact_id AND r.ring = %s
         ORDER BY a.artifact_id"""

    def catalogue(self) -> list[ArtifactHead]:
        rows = self._rows(self._CATALOGUE, (self.ring,))
        if not rows:
            raise ReferenceUnavailable(
                "(any)", self.ring,
                "publish at least one artifact and release it to this ring; an empty catalogue is "
                "indistinguishable from a library that is not there")
        return [ArtifactHead(artifact_id=r[0], kind=ArtifactKind(r[1]), record_type=r[2] or "",
                             title=r[3], owner=r[4], version=r[5]) for r in rows]

    # ---------------------------------------------------------------- pin

    _RESOLVE = """
        SELECT v.artifact_id, v.version, a.kind, a.title, v.master_ref, v.master_sha256,
               v.agent_sha256, v.derived_from, v.manifest_sha256, v.signature, v.key_id,
               v.signed_at, v.published_at, r.ring, v.status
          FROM ref_release r
          JOIN ref_artifact_version v
            ON v.artifact_id = r.artifact_id AND v.version = r.version
          JOIN ref_artifact a ON a.artifact_id = v.artifact_id
         WHERE r.ring = %s AND v.artifact_id = ANY(%s)"""

    def pin(self, artifact_ids: Sequence[str] = ()) -> Pin:
        wanted = list(artifact_ids) or [head.artifact_id for head in self.catalogue()]
        rows = {r[0]: r for r in self._rows(self._RESOLVE, (self.ring, wanted))}

        versions: list[ArtifactVersion] = []
        for artifact_id in wanted:
            row = rows.get(artifact_id)
            if row is None:
                raise ReferenceUnavailable(artifact_id, self.ring)
            if row[14] != "published":
                raise ArtifactUnverified(artifact_id, row[1],
                                         f"the version is {row[14]!r}, not published")
            self._verify(row)
            versions.append(ArtifactVersion(
                artifact_id=row[0], version=row[1], kind=ArtifactKind(row[2]), title=row[3],
                master_ref=row[4], master_sha256=row[5], agent_sha256=row[6], derived_from=row[7],
                signature_id=row[10], signed_at=str(row[11]), ring=row[13],
                published_at=str(row[12])))

        started = _now()
        pin_id = f"pin-{uuid.uuid4().hex[:12]}"
        expires = started + self.pin_ttl
        self._write(
            [("INSERT INTO ref_pin (pin_id, ring, pinned_at, expires_at) VALUES (%s,%s,%s,%s)",
              (pin_id, self.ring, started, expires))]
            + [("INSERT INTO ref_pin_entry (pin_id, artifact_id, version) VALUES (%s,%s,%s)",
                (pin_id, v.artifact_id, v.version)) for v in versions])
        return Pin(pin_id=pin_id, ring=self.ring, pinned_at=started.isoformat(),
                   expires_at=expires.isoformat(), versions=tuple(versions))

    def _verify(self, row: tuple) -> None:
        """Signature and digest, re-checked on EVERY pin rather than once at publish."""
        public_key = self.trust_keys.get(row[10])
        if public_key is None:
            raise ArtifactUnverified(row[0], row[1],
                                     f"nothing in the trust store answers to key {row[10]!r}")
        try:
            body = manifest(artifact_id=row[0], version=row[1], kind=row[2],
                            master_sha256=row[5], agent_sha256=row[6], derived_from=row[7],
                            # The RAW value, not `str()` of it: the driver returns a datetime and
                            # `str()` spells the ISO separator as a space, so the manifest rebuilt
                            # here did not match the one signed at publish and every artifact in a
                            # freshly published corpus reported itself TAMPERED. `manifest`
                            # canonicalises an instant; handing it a string takes that away.
                            content_digest=row[8], published_at=row[12], key_id=row[10])
            ok = verify(body, row[9], public_key)
        except ManifestError as exc:
            raise ArtifactUnverified(row[0], row[1], str(exc)) from exc
        if not ok:
            raise ArtifactUnverified(row[0], row[1],
                                     "the signature does not cover this version's content")

    _PIN_BY_ID = """
        SELECT p.pin_id, p.ring, p.pinned_at, p.expires_at,
               e.artifact_id, e.version, a.kind, a.title, v.master_ref, v.master_sha256,
               v.agent_sha256, v.derived_from, v.key_id, v.signed_at, v.published_at
          FROM ref_pin p
          JOIN ref_pin_entry e ON e.pin_id = p.pin_id
          JOIN ref_artifact a ON a.artifact_id = e.artifact_id
          JOIN ref_artifact_version v
            ON v.artifact_id = e.artifact_id AND v.version = e.version
         WHERE p.pin_id = %s"""

    def pin_by_id(self, pin_id: str) -> Pin:
        """Rehydrate a pin from the server's own record — the caller holds only its id."""
        rows = self._rows(self._PIN_BY_ID, (pin_id,))
        if not rows:
            raise PinExpired(pin_id)
        head = rows[0]
        pin = Pin(pin_id=head[0], ring=head[1], pinned_at=str(head[2]), expires_at=str(head[3]),
                  versions=tuple(ArtifactVersion(
                      artifact_id=r[4], version=r[5], kind=ArtifactKind(r[6]), title=r[7],
                      master_ref=r[8], master_sha256=r[9], agent_sha256=r[10], derived_from=r[11],
                      signature_id=r[12], signed_at=str(r[13]), ring=head[1],
                      published_at=str(r[14])) for r in rows))
        self._check_pin(pin)
        return pin

    def _check_pin(self, pin: Pin) -> None:
        if datetime.fromisoformat(pin.expires_at) <= _now():
            raise PinExpired(pin.pin_id)

    # ---------------------------------------------------------------- lookup

    _LOOKUP = """
        SELECT r.artifact_id, r.version, r.record_id, r.record_type, r.key, r.body,
               a.title, v.master_ref, v.key_id
          FROM ref_record r
          JOIN ref_pin_entry p
            ON p.artifact_id = r.artifact_id AND p.version = r.version AND p.pin_id = %s
          JOIN ref_artifact a ON a.artifact_id = r.artifact_id
          JOIN ref_artifact_version v
            ON v.artifact_id = r.artifact_id AND v.version = r.version
         WHERE r.record_type = %s AND r.key @> %s
         LIMIT %s"""

    _TYPES = """
        SELECT DISTINCT a.record_type FROM ref_artifact a
          JOIN ref_release rel ON rel.artifact_id = a.artifact_id AND rel.ring = %s
         WHERE a.record_type IS NOT NULL"""

    def lookup(self, pin: Pin, *, record_type: str, key: Mapping[str, Any], run: RunRef,
               limit: int = 20) -> RecordResult:
        self._check_pin(pin)
        known = [r[0] for r in self._rows(self._TYPES, (self.ring,))]
        if record_type not in known:
            raise UnknownRecordType(record_type, sorted(known))

        rows = self._rows(self._LOOKUP, (pin.pin_id, record_type, json.dumps(dict(key)), limit))
        records, citations = [], []
        for row in rows:
            citation = Citation(artifact_id=row[0], title=row[6], version=row[1],
                                signature_id=row[8], locator=row[2], master_ref=row[7])
            records.append(Record(record_id=row[2], record_type=row[3], key=row[4], body=row[5],
                                  citation=citation))
            citations.append(citation)
        self._note(pin, run, "lookup", artifact_ids=[r[0] for r in rows] or
                   [v.artifact_id for v in pin.versions], locator=json.dumps(dict(key)),
                   hit=bool(rows))
        return RecordResult(records=tuple(records), citations=tuple(citations))

    # ---------------------------------------------------------------- search

    _INDEX_STATE = """
        SELECT s.artifact_id, s.version, s.passages, s.embed_model, s.embed_dim, s.completed_at
          FROM ref_index_state s
          JOIN ref_pin_entry p
            ON p.artifact_id = s.artifact_id AND p.version = s.version AND p.pin_id = %s
         WHERE s.artifact_id = ANY(%s)"""

    _SEARCH = """
        SELECT g.artifact_id, g.version, g.passage_id, g.text, g.heading_path, g.anchor,
               a.title, v.master_ref, v.key_id, 1 - (g.embedding <=> %s::vector) AS score
          FROM ref_passage g
          JOIN ref_pin_entry p
            ON p.artifact_id = g.artifact_id AND p.version = g.version AND p.pin_id = %s
          JOIN ref_artifact a ON a.artifact_id = g.artifact_id
          JOIN ref_artifact_version v
            ON v.artifact_id = g.artifact_id AND v.version = g.version
         WHERE g.artifact_id = ANY(%s)
         ORDER BY g.embedding <=> %s::vector
         LIMIT %s"""

    def search(self, pin: Pin, *, question: str, run: RunRef,
               artifact_ids: Sequence[str] = (), k: int = 5) -> PassageResult:
        self._check_pin(pin)
        if self.embedder is None:
            raise IndexUnavailable("(any)", pin.pin_id,
                                   "no embedder is configured, so a semantic query cannot be "
                                   "embedded at all")
        wanted = list(artifact_ids) or [v.artifact_id for v in pin.versions]

        for row in self._rows(self._INDEX_STATE, (pin.pin_id, wanted)):
            artifact_id, version, passages, model, dim, completed = row
            if completed is None or not passages:
                raise IndexUnavailable(artifact_id, version,
                                       "the version has no completed index")
            if model != self.embedder.model or int(dim or 0) != int(self.embedder.dim):
                raise IndexUnavailable(
                    artifact_id, version,
                    f"indexed with {model!r}/{dim} but the query embeds with "
                    f"{self.embedder.model!r}/{self.embedder.dim}")

        vector = self.embedder.embed([question], purpose="query")[0]
        literal = "[" + ",".join(str(v) for v in vector) + "]"
        rows = self._rows(self._SEARCH, (literal, pin.pin_id, wanted, literal, k))

        passages_out, citations = [], []
        for row in rows:
            citation = Citation(artifact_id=row[0], title=row[6], version=row[1],
                                signature_id=row[8], locator=row[2], master_ref=row[7],
                                anchor=row[5])
            passages_out.append(Passage(passage_id=row[2], text=row[3], score=float(row[9]),
                                        heading_path=tuple(row[4] or ()), citation=citation))
            citations.append(citation)
        self._note(pin, run, "search", artifact_ids=wanted, locator=question[:120],
                   hit=bool(rows))
        return PassageResult(passages=tuple(passages_out), citations=tuple(citations))

    # ---------------------------------------------------------------- one record

    _RECORD = """
        SELECT r.artifact_id, r.version, r.record_id, r.record_type, r.key, r.body,
               a.title, v.master_ref, v.key_id
          FROM ref_record r
          JOIN ref_pin_entry p
            ON p.artifact_id = r.artifact_id AND p.version = r.version AND p.pin_id = %s
          JOIN ref_artifact a ON a.artifact_id = r.artifact_id
          JOIN ref_artifact_version v
            ON v.artifact_id = r.artifact_id AND v.version = r.version
         WHERE r.artifact_id = %s AND r.record_id = %s"""

    def record(self, pin: Pin, *, artifact_id: str, record_id: str, run: RunRef) -> Record:
        self._check_pin(pin)
        rows = self._rows(self._RECORD, (pin.pin_id, artifact_id, record_id))
        self._note(pin, run, "record", artifact_ids=[artifact_id], locator=record_id,
                   hit=bool(rows))
        if not rows:
            raise KeyError(f"no record {record_id!r} in {artifact_id!r} at the pinned version")
        row = rows[0]
        return Record(record_id=row[2], record_type=row[3], key=row[4], body=row[5],
                      citation=Citation(artifact_id=row[0], title=row[6], version=row[1],
                                        signature_id=row[8], locator=row[2], master_ref=row[7]))

    # ---------------------------------------------------------------- the reverse index

    _CONSUMERS = """
        SELECT run_id, process, field, artifact_id, version, mode, consulted_at, locator, hit
          FROM ref_consumption
         WHERE artifact_id = %s AND version = %s
         ORDER BY consulted_at DESC"""

    def consumers(self, *, artifact_id: str, version: str) -> list[Consumption]:
        return [Consumption(run_id=r[0], process=r[1], field=r[2], artifact_id=r[3], version=r[4],
                            mode=r[5], consulted_at=str(r[6]), locator=r[7] or "", hit=r[8])
                for r in self._rows(self._CONSUMERS, (artifact_id, version))]

    # ---------------------------------------------------------------- attribution

    def _note(self, pin: Pin, run: RunRef, mode: str, *, artifact_ids: Sequence[str],
              locator: str, hit: bool) -> None:
        """Written INSIDE the read, so FR-44 has no "report your sources afterwards" step to miss.

        A miss is recorded too: "we consulted the price sheet and it had no line for this" is
        itself a derivation fact, and the reverse index is incomplete without it."""
        when = _now()
        self._write([(
            "INSERT INTO ref_consumption (run_id, process, field, artifact_id, version, mode, "
            "locator, query_digest, hit, pin_id, consulted_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run.run_id, run.process, run.field, artifact_id,
             pin.version_of(artifact_id).version, mode, locator[:200], locator[:64], hit,
             pin.pin_id, when))
            for artifact_id in dict.fromkeys(artifact_ids)])


def build(**overrides: Any) -> PostgresReferenceLibrary:
    """The container's factory. Settings come from `lab.platform.config`, the one env reader."""
    import psycopg

    options: dict[str, Any] = {
        "dsn": config.REFERENCE_DB_URL,
        "connect": psycopg.connect,
        "ring": config.REFERENCE_RING,
        "trust_keys": _trust_keys(config.REFERENCE_TRUST_KEYS),
        "pin_ttl_s": config.REFERENCE_PIN_TTL_S,
    }
    options.update(overrides)
    return PostgresReferenceLibrary(**options)
