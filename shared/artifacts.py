"""Artifact store — files that cross service boundaries (export specs, rendered XML, SVG
previews, and the workloads' INPUT uploads) live here, addressed by `art://<id>/<name>`
references, never by local paths.

Backends (chosen from the store URL):
  s3://bucket[/prefix]  S3-compatible object store (Railway Bucket now, Azure Blob later):
                        key = <prefix>/<id>/<name>; credentials from S3_* env — held ONLY by the
                        components that must write/read objects directly (review app, storage-mcp)
  postgres://…          a `lab_artifacts` table (bytea) — default when DATABASE_URL exists: durable,
                        reachable from every container, no extra service (Neon today)
  file:///dir           local directory — single-machine development only

Two logical stores share one code path: `store()` (ARTIFACTS_URL — renders/specs written by the
MCP servers) and `uploads()` (UPLOADS_URL, default = ARTIFACTS_URL — the inputs a person submits).
Splitting them lets uploads live in a bucket while renders stay in Postgres; with UPLOADS_URL
unset (local dev) both are the same store and no S3 is needed. Agents never call this module for
refs — they read objects through the gateway's storage-mcp tools.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from . import config

CONTENT_TYPES = {
    "xml": "application/xml", "svg": "image/svg+xml", "json": "application/json",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf", "md": "text/markdown", "markdown": "text/markdown", "txt": "text/plain",
    "csv": "text/csv", "rst": "text/x-rst", "vsdx": "application/vnd.ms-visio.drawing.main+xml",
}


def content_type_for(name: str, default: str = "application/octet-stream") -> str:
    """Content type from a file name's extension — the one map every uploader uses."""
    return CONTENT_TYPES.get(name.rsplit(".", 1)[-1].lower(), default) if "." in name else default


def _ref(aid, name):
    return f"art://{aid}/{name}"


class LocalStore:
    def __init__(self, root):
        self.root = root; os.makedirs(root, exist_ok=True)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        aid = uuid.uuid4().hex[:12]; d = os.path.join(self.root, aid); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, name), "wb").write(data)
        return _ref(aid, name)

    def get(self, ref) -> bytes:
        aid, name = _split(ref)
        return open(os.path.join(self.root, aid, name), "rb").read()

    def info(self, ref) -> dict:
        aid, name = _split(ref); p = os.path.join(self.root, aid, name)
        return {"ref": ref, "name": name, "content_type": content_type_for(name),
                "size": os.path.getsize(p), "backend": "file"}

    def list(self, prefix="", limit=100) -> list[dict]:
        out = []
        for aid in sorted(os.listdir(self.root), key=lambda a: os.path.getmtime(os.path.join(self.root, a)), reverse=True):
            d = os.path.join(self.root, aid)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if name.startswith(prefix):
                    out.append(self.info(_ref(aid, name)))
                if len(out) >= limit:
                    return out
        return out


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
        return _ref(aid, name)

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

    def list(self, prefix="", limit=100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, name, content_type, size, created_at FROM lab_artifacts "
                             "WHERE name LIKE %s ORDER BY created_at DESC LIMIT %s", (prefix + "%", limit)).fetchall()
        return [{"ref": _ref(r[0], r[1]), "name": r[1], "content_type": r[2], "size": r[3],
                 "created_at": r[4].isoformat(), "backend": "postgres"} for r in rows]


class S3Store:
    """S3-compatible bucket: key = <prefix>/<id>/<name>. Railway Bucket / MinIO / Azure Blob (via its
    S3 gateway) all speak this. Credentials come from S3_* env (see shared/config.py)."""

    def __init__(self, url):
        import boto3
        from botocore.config import Config
        rest = url[len("s3://"):]
        self.bucket, _, prefix = rest.partition("/")
        if not self.bucket:
            raise ValueError(f"S3 store url needs a bucket: {url}")
        self.prefix = prefix.strip("/")
        style = "virtual" if (config.S3_URL_STYLE or "path").lower().startswith("virtual") else "path"
        self.s3 = boto3.client(
            "s3", endpoint_url=config.S3_ENDPOINT or None, region_name=config.S3_REGION or None,
            aws_access_key_id=config.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY or None,
            config=Config(s3={"addressing_style": style}, retries={"max_attempts": 3}))

    def _key(self, aid, name=""):
        return "/".join(p for p in (self.prefix, aid, name) if p)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        aid = uuid.uuid4().hex[:12]
        self.s3.put_object(Bucket=self.bucket, Key=self._key(aid, name), Body=data, ContentType=content_type)
        return _ref(aid, name)

    def get(self, ref) -> bytes:
        aid, name = _split(ref)
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self._key(aid, name))["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            raise KeyError(f"unknown artifact {ref}") from None

    def info(self, ref) -> dict:
        aid, name = _split(ref)
        try:
            h = self.s3.head_object(Bucket=self.bucket, Key=self._key(aid, name))
        except self.s3.exceptions.ClientError as e:              # 404 surfaces as ClientError on head
            raise KeyError(f"unknown artifact {ref}") from e
        return {"ref": ref, "name": name, "content_type": h.get("ContentType"),
                "size": h.get("ContentLength"), "created_at": h["LastModified"].isoformat(), "backend": "s3"}

    def list(self, prefix="", limit=100) -> list[dict]:
        out, token = [], None
        while len(out) < limit:
            kw = {"Bucket": self.bucket, "Prefix": self._key(""), "MaxKeys": min(1000, limit)}
            if token:
                kw["ContinuationToken"] = token
            page = self.s3.list_objects_v2(**kw)
            for o in page.get("Contents", []):
                rel = o["Key"][len(self.prefix) + 1:] if self.prefix else o["Key"]
                aid, _, name = rel.partition("/")
                if name and name.startswith(prefix):
                    out.append({"ref": _ref(aid, name), "name": name, "content_type": content_type_for(name),
                                "size": o["Size"], "created_at": o["LastModified"].isoformat(), "backend": "s3"})
                if len(out) >= limit:
                    break
            token = page.get("NextContinuationToken")
            if not token:
                break
        out.sort(key=lambda i: i["created_at"], reverse=True)
        return out


def _split(ref):
    if not ref.startswith("art://"):
        raise ValueError(f"not an artifact ref: {ref}")
    aid, _, name = ref[6:].partition("/")
    return aid, name


Store = LocalStore | PostgresStore | S3Store
_stores: dict[str, "Store"] = {}


def store(url: str | None = None) -> "Store":
    """The store behind a URL (default ARTIFACTS_URL) — one client per URL per process."""
    url = url or config.ARTIFACTS_URL
    s = _stores.get(url)
    if s is None:
        if url.startswith("file://"):
            s = LocalStore(url[7:])
        elif url.startswith("s3://"):
            s = S3Store(url)
        else:
            s = PostgresStore(url)
        _stores[url] = s
    return s


def uploads():
    """Where submitted inputs go (UPLOADS_URL; = the artifact store unless a bucket is configured)."""
    return store(config.UPLOADS_URL)


def put_file(path, content_type=None, target=None) -> str:
    ct = content_type or content_type_for(path)
    return (target or store()).put(os.path.basename(path), open(path, "rb").read(), ct)
