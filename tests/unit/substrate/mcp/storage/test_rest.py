"""storage-mcp's byte routes — what the front door forwards `/api/artifacts` and `/api/uploads` to.

storage-mcp holds the store credentials; the front door holds Redis only. So a surface reading an
artifact or uploading an input goes surface -> gateway (/api, role checked) -> front door -> HERE,
and no surface holds a store credential. Offline: two in-memory stores, Starlette's test client.
"""
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from lab.substrate.mcp.storage import rest


class MemStore:
    def __init__(self, objects=None):
        self.objects, self.puts = dict(objects or {}), []

    def get(self, ref):
        if ref not in self.objects:
            raise KeyError(ref)
        return self.objects[ref]

    def put(self, name, data, content_type="application/octet-stream"):
        ref = f"art://u{len(self.puts)}/{name}"
        self.puts.append((name, data, content_type))
        self.objects[ref] = data
        return ref

    def put_stream(self, name, fileobj, content_type="application/octet-stream", size_hint=None):
        return self.put(name, fileobj.read(), content_type)


class Srv:
    def __init__(self, artifacts, uploads):
        self.artifacts, self.uploads = (lambda: artifacts), (lambda: uploads)


@pytest.fixture
def stores():
    arts = MemStore({"art://a1/model.archimate.xml": b"<model/>"})
    ups = MemStore({"art://b2/diagram.png": b"\x89PNG"})
    return arts, ups, TestClient(Starlette(routes=rest.routes(Srv(arts, ups))))


def test_an_artifact_comes_back_as_bytes_typed_and_named_from_its_ref(stores):
    _, _, client = stores
    got = client.get("/artifacts", params={"ref": "art://a1/model.archimate.xml"})
    assert got.status_code == 200 and got.content == b"<model/>"
    assert "xml" in got.headers["content-type"]
    assert 'filename="model.archimate.xml"' in got.headers["content-disposition"]


def test_an_upload_ref_is_found_too_because_a_ref_does_not_say_which_store(stores):
    _, _, client = stores
    got = client.get("/artifacts", params={"ref": "art://b2/diagram.png"})
    assert got.status_code == 200 and got.content == b"\x89PNG"


def test_a_missing_ref_is_404_and_a_malformed_one_400(stores):
    _, _, client = stores
    assert client.get("/artifacts", params={"ref": "art://zz/none.txt"}).status_code == 404
    assert client.get("/artifacts", params={"ref": "https://evil/x"}).status_code == 400
    assert client.get("/artifacts").status_code == 400


def test_an_upload_keeps_the_original_filename_and_goes_to_the_upload_store(stores):
    arts, ups, client = stores
    got = client.post("/uploads", files=[("files", ("brief.docx", b"DOCX", "application/octet-stream")),
                                         ("files", ("map.png", b"PNG", "image/png"))])
    assert got.status_code == 201
    refs = got.json()["refs"]
    assert [r.rsplit("/", 1)[-1] for r in refs] == ["brief.docx", "map.png"]
    assert [p[0] for p in ups.puts] == ["brief.docx", "map.png"] and not arts.puts
    # the type is derived from the NAME, not trusted from the caller
    assert ups.puts[0][2] != "application/octet-stream"


def test_an_upload_with_no_files_says_so(stores):
    _, _, client = stores
    assert client.post("/uploads", files=[]).status_code == 400


def test_a_traversal_ref_is_refused_before_any_store_is_asked(stores):
    _, _, client = stores
    for bad in ("art://../x/../../etc/passwd", "art://abc/../secret", "art://abc/x\\..\\y"):
        assert client.get("/artifacts", params={"ref": bad}).status_code == 400, bad


def test_an_upload_name_is_reduced_to_its_base_name_and_a_dot_name_refused(stores):
    _, ups, client = stores
    got = client.post("/uploads", files=[("files", ("../../etc/brief.docx", b"DOCX"))])
    assert got.status_code == 201 and ups.puts[-1][0] == "brief.docx"
    assert client.post("/uploads", files=[("files", ("..", b"x"))]).status_code == 400


def test_an_oversize_upload_is_413_with_the_store_s_own_sentence():
    from lab.substrate.artifacts import ArtifactTooLarge

    class Full(MemStore):
        def put_stream(self, name, fileobj, content_type="", size_hint=None):
            raise ArtifactTooLarge(f"artifact {name!r} exceeds this store's limit")
    client = TestClient(Starlette(routes=rest.routes(Srv(MemStore(), Full()))))
    got = client.post("/uploads", files=[("files", ("big.bin", b"x" * 10))])
    assert got.status_code == 413 and "exceeds" in got.json()["error"]


def test_a_store_failure_that_is_not_a_miss_is_a_502_not_a_bare_500():
    class Broken(MemStore):
        def get(self, ref):
            raise RuntimeError("bucket unreachable")
    client = TestClient(Starlette(routes=rest.routes(Srv(Broken(), Broken()))))
    got = client.get("/artifacts", params={"ref": "art://abc/x.txt"})
    assert got.status_code == 502 and "bucket unreachable" in got.json()["error"]
