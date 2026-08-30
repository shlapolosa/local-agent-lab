"""Artifact store — files that cross service boundaries (export specs, rendered XML, SVG
previews) live here, addressed by `art://<id>/<name>` references, never by local paths.

Backends (chosen from ARTIFACTS_URL):
  postgres://…  a `lab_artifacts` table (bytea) — default when DATABASE_URL exists: durable,
                reachable from every container, no extra service (Neon today, Azure Postgres later)
  file:///dir   local directory — single-machine development only
Swap for Azure Blob / S3 by adding a class with the same three methods.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from . import config


class LocalStore:
    def __init__(self, root):
        self.root = root; os.makedirs(root, exist_ok=True)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        aid = uuid.uuid4().hex[:12]; d = os.path.join(self.root, aid); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, name), "wb").write(data)
        return f"art://{aid}/{name}"

    def get(self, ref) -> bytes:
        aid, name = _split(ref)
        return open(os.path.join(self.root, aid, name), "rb").read()

    def info(self, ref) -> dict:
        aid, name = _split(ref); p = os.path.join(self.root, aid, name)
        return {"ref": ref, "name": name, "size": os.path.getsize(p), "backend": "file"}


class PostgresStore:
    DDL = """CREATE TABLE IF NOT EXISTS lab_artifacts (
               id TEXT PRIMARY KEY, name TEXT NOT NULL, content_type TEXT, size INTEGER,
               created_at TIMESTAMPTZ NOT NULL, data BYTEA NOT NULL)"""

    def __init__(self, dsn):
        import psycopg
        self._psycopg = psycopg; self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        with self._conn() as c:
            c.execute(self.DDL)

    def _conn(self):
        return self._psycopg.connect(self.dsn, autocommit=True)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        aid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO lab_artifacts (id, name, content_type, size, created_at, data) VALUES (%s,%s,%s,%s,%s,%s)",
                      (aid, name, content_type, len(data), datetime.now(timezone.utc), data))
        return f"art://{aid}/{name}"

    def get(self, ref) -> bytes:
        aid, _ = _split(ref)
        with self._conn() as c:
            row = c.execute("SELECT data FROM lab_artifacts WHERE id=%s", (aid,)).fetchone()
        if not row:
            raise KeyError(f"unknown artifact {ref}")
        return bytes(row[0])

    def info(self, ref) -> dict:
        aid, _ = _split(ref)
        with self._conn() as c:
            row = c.execute("SELECT name, content_type, size, created_at FROM lab_artifacts WHERE id=%s", (aid,)).fetchone()
        if not row:
            raise KeyError(f"unknown artifact {ref}")
        return {"ref": ref, "name": row[0], "content_type": row[1], "size": row[2],
                "created_at": row[3].isoformat(), "backend": "postgres"}


def _split(ref):
    if not ref.startswith("art://"):
        raise ValueError(f"not an artifact ref: {ref}")
    aid, _, name = ref[6:].partition("/")
    return aid, name


_store = None


def store():
    global _store
    if _store is None:
        url = config.ARTIFACTS_URL
        _store = LocalStore(url[7:]) if url.startswith("file://") else PostgresStore(url)
    return _store


def put_file(path, content_type=None) -> str:
    ct = content_type or {"xml": "application/xml", "svg": "image/svg+xml", "json": "application/json"}.get(
        path.rsplit(".", 1)[-1], "application/octet-stream")
    return store().put(os.path.basename(path), open(path, "rb").read(), ct)
