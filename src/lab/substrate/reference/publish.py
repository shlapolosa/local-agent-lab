"""The reference corpus publisher — an OPERATOR CLI, deliberately not a tool.

It holds the two things no service may hold: the private signing seed and the publisher DSN. If
publishing were an MCP tool, DR-03 ("no instance writes to a shared store under any condition")
would rest on nobody granting it. As a CLI there is no tool to grant, which is a different kind of
guarantee.

The order of operations is the safety property. A version is inserted as `draft`, its content is
indexed, and only then does one transaction mark it `published` — so a crashed publish leaves a
draft with no release row and nothing servable. RELEASING is a separate command, because publishing
is safe and releasing is what changes what runs see; collapsing them would make every publish an
immediate production change to every open business case.

The derivation is mechanical rather than promised: the master is hashed, PARSED, and the
agent-readable form derived from what came back. `derived_from = master_sha256` is then a fact.

    python -m lab.substrate.reference.publish init [--grants]
    python -m lab.substrate.reference.publish publish <artifact_id> --from <dir> --version <v>
    python -m lab.substrate.reference.publish release <artifact_id> <version> --ring N
    python -m lab.substrate.reference.publish list | verify [<artifact_id>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from lab.core.reference.derive import content_digest, passages, records
from lab.core.reference.manifest import manifest, sign, verify
from lab.core.reference.master import parse as parse_master
from lab.core.reference.rings import RINGS, can_release
from lab.platform import config
from lab.substrate import artifacts as artifact_store
from lab.substrate.reference.schema import apply_migrations

__all__ = ["PublishError", "Publisher", "main"]


class PublishError(RuntimeError):
    """The publish could not be completed, and a half-published version must not be left servable."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Publisher:
    """Everything the operator CLI does, with its I/O injected so it is testable offline."""

    def __init__(self, *, dsn: str, connect: Callable[..., Any], signing_key: str, key_id: str,
                 store: Any = None, embedder: Any = None,
                 soak: timedelta = timedelta(days=1)) -> None:
        self.dsn = dsn
        self._connect = connect
        self.signing_key = signing_key
        self.key_id = key_id
        self.store = store
        self.embedder = embedder
        self.soak = soak

    # ---------------------------------------------------------------- plumbing

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        with self._connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())

    def _tx(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        """One transaction. A publish that dies mid-way leaves a draft, never a servable version."""
        with self._connect(self.dsn) as conn, conn.cursor() as cur:
            for sql, params in statements:
                cur.execute(sql, tuple(params))
            conn.commit()

    # ---------------------------------------------------------------- init

    def init(self, *, grants: bool = False) -> int:
        with self._connect(self.dsn) as conn:
            return apply_migrations(conn, grants=grants)

    def trust(self, public_key: str) -> None:
        """Record the PUBLIC half of the signing key so readers can verify. The private seed never
        travels — not into the database, not into `LAB_ENV`, not into a service."""
        self._tx([("INSERT INTO ref_signing_key (key_id, algorithm, public_key, valid_from) "
                   "VALUES (%s,%s,%s,%s) ON CONFLICT (key_id) DO NOTHING",
                   (self.key_id, "ed25519", public_key, _now()))])

    # ---------------------------------------------------------------- publish

    def publish(self, artifact_id: str, *, master_path: Path, version: str, kind: str,
                owner: str, record_type: str = "", key_fields: Sequence[str] = (),
                supersedes: str = "") -> dict:
        """Hash the master, derive from it, sign, index, and mark published — in that order."""
        if kind not in ("record", "prose"):
            raise PublishError(f"kind must be 'record' or 'prose'; got {kind!r}")
        if kind == "record" and not (record_type and key_fields):
            raise PublishError("a record artifact needs a record_type and its natural key_fields — "
                               "without the key, a re-publish cannot keep a row's identity")

        raw = master_path.read_bytes()
        master_sha = _sha256(raw)
        master = parse_master(raw.decode("utf-8"))

        # Derived FROM the parsed master, so `derived_from` is a fact rather than a claim.
        if kind == "record":
            rows = [dict(zip(master.headers, row)) for row in master.rows]
            derived = records(artifact_id, rows, key_fields=list(key_fields))
            entries: list[Any] = [{"record_id": d.record_id, "key": d.key, "body": d.body}
                                  for d in derived]
        else:
            derived = passages(artifact_id, master.prose or raw.decode("utf-8"))
            entries = [{"passage_id": d.passage_id, "anchor": d.anchor, "text": d.text}
                       for d in derived]
        if not derived:
            raise PublishError(f"{artifact_id}: the master derived nothing — an artifact that "
                               f"indexes to zero rows would pass any 'is it there' check")

        agent_bytes = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
        agent_sha = _sha256(agent_bytes)
        digest = content_digest(entries)
        published_at = _now().isoformat()

        body = manifest(artifact_id=artifact_id, version=version, kind=kind,
                        master_sha256=master_sha, agent_sha256=agent_sha,
                        derived_from=master_sha, content_digest=digest,
                        published_at=published_at, key_id=self.key_id)
        signature = sign(body, self.signing_key)

        store = self.store or artifact_store.store()
        master_ref = store.put(f"{artifact_id}.md", raw, "text/markdown")
        agent_ref = store.put(f"{artifact_id}.json", agent_bytes, "application/json")

        statements: list[tuple[str, Sequence[Any]]] = [
            ("INSERT INTO ref_artifact (artifact_id, kind, record_type, title, owner) "
             "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (artifact_id) DO UPDATE "
             "SET title = EXCLUDED.title, owner = EXCLUDED.owner",
             (artifact_id, kind, record_type or None, master.title, owner)),
            ("INSERT INTO ref_artifact_version (artifact_id, version, status, master_ref, "
             "master_sha256, agent_ref, agent_sha256, derived_from, manifest_sha256, signature, "
             "key_id, signed_at, published_at, supersedes) "
             "VALUES (%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
             (artifact_id, version, master_ref, master_sha, agent_ref, agent_sha, master_sha,
              digest, signature, self.key_id, published_at, published_at, supersedes or None)),
        ]
        statements += (self._record_rows(artifact_id, version, record_type, derived)
                       if kind == "record"
                       else self._passage_rows(artifact_id, version, derived))

        # The one transaction that makes it servable — index state and status together, or neither.
        statements.append((
            "INSERT INTO ref_index_state (artifact_id, version, records, passages, embed_model, "
            "embed_dim, completed_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (artifact_id, version) DO UPDATE SET records = EXCLUDED.records, "
            "passages = EXCLUDED.passages, embed_model = EXCLUDED.embed_model, "
            "embed_dim = EXCLUDED.embed_dim, completed_at = EXCLUDED.completed_at",
            (artifact_id, version,
             len(derived) if kind == "record" else 0,
             0 if kind == "record" else len(derived),
             self.embedder.model if (kind == "prose" and self.embedder) else None,
             self.embedder.dim if (kind == "prose" and self.embedder) else None,
             _now())))
        statements.append(("UPDATE ref_artifact_version SET status = 'published' "
                           "WHERE artifact_id = %s AND version = %s", (artifact_id, version)))
        self._tx(statements)
        # The manifest is returned, not just written: an operator publishing a governed artifact
        # should be able to see exactly what was signed without reading it back out of the database.
        return {"artifact_id": artifact_id, "version": version, "kind": kind,
                "entries": len(derived), "master_ref": master_ref, "agent_ref": agent_ref,
                "signature_id": self.key_id, "signature": signature,
                "manifest": {"master_sha256": master_sha, "agent_sha256": agent_sha,
                             "derived_from": master_sha, "content_digest": digest,
                             "published_at": published_at}}

    def _record_rows(self, artifact_id, version, record_type, derived):
        return [("INSERT INTO ref_record (artifact_id, version, record_id, record_type, key, body) "
                 "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                 (artifact_id, version, d.record_id, record_type, json.dumps(dict(d.key)),
                  json.dumps(dict(d.body)))) for d in derived]

    def _passage_rows(self, artifact_id, version, derived):
        if self.embedder is None:
            raise PublishError(
                f"{artifact_id} is a prose artifact and no embedder is configured. Publishing it "
                f"unindexed would create a version that reference_search must refuse — set "
                f"REFERENCE_EMBED_MODEL, or publish the record artifacts only for now.")
        vectors = self.embedder.embed([d.text for d in derived], purpose="document")
        return [("INSERT INTO ref_passage (artifact_id, version, passage_id, ordinal, "
                 "heading_path, anchor, text, tokens, embed_model, embed_dim, embedding) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                 (artifact_id, version, d.passage_id, d.ordinal, list(d.heading_path), d.anchor,
                  d.text, len(d.text.split()), self.embedder.model, self.embedder.dim,
                  "[" + ",".join(str(v) for v in vec) + "]"))
                for d, vec in zip(derived, vectors)]

    # ---------------------------------------------------------------- release

    _PREVIOUS = ("SELECT released_at FROM ref_release "
                 "WHERE artifact_id = %s AND ring = %s AND version = %s")

    def release(self, artifact_id: str, version: str, *, ring: int, actor: str,
                rollback: bool = False, defects: tuple[str, ...] = ()) -> dict:
        """Move a version to a ring, subject to the CR-18 soak on the ring below it."""
        previous = None
        if ring > RINGS[0]:
            rows = self._rows(self._PREVIOUS, (artifact_id, ring - 1, version))
            previous = rows[0][0] if rows else None
            if isinstance(previous, str):
                previous = datetime.fromisoformat(previous)

        decision = can_release(ring, previous_released_at=previous, now=_now(), soak=self.soak,
                               defects=defects, rollback=rollback)
        if not decision.allowed:
            raise PublishError(f"{artifact_id} {version} -> ring {ring}: {decision.reason}")
        self._tx([("INSERT INTO ref_release (artifact_id, ring, version, released_at, released_by) "
                   "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (artifact_id, ring) DO UPDATE "
                   "SET version = EXCLUDED.version, released_at = EXCLUDED.released_at, "
                   "released_by = EXCLUDED.released_by",
                   (artifact_id, ring, version, _now(), actor))])
        return {"artifact_id": artifact_id, "version": version, "ring": ring,
                "reason": decision.reason}

    # ---------------------------------------------------------------- inspect

    _LIST = """
        SELECT v.artifact_id, v.version, v.status, v.key_id,
               COALESCE(string_agg(r.ring::text, ',' ORDER BY r.ring), '')
          FROM ref_artifact_version v
          LEFT JOIN ref_release r ON r.artifact_id = v.artifact_id AND r.version = v.version
         GROUP BY v.artifact_id, v.version, v.status, v.key_id
         ORDER BY v.artifact_id, v.version"""

    def list(self) -> list[dict]:
        return [{"artifact_id": r[0], "version": r[1], "status": r[2], "signature_id": r[3],
                 "rings": [int(x) for x in r[4].split(",") if x]} for r in self._rows(self._LIST)]

    _VERIFY = """
        SELECT v.artifact_id, v.version, a.kind, v.master_sha256, v.agent_sha256, v.derived_from,
               v.manifest_sha256, v.signature, v.key_id, v.published_at, k.public_key
          FROM ref_artifact_version v
          JOIN ref_artifact a ON a.artifact_id = v.artifact_id
          LEFT JOIN ref_signing_key k ON k.key_id = v.key_id
         WHERE (%s = '' OR v.artifact_id = %s)"""

    def verify(self, artifact_id: str = "") -> list[dict]:
        """Re-check every signature without serving anything — what an operator runs after a
        restore, or when somebody asks whether the corpus is still what it was."""
        out = []
        for r in self._rows(self._VERIFY, (artifact_id, artifact_id)):
            if r[10] is None:
                out.append({"artifact_id": r[0], "version": r[1], "ok": False,
                            "why": f"no public key for {r[8]!r} in the trust store"})
                continue
            body = manifest(artifact_id=r[0], version=r[1], kind=r[2], master_sha256=r[3],
                            agent_sha256=r[4], derived_from=r[5], content_digest=r[6],
                            published_at=str(r[9]), key_id=r[8])
            ok = verify(body, r[7], r[10])
            out.append({"artifact_id": r[0], "version": r[1], "ok": ok,
                        "why": "" if ok else "the signature does not cover this version"})
        return out


# ---------------------------------------------------------------- the CLI

def _publisher(soak_days: float = 1.0) -> Publisher:
    import psycopg
    dsn = config.REFERENCE_PUBLISH_DB_URL or config.REFERENCE_DB_URL
    key = config.REFERENCE_SIGNING_KEY
    if not key:
        raise SystemExit("REFERENCE_SIGNING_KEY is not set. It is the private seed and belongs on "
                         "the publishing workstation only — never in LAB_ENV, where it would prove "
                         "nothing beyond repo admin.")
    from lab.substrate.container import build as build_container
    container = build_container("reference-publisher")
    return Publisher(dsn=dsn, connect=psycopg.connect, signing_key=key,
                     key_id=config.REFERENCE_KEY_ID,
                     embedder=container.embedder(), soak=timedelta(days=soak_days))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.substrate.reference.publish",
                                 description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the tables (and optionally the role grants)")
    init.add_argument("--grants", action="store_true")

    pub = sub.add_parser("publish", help="publish one artifact version from its master")
    pub.add_argument("artifact_id")
    pub.add_argument("--master", type=Path, required=True)
    pub.add_argument("--version", required=True)
    pub.add_argument("--kind", choices=("record", "prose"), required=True)
    pub.add_argument("--owner", required=True)
    pub.add_argument("--record-type", default="")
    pub.add_argument("--key-fields", default="", help="comma-separated natural key")
    pub.add_argument("--supersedes", default="")

    rel = sub.add_parser("release", help="move a version to a ring, subject to the soak")
    rel.add_argument("artifact_id")
    rel.add_argument("version")
    rel.add_argument("--ring", type=int, required=True)
    rel.add_argument("--actor", required=True)
    rel.add_argument("--rollback", action="store_true")

    sub.add_parser("list", help="what is published, and at which rings")
    ver = sub.add_parser("verify", help="re-check signatures without serving anything")
    ver.add_argument("artifact_id", nargs="?", default="")

    args = ap.parse_args(argv)
    publisher = _publisher()

    if args.command == "init":
        print(f"{publisher.init(grants=args.grants)} statements applied")
    elif args.command == "publish":
        out = publisher.publish(
            args.artifact_id, master_path=args.master, version=args.version, kind=args.kind,
            owner=args.owner, record_type=args.record_type,
            key_fields=[f for f in args.key_fields.split(",") if f],
            supersedes=args.supersedes)
        print(json.dumps(out, indent=2))
    elif args.command == "release":
        print(json.dumps(publisher.release(args.artifact_id, args.version, ring=args.ring,
                                           actor=args.actor, rollback=args.rollback), indent=2))
    elif args.command == "list":
        for row in publisher.list():
            print(f"{row['artifact_id']:28} {row['version']:12} {row['status']:10} "
                  f"rings={row['rings'] or '-'}")
    elif args.command == "verify":
        bad = [r for r in publisher.verify(args.artifact_id) if not r["ok"]]
        for row in bad:
            print(f"FAIL {row['artifact_id']} {row['version']}: {row['why']}", file=sys.stderr)
        print(f"{'FAILED' if bad else 'ok'} — {len(bad)} unverifiable")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
