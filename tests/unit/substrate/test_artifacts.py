"""src/lab/substrate/artifacts.py — the artifact store behind `art://<id>/<name>` refs. OFFLINE: the Postgres
backend runs on an in-memory table injected through `connect=`, the S3 backend on a recording client
injected through `boto=`, LocalStore on a temp dir; the `store()` factory is exercised with the
backend classes swapped for recorders (no DB, no bucket)."""
import os
import sys
import tempfile
from datetime import datetime, timezone


from lab.substrate import artifacts

from lab.platform import config, filetypes


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}")


# ------------------------------------------------------------------ refs + the file-type table
def test_ref_format_and_parse():
    assert artifacts._ref("ab12", "m.xml") == "art://ab12/m.xml"
    assert artifacts._split("art://ab12/m.xml") == ("ab12", "m.xml")
    assert artifacts._split("art://ab12") == ("ab12", "")
    assert artifacts._split("art://ab12/dir/m.xml") == ("ab12", "dir/m.xml")
    e = _raises(ValueError, artifacts._split, "/tmp/m.xml")
    assert "not an artifact ref" in str(e)


def test_file_type_helpers():
    assert filetypes._ext("A.B.VSDX") == "vsdx" and filetypes._ext("noext") == ""
    assert artifacts.kind_for("x.png") == "image" and artifacts.kind_for("r.PDF") == "document"
    assert artifacts.kind_for("s.json") == "artifact" and artifacts.kind_for("q.bin", "other") == "other"
    assert artifacts.content_type_for("f.webp") == "image/webp"
    assert artifacts.content_type_for("f.zzz") == "application/octet-stream"
    for ext, (ct, kind) in artifacts.FILE_TYPES.items():
        assert kind in ("vsdx", "image", "document", "artifact"), ext
        assert artifacts.CONTENT_TYPES[ext] == ct


# ------------------------------------------------------------------ LocalStore
def test_local_store_round_trip():
    with tempfile.TemporaryDirectory() as d:
        s = artifacts.LocalStore(os.path.join(d, "arts"))
        ref = s.put("m.xml", b"<x/>", "application/xml")
        aid, name = artifacts._split(ref)
        assert len(aid) == 12 and name == "m.xml" and s.get(ref) == b"<x/>"
        info = s.info(ref)
        assert info == {"ref": ref, "name": "m.xml", "content_type": "application/xml", "size": 4, "backend": "file"}
        ref2 = s.put("v.svg", b"<svg/>")
        open(os.path.join(s.root, "stray-file"), "w").write("not a dir")     # ignored by list()
        lst = s.list()
        assert {i["ref"] for i in lst} == {ref, ref2}
        assert [i["name"] for i in s.list(prefix="v")] == ["v.svg"]
        assert len(s.list(limit=1)) == 1
        _raises(FileNotFoundError, s.get, "art://nope/x.xml")
        _raises(ValueError, s.get, "not-a-ref")
        # put_file: content type from the name, explicit target
        p = os.path.join(d, "spec.json"); open(p, "wb").write(b"{}")
        ref3 = artifacts.put_file(p, target=s)
        assert s.info(ref3)["content_type"] == "application/json" and s.get(ref3) == b"{}"
        ref4 = artifacts.put_file(p, content_type="text/plain", target=s)
        assert ref4.endswith("/spec.json")


# ------------------------------------------------------------------ PostgresStore on a fake psycopg
class FakePg:
    """psycopg.connect stand-in: one in-memory `lab_artifacts` table, every (sql, params) recorded."""

    def __init__(self):
        self.rows, self.log = {}, []

    def connect(self, dsn, autocommit=False):
        self.log.append(("connect", dsn, autocommit))
        return _Conn(self)


class _Cur:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return list(self.rows)


class _Conn:
    def __init__(self, db): self.db = db
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        self.db.log.append((sql, params))
        rows = self.db.rows
        if sql.startswith("CREATE TABLE"):
            return _Cur([])
        if sql.startswith("INSERT"):
            aid, name, ct, size, created, data = params
            rows[aid] = {"name": name, "content_type": ct, "size": size, "created_at": created, "data": data}
            return _Cur([])
        if sql.startswith("SELECT data"):
            r = rows.get(params[0]); return _Cur([(r["data"],)] if r else [])
        if sql.startswith("SELECT name, content_type, size, created_at"):
            r = rows.get(params[0]); return _Cur([(r["name"], r["content_type"], r["size"], r["created_at"])] if r else [])
        if sql.startswith("SELECT id, name, content_type, size, created_at"):
            like, limit = params
            hit = [(aid, r["name"], r["content_type"], r["size"], r["created_at"]) for aid, r in rows.items()
                   if r["name"].startswith(like.rstrip("%"))]
            return _Cur(sorted(hit, key=lambda t: t[4], reverse=True)[:limit])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_postgres_store_on_fake_connection():
    db = FakePg()
    s = artifacts.PostgresStore("postgresql+psycopg://u:p@neon/litellm", connect=db.connect)
    assert s.dsn == "postgresql://u:p@neon/litellm", "psycopg dialect prefix normalised"
    assert db.log[0] == ("connect", s.dsn, True) and db.log[1][0].startswith("CREATE TABLE IF NOT EXISTS lab_artifacts")
    ref = s.put("m.xml", b"<x/>", "application/xml")
    aid, _ = artifacts._split(ref)
    ins = next(l for l in db.log if l[0].startswith("INSERT"))
    assert ins[1][:4] == (aid, "m.xml", "application/xml", 4) and isinstance(ins[1][4], datetime) and ins[1][5] == b"<x/>"
    assert s.get(ref) == b"<x/>"
    info = s.info(ref)
    assert info["backend"] == "postgres" and info["name"] == "m.xml" and info["size"] == 4 and info["created_at"].endswith("+00:00")
    ref2 = s.put("v.svg", b"<svg/>")
    assert {i["ref"] for i in s.list()} == {ref, ref2}
    assert [i["name"] for i in s.list(prefix="v", limit=5)] == ["v.svg"]
    q = [l for l in db.log if l[0].startswith("SELECT id")][-1]
    assert q[1] == ("v%", 5)
    _raises(KeyError, s.get, "art://nope/x")
    _raises(KeyError, s.info, "art://nope/x")


# ------------------------------------------------------------------ S3Store on a fake boto3
class FakeS3:
    class exceptions:
        class NoSuchKey(Exception): ...
        class ClientError(Exception): ...

    def __init__(self):
        self.objects, self.calls = {}, []          # key -> (body, ct, last_modified)

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Bucket, Key, ContentType))
        self.objects[Key] = (Body, ContentType, datetime(2026, 9, 1, tzinfo=timezone.utc).replace(second=len(self.objects)))

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None):
        """boto3's transfer manager, faked: it reads the stream in parts (never whole), exactly the
        property the store depends on for a multi-gigabyte recording."""
        parts, reads = [], 0
        while True:
            chunk = Fileobj.read(1 << 16)
            reads += 1
            if not chunk:
                break
            parts.append(chunk)
        self.calls.append(("upload_fileobj", Bucket, Key, ExtraArgs, reads))
        body = b"".join(parts)
        self.objects[Key] = (body, (ExtraArgs or {}).get("ContentType"),
                             datetime(2026, 9, 1, tzinfo=timezone.utc).replace(second=len(self.objects)))

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey()
        import io
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def head_object(self, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        if Key not in self.objects:
            raise self.exceptions.ClientError("404")
        body, ct, lm = self.objects[Key]
        return {"ContentType": ct, "ContentLength": len(body), "LastModified": lm}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        self.calls.append(("list", Bucket, Prefix, MaxKeys, ContinuationToken))
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + MaxKeys]
        out = {"Contents": [{"Key": k, "Size": len(self.objects[k][0]), "LastModified": self.objects[k][2]} for k in page]}
        if start + MaxKeys < len(keys):
            out["NextContinuationToken"] = str(start + MaxKeys)
        return out


class FakeBoto:
    def __init__(self): self.s3, self.kw = FakeS3(), None
    def client(self, name, **kw):
        assert name == "s3"; self.kw = kw; return self.s3


def _with_s3_config(**vals):
    saved = {k: getattr(config, k) for k in vals}
    for k, v in vals.items():
        setattr(config, k, v)
    return saved


def test_s3_store_on_fake_boto():
    saved = _with_s3_config(S3_ENDPOINT="https://bucket.example", S3_REGION="auto", S3_ACCESS_KEY_ID="ak",
                            S3_SECRET_ACCESS_KEY="sk", S3_URL_STYLE="virtual")
    try:
        _raises(ValueError, artifacts.S3Store, "s3://", boto=FakeBoto())
        b = FakeBoto()
        s = artifacts.S3Store("s3://lab-uploads/in/box/", boto=b)
        assert (s.bucket, s.prefix) == ("lab-uploads", "in/box")
        assert b.kw["endpoint_url"] == "https://bucket.example" and b.kw["region_name"] == "auto"
        assert b.kw["aws_access_key_id"] == "ak" and b.kw["aws_secret_access_key"] == "sk"
        assert b.kw["config"].s3["addressing_style"] == "virtual" and b.kw["config"].retries["max_attempts"] == 3
        assert s._key("id1", "a.png") == "in/box/id1/a.png" and s._key("") == "in/box"
        ref = s.put("d.vsdx", b"PK..", "application/vnd.ms-visio.drawing.main+xml")
        aid, _ = artifacts._split(ref)
        assert b.s3.calls[0] == ("put", "lab-uploads", f"in/box/{aid}/d.vsdx", "application/vnd.ms-visio.drawing.main+xml")
        assert s.get(ref) == b"PK.."
        info = s.info(ref)
        assert info["backend"] == "s3" and info["size"] == 4 and info["name"] == "d.vsdx" and info["created_at"].startswith("2026-09-01")
        _raises(KeyError, s.get, "art://nope/d.vsdx")
        _raises(KeyError, s.info, "art://nope/d.vsdx")
        s.put("r.docx", b"12345"); s.put("r2.md", b"#")
        b.s3.objects["in/box/dangling"] = (b"", "", datetime(2026, 1, 1, tzinfo=timezone.utc))   # no "/name" -> skipped
        lst = s.list()
        assert [i["name"] for i in lst] == ["r2.md", "r.docx", "d.vsdx"], "newest first"
        assert lst[0]["content_type"] == "text/markdown" and lst[0]["backend"] == "s3"
        assert [i["name"] for i in s.list(prefix="r")] == ["r2.md", "r.docx"]
        # pagination: MaxKeys = limit; a page that does not fill `limit` continues with the token
        b.s3.calls.clear()
        assert len(s.list(limit=2)) == 2
        assert [c[4] for c in b.s3.calls if c[0] == "list"] == [None], "a full first page ends the walk"
        b.s3.calls.clear()
        assert s.list(prefix="zzz-none", limit=2) == []
        pages = [c for c in b.s3.calls if c[0] == "list"]
        assert [(c[3], c[4]) for c in pages] == [(2, None), (2, "2")], "4 keys, 2 per page, then no token"
    finally:
        _with_s3_config(**saved)


def test_s3_store_defaults_no_prefix_path_style():
    saved = _with_s3_config(S3_ENDPOINT=None, S3_REGION=None, S3_ACCESS_KEY_ID=None, S3_SECRET_ACCESS_KEY=None, S3_URL_STYLE=None)
    try:
        b = FakeBoto()
        s = artifacts.S3Store("s3://bucket-only", boto=b)
        assert (s.bucket, s.prefix) == ("bucket-only", "") and b.kw["endpoint_url"] is None
        assert b.kw["config"].s3["addressing_style"] == "path"
        ref = s.put("x.png", b"\x89PNG")
        aid, _ = artifacts._split(ref)
        assert s._key(aid, "x.png") == f"{aid}/x.png" and s._key("") == ""
        assert [i["ref"] for i in s.list()] == [ref]
    finally:
        _with_s3_config(**saved)


def test_default_wiring_resolves_psycopg_and_boto3():
    """With nothing injected the stores reach for `psycopg.connect` / `boto3.client` — stand the
    modules in via sys.modules so that default path runs without a database or a bucket."""
    import types
    db, b = FakePg(), FakeBoto()
    saved = {k: sys.modules.get(k) for k in ("psycopg", "boto3")}
    sys.modules["psycopg"] = types.SimpleNamespace(connect=db.connect)
    sys.modules["boto3"] = types.SimpleNamespace(client=b.client)
    try:
        s = artifacts.PostgresStore("postgresql://u@h/db")
        assert db.log[0][0] == "connect" and s._connect == db.connect
        s3 = artifacts.S3Store("s3://bkt/p")
        assert s3.s3 is b.s3 and b.kw is not None
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ------------------------------------------------------------------ the store() factory
def test_store_factory_by_scheme_and_caching():
    saved_stores = dict(artifacts._stores)
    saved = {"PostgresStore": artifacts.PostgresStore, "S3Store": artifacts.S3Store}
    saved_cfg = {"ARTIFACTS_URL": config.ARTIFACTS_URL, "UPLOADS_URL": config.UPLOADS_URL}
    artifacts.PostgresStore = lambda url: ("pg", url)
    artifacts.S3Store = lambda url: ("s3", url)
    try:
        artifacts._stores.clear()
        with tempfile.TemporaryDirectory() as d:
            local = artifacts.store(f"file://{d}")
            assert isinstance(local, artifacts.LocalStore) and local.root == d
            assert artifacts.store(f"file://{d}") is local, "one client per URL per process"
        assert artifacts.store("s3://b/p") == ("s3", "s3://b/p")
        assert artifacts.store("postgresql://u@h/db") == ("pg", "postgresql://u@h/db")
        config.ARTIFACTS_URL, config.UPLOADS_URL = "postgresql://default/db", "s3://uploads"
        assert artifacts.store() == ("pg", "postgresql://default/db")
        assert artifacts.uploads() == ("s3", "s3://uploads")
        config.UPLOADS_URL = config.ARTIFACTS_URL
        assert artifacts.uploads() is artifacts.store(), "no bucket configured -> the same store"
    finally:
        artifacts.PostgresStore, artifacts.S3Store = saved["PostgresStore"], saved["S3Store"]
        config.ARTIFACTS_URL, config.UPLOADS_URL = saved_cfg["ARTIFACTS_URL"], saved_cfg["UPLOADS_URL"]
        artifacts._stores.clear(); artifacts._stores.update(saved_stores)


# ------------------------------------------------------------------ streaming writes (put_stream)
class _StreamSource:
    """A read-only fileobj that yields `total` bytes and REFUSES any read larger than `max_read` —
    the proof that a backend streams: a store that materialises the object (`read()` / `read(-1)`)
    blows up here instead of quietly allocating a gigabyte."""

    def __init__(self, total, max_read=artifacts.CHUNK, fill=b"\x01"):
        self.total, self.max_read, self.fill = total, max_read, fill
        self.left, self.reads = total, 0

    def read(self, n=-1):
        self.reads += 1
        if n is None or n < 0 or n > self.max_read:
            raise AssertionError(f"whole-object read requested (n={n}) — the store must chunk")
        take = min(n, self.left)
        self.left -= take
        return self.fill * take


def test_stream_source_double_refuses_a_whole_object_read():
    src = _StreamSource(3, max_read=2)
    assert src.read(2) == b"\x01\x01" and src.read(2) == b"\x01" and src.read(2) == b""
    _raises(AssertionError, _StreamSource(3, max_read=2).read)          # read() = the whole thing


def test_capped_reader_clamps_an_unbounded_read():
    """`read()` / `read(-1)` would materialise the object — the wrapper hands back a CHUNK instead."""
    r = artifacts._CappedReader(_StreamSource(artifacts.CHUNK * 3), artifacts.CHUNK * 3, "too big")
    assert len(r.read()) == artifacts.CHUNK and len(r.read(-1)) == artifacts.CHUNK
    assert len(r.read(10)) == 10


def test_local_store_put_stream_is_chunked_and_ref_shaped_like_put():
    with tempfile.TemporaryDirectory() as d:
        s = artifacts.LocalStore(os.path.join(d, "arts"))
        n = artifacts.CHUNK * 2 + 7
        src = _StreamSource(n)
        ref = s.put_stream("rec.mp4", src, "video/mp4", size_hint=n)
        aid, name = artifacts._split(ref)
        assert len(aid) == 12 and name == "rec.mp4", "same art://<12-hex>/<name> shape as put()"
        assert src.reads >= 3, "streamed in chunks, not one read"
        assert s.info(ref) == {"ref": ref, "name": "rec.mp4", "content_type": artifacts.content_type_for("rec.mp4"),
                               "size": n, "backend": "file"}, "info reads the type off the name, as it does for put()"
        assert s.get(ref) == b"\x01" * n
        assert {i["ref"] for i in s.list()} == {ref}
        # no size_hint (a Graph download with no Content-Length) still works
        ref2 = s.put_stream("small.bin", _StreamSource(5))
        assert s.get(ref2) == b"\x01" * 5 and s.info(ref2)["content_type"] == "application/octet-stream"


def test_local_store_cap_by_hint_and_mid_stream_leaves_nothing_behind():
    with tempfile.TemporaryDirectory() as d:
        s = artifacts.LocalStore(os.path.join(d, "arts"), max_bytes=1000)
        # 1. size_hint over the cap: refused BEFORE a single byte is read
        src = _StreamSource(10)
        e = _raises(artifacts.ArtifactTooLarge, s.put_stream, "big.mp4", src, "video/mp4", size_hint=5000)
        assert src.reads == 0 and "1000" in str(e) and "big.mp4" in str(e)
        assert os.listdir(s.root) == [], "nothing created for a refused upload"
        # 2. a LYING (or absent) Content-Length must not defeat the cap: it trips mid-stream
        src = _StreamSource(4000)
        e = _raises(artifacts.ArtifactTooLarge, s.put_stream, "liar.mp4", src, "video/mp4", size_hint=10)
        assert "1000" in str(e)
        assert os.listdir(s.root) == [], "the partial file is cleaned up"
        assert artifacts.ArtifactTooLarge("x").__class__.__mro__[1] is ValueError, "callers catching ValueError still work"
        # 3. exactly at the cap is fine
        ref = s.put_stream("edge.bin", _StreamSource(1000))
        assert s.info(ref)["size"] == 1000
        # 4. the by-value path honours the same cap
        _raises(artifacts.ArtifactTooLarge, s.put, "big.bin", b"x" * 1001)


def test_local_store_cap_defaults_to_config():
    with tempfile.TemporaryDirectory() as d:
        saved = config.ARTIFACT_MAX_BYTES
        config.ARTIFACT_MAX_BYTES = 4
        try:
            s = artifacts.LocalStore(os.path.join(d, "arts"))
            assert s.max_bytes == 4, "the default comes from config, not a literal in the store"
            _raises(artifacts.ArtifactTooLarge, s.put, "x.bin", b"12345")
        finally:
            config.ARTIFACT_MAX_BYTES = saved


def test_postgres_put_stream_spools_and_refuses_a_recording():
    db = FakePg()
    s = artifacts.PostgresStore("postgresql://u@h/db", connect=db.connect, inline_max_bytes=512)
    ref = s.put_stream("spec.json", _StreamSource(300), "application/json", size_hint=300)
    aid, name = artifacts._split(ref)
    assert len(aid) == 12 and name == "spec.json"
    ins = [l for l in db.log if l[0].startswith("INSERT")][-1]
    assert ins[1][:4] == (aid, "spec.json", "application/json", 300) and ins[1][5] == b"\x01" * 300
    assert s.get(ref) == b"\x01" * 300 and s.info(ref)["size"] == 300
    # refused by the hint — and the message tells the operator what to do instead
    src = _StreamSource(10)
    e = _raises(artifacts.ArtifactTooLarge, s.put_stream, "meeting.mp4", src, "video/mp4", size_hint=10 ** 9)
    assert src.reads == 0
    for phrase in ("meeting.mp4", "bytea", "512", "UPLOADS_URL=s3://"):
        assert phrase in str(e), f"{phrase!r} missing from: {e}"
    # ... and mid-stream, when the caller lied about the length
    e = _raises(artifacts.ArtifactTooLarge, s.put_stream, "meeting.mp4", _StreamSource(4000), "video/mp4")
    assert "UPLOADS_URL=s3://" in str(e)
    assert not [l for l in db.log if l[0].startswith("INSERT") and l[1][1] == "meeting.mp4"], "nothing written"
    # the by-value path shares the ceiling
    _raises(artifacts.ArtifactTooLarge, s.put, "big.bin", b"x" * 513)


def test_postgres_inline_cap_defaults_to_config_and_respects_the_overall_cap():
    db = FakePg()
    saved = config.ARTIFACT_INLINE_MAX_BYTES
    config.ARTIFACT_INLINE_MAX_BYTES = 64
    try:
        s = artifacts.PostgresStore("postgresql://u@h/db", connect=db.connect)
        assert s.max_bytes == 64, "postgres caps at the inline ceiling"
    finally:
        config.ARTIFACT_INLINE_MAX_BYTES = saved
    # an explicit overall cap below the inline ceiling still wins (min of the two)
    s = artifacts.PostgresStore("postgresql://u@h/db", connect=db.connect, max_bytes=8, inline_max_bytes=512)
    assert s.max_bytes == 8
    _raises(artifacts.ArtifactTooLarge, s.put_stream, "x.bin", _StreamSource(20))


def test_s3_put_stream_uses_upload_fileobj_multipart():
    saved = _with_s3_config(S3_ENDPOINT=None, S3_REGION=None, S3_ACCESS_KEY_ID=None,
                            S3_SECRET_ACCESS_KEY=None, S3_URL_STYLE=None)
    try:
        b = FakeBoto()
        s = artifacts.S3Store("s3://lab-uploads/in", boto=b)
        n = artifacts.CHUNK + 11
        src = _StreamSource(n)
        ref = s.put_stream("rec.mp4", src, "video/mp4", size_hint=n)
        aid, name = artifacts._split(ref)
        assert len(aid) == 12 and name == "rec.mp4"
        call = b.s3.calls[0]
        assert call[:3] == ("upload_fileobj", "lab-uploads", f"in/{aid}/rec.mp4")
        assert call[3] == {"ContentType": "video/mp4"}, "content type travels as ExtraArgs"
        assert call[4] >= 2, "boto read the object in parts, never whole"
        assert s.get(ref) == b"\x01" * n and s.info(ref)["size"] == n
        # the cap wraps the fileobj boto3 itself reads from, so a lying Content-Length still trips
        s2 = artifacts.S3Store("s3://lab-uploads", boto=FakeBoto(), max_bytes=1000)
        e = _raises(artifacts.ArtifactTooLarge, s2.put_stream, "liar.mp4", _StreamSource(5000), "video/mp4")
        assert "1000" in str(e)
        src = _StreamSource(10)
        _raises(artifacts.ArtifactTooLarge, s2.put_stream, "big.mp4", src, "video/mp4", size_hint=2000)
        assert src.reads == 0
        _raises(artifacts.ArtifactTooLarge, s2.put, "big.bin", b"x" * 1001)
    finally:
        _with_s3_config(**saved)


def test_put_and_put_stream_agree_on_the_ref_across_backends():
    """Same shape, same readback, same info from either path — a caller cannot tell them apart."""
    import io
    with tempfile.TemporaryDirectory() as d:
        db, b = FakePg(), FakeBoto()
        saved = _with_s3_config(S3_ENDPOINT=None, S3_REGION=None, S3_ACCESS_KEY_ID=None,
                                S3_SECRET_ACCESS_KEY=None, S3_URL_STYLE=None)
        try:
            stores = [artifacts.LocalStore(os.path.join(d, "arts")),
                      artifacts.PostgresStore("postgresql://u@h/db", connect=db.connect),
                      artifacts.S3Store("s3://bkt/p", boto=b)]
            for s in stores:
                a = s.put("m.xml", b"<x/>", "application/xml")
                c = s.put_stream("m.xml", io.BytesIO(b"<x/>"), "application/xml")
                assert a != c, "each write is its own artifact id"
                assert [artifacts._split(r)[1] for r in (a, c)] == ["m.xml", "m.xml"]
                assert len(artifacts._split(c)[0]) == 12
                assert s.get(a) == s.get(c) == b"<x/>"
                ia, ic = s.info(a), s.info(c)
                assert ia["size"] == ic["size"] == 4 and ia["backend"] == ic["backend"]
                assert ia["content_type"] == ic["content_type"] == "application/xml"
        finally:
            _with_s3_config(**saved)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
