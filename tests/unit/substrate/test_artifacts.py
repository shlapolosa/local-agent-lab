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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
