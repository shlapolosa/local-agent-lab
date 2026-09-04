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

Two write paths, one ref:
  put(name, data, content_type)                      by value  — small objects already in memory
  put_stream(name, fileobj, content_type, size_hint) by stream — never materialised
`IteratorReader` adapts a source that YIELDS chunks (a port's `open()`) to the file-like `put_stream`
reads, without ever joining them.

`put_stream` exists because an input can be a Teams meeting recording: hundreds of megabytes to
gigabytes, which `put`'s `bytes` argument would hold in RAM twice on an 8 GB machine. It copies a
file-like source (a urllib/requests response is one) to the backend in `CHUNK` pieces. `put` does NOT
delegate to it: each backend's by-value write is a single round trip (one `put_object`, one INSERT,
one `open().write()`) and routing it through the transfer manager or a spool file would buy nothing.
What must have one home — the artifact id, the size ceiling and its message — lives in `_BaseStore`,
so both paths are governed by the same policy.

Size policy: `max_bytes` (default `config.ARTIFACT_MAX_BYTES`) is enforced on BOTH paths — up front
from `size_hint` when the caller knows the length, and again while streaming through `_CappedReader`,
because an absent or lying `Content-Length` must not defeat the cap. `PostgresStore` caps far lower
(`config.ARTIFACT_INLINE_MAX_BYTES`) and REFUSES with an explanation: a bytea row is materialised in
RAM at both ends, so a recording belongs in a bucket, not in the database.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

from lab.platform import config
from lab.platform.filetypes import FILE_TYPES, CONTENT_TYPES, content_type_for, kind_for  # noqa: F401  (re-exported: the one map)


CHUNK = 1 << 20          # 1 MiB — the unit every streaming copy moves; nothing bigger is ever held


def _ref(aid, name):
    return f"art://{aid}/{name}"


class ArtifactTooLarge(ValueError):
    """Refused: the object is bigger than this store is configured to hold. A ValueError so callers
    that already treat a bad write as one keep working; catch it by name to fall back to a bucket."""


class _CappedReader:
    """A read-only file wrapper that counts what it hands out and refuses to exceed `cap`.

    Wrapping the SOURCE (rather than counting in our own loop) is what lets a cap apply to a reader
    we do not drive — boto3's transfer manager pulls the parts itself. An unbounded `read()` is
    clamped to CHUNK on purpose: this object exists so that nothing is ever materialised whole."""

    def __init__(self, fileobj, cap, message):
        self._f, self._cap, self._message, self._seen = fileobj, cap, message, 0

    def read(self, n=-1):
        chunk = self._f.read(CHUNK if n is None or n < 0 else n)
        self._seen += len(chunk)
        if self._seen > self._cap:
            raise ArtifactTooLarge(f"{self._message} — exceeded while streaming (no usable length was declared)")
        return chunk


_EXHAUSTED = object()          # a sentinel, so an empty chunk mid-stream is not mistaken for the end


class IteratorReader:
    """A `read()`-able file over a chunk ITERATOR — the seam between a source that YIELDS bytes and
    `put_stream`, which READS them.

    A collaboration provider's `open()` hands back an iterator of chunks; every backend's streaming
    write wants a file-like. Joining the iterator to bridge them would defeat the entire point, so
    this holds at most one chunk plus the unread remainder of the last, and an unbounded `read()` is
    clamped to `CHUNK` for the same reason `_CappedReader` clamps one."""

    def __init__(self, chunks):
        self._chunks, self._buf = iter(chunks), b""
        self.count = 0                 # bytes handed out so far — what a caller reports it stored

    def read(self, n=-1):
        if n is None or n < 0:
            n = CHUNK
        while len(self._buf) < n:
            chunk = next(self._chunks, _EXHAUSTED)
            if chunk is _EXHAUSTED:
                break
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        self.count += len(out)
        return out


class _BaseStore:
    """The write policy every backend shares: the artifact id, and ONE size ceiling honoured by both
    the by-value and the streaming path. The default comes from config (deployment policy) but enters
    through the constructor, so a caller or a test can inject its own."""

    def __init__(self, *, max_bytes=None):
        self.max_bytes = config.ARTIFACT_MAX_BYTES if max_bytes is None else max_bytes

    @staticmethod
    def _new_id():
        return uuid.uuid4().hex[:12]

    def _limit_message(self, name):
        return (f"artifact '{name}' exceeds this store's {self.max_bytes} byte limit "
                f"(config ARTIFACT_MAX_BYTES, or the store's max_bytes)")

    def _guard(self, name, size):
        """Refuse a known-oversize object before a byte moves."""
        if size is not None and size > self.max_bytes:
            raise ArtifactTooLarge(f"{self._limit_message(name)} — declared {size} bytes")

    def _capped(self, name, fileobj, size_hint):
        self._guard(name, size_hint)
        return _CappedReader(fileobj, self.max_bytes, self._limit_message(name))


class LocalStore(_BaseStore):
    def __init__(self, root, *, max_bytes=None):
        super().__init__(max_bytes=max_bytes)
        self.root = root; os.makedirs(root, exist_ok=True)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        self._guard(name, len(data))
        aid = self._new_id(); d = os.path.join(self.root, aid); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, name), "wb").write(data)
        return _ref(aid, name)

    def put_stream(self, name, fileobj, content_type="application/octet-stream", size_hint=None) -> str:
        """Chunked copy to disk — the source is never read whole. A refusal (or any failure) takes
        the half-written directory with it: no ref is ever handed out for a partial object."""
        src = self._capped(name, fileobj, size_hint)
        aid = self._new_id(); d = os.path.join(self.root, aid); os.makedirs(d, exist_ok=True)
        try:
            with open(os.path.join(d, name), "wb") as f:
                shutil.copyfileobj(src, f, CHUNK)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
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


class PostgresStore(_BaseStore):
    DDL = """CREATE TABLE IF NOT EXISTS lab_artifacts (
               id TEXT PRIMARY KEY, name TEXT NOT NULL, content_type TEXT, size INTEGER,
               created_at TIMESTAMPTZ NOT NULL, data BYTEA NOT NULL)"""
    SPOOL_MAX_MEMORY = 8 * 1024 * 1024        # a stream bigger than this spools to a temp FILE, not RAM

    def __init__(self, dsn, *, connect=None, max_bytes=None, inline_max_bytes=None):
        """`connect` = a `psycopg.connect`-shaped callable (tests inject an in-memory one).
        This backend stores the object INLINE, so its ceiling is the lower of the overall cap and
        `inline_max_bytes` (config.ARTIFACT_INLINE_MAX_BYTES)."""
        inline = config.ARTIFACT_INLINE_MAX_BYTES if inline_max_bytes is None else inline_max_bytes
        overall = config.ARTIFACT_MAX_BYTES if max_bytes is None else max_bytes
        super().__init__(max_bytes=min(overall, inline))
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self._connect = connect; self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        with self._conn() as c:
            c.execute(self.DDL)

    def _conn(self):
        return self._connect(self.dsn, autocommit=True)

    def _limit_message(self, name):
        return (f"artifact '{name}' exceeds the {self.max_bytes} byte inline limit of the postgres "
                "artifact store, which keeps objects in a bytea column: the row is materialised in "
                "memory at both ends (and PostgreSQL stops at 1 GB), so a recording-sized object is "
                "refused rather than stored badly. Configure a bucket for large objects — "
                "UPLOADS_URL=s3://<bucket>[/prefix] plus the S3_* credentials — and retry.")

    def _insert(self, name, data: bytes, content_type) -> str:
        aid = self._new_id()
        with self._conn() as c:
            c.execute("INSERT INTO lab_artifacts (id, name, content_type, size, created_at, data) VALUES (%s,%s,%s,%s,%s,%s)",
                      (aid, name, content_type, len(data), datetime.now(timezone.utc), data))
        return _ref(aid, name)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        self._guard(name, len(data))
        return self._insert(name, data, content_type)

    def put_stream(self, name, fileobj, content_type="application/octet-stream", size_hint=None) -> str:
        """Spool to a SpooledTemporaryFile (RAM up to SPOOL_MAX_MEMORY, then disk) and insert once.
        Above the inline limit this REFUSES: a multi-gigabyte bytea is the wrong answer, and telling
        the operator to configure a bucket is better than doing it."""
        src = self._capped(name, fileobj, size_hint)
        with tempfile.SpooledTemporaryFile(max_size=self.SPOOL_MAX_MEMORY) as spool:
            shutil.copyfileobj(src, spool, CHUNK)
            spool.seek(0)
            data = spool.read()                   # bounded by the inline cap enforced above
        return self._insert(name, data, content_type)

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


class S3Store(_BaseStore):
    """S3-compatible bucket: key = <prefix>/<id>/<name>. Railway Bucket / MinIO / Azure Blob (via its
    S3 gateway) all speak this. Credentials come from S3_* env (see src/lab/platform/config.py)."""

    def __init__(self, url, *, boto=None, max_bytes=None):
        """`boto` = a module with `client(...)` (boto3 by default; tests inject a recorder)."""
        super().__init__(max_bytes=max_bytes)
        if boto is None:
            import boto3 as boto
        from botocore.config import Config
        rest = url[len("s3://"):]
        self.bucket, _, prefix = rest.partition("/")
        if not self.bucket:
            raise ValueError(f"S3 store url needs a bucket: {url}")
        self.prefix = prefix.strip("/")
        style = "virtual" if (config.S3_URL_STYLE or "path").lower().startswith("virtual") else "path"
        self.s3 = boto.client(
            "s3", endpoint_url=config.S3_ENDPOINT or None, region_name=config.S3_REGION or None,
            aws_access_key_id=config.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY or None,
            config=Config(s3={"addressing_style": style}, retries={"max_attempts": 3}))

    def _key(self, aid, name=""):
        return "/".join(p for p in (self.prefix, aid, name) if p)

    def put(self, name, data: bytes, content_type="application/octet-stream") -> str:
        self._guard(name, len(data))
        aid = self._new_id()
        self.s3.put_object(Bucket=self.bucket, Key=self._key(aid, name), Body=data, ContentType=content_type)
        return _ref(aid, name)

    def put_stream(self, name, fileobj, content_type="application/octet-stream", size_hint=None) -> str:
        """boto3's `upload_fileobj` — the transfer manager reads the source in parts and switches to
        a real multipart upload past its threshold, so a gigabyte never lands in this process. The
        cap rides on the wrapped fileobj boto3 itself reads from, which is the only way to enforce it
        on a transfer we do not drive; the manager aborts the upload when that raises."""
        src = self._capped(name, fileobj, size_hint)
        aid = self._new_id()
        self.s3.upload_fileobj(src, self.bucket, self._key(aid, name), ExtraArgs={"ContentType": content_type})
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


# The store PORT, structurally: put / put_stream / get / info / list. Kept a union (not an ABC) —
# the three implementations already share `_BaseStore` for the write policy they must not diverge on.
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
