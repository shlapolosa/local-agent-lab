"""src/lab/workloads/visio_to_archimate/inputs.py — workload inputs by path or art:// ref: page
fragments, names, local loading (refs refused: they are read through storage-mcp), document /
figure / vsdx parsing through lab.platform.docparse (the uploader is lab.substrate.review.uploads).
Offline: the .vsdx fixture is parsed locally.
Run: .venv/bin/python tests/unit/workloads/visio_to_archimate/test_inputs.py   (also pytest-compatible)"""
import contextlib
import io
import os
import runpy
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from lab.workloads.visio_to_archimate import inputs as I  # noqa: E402
from lab.platform import docparse  # noqa: E402

FIXTURE = os.path.join(ROOT, "var", "inputs", "visio_to_archimate", "malaffi-application-solution-arch.vsdx")


def test_is_ref_split_page_and_name_of():
    assert I.is_ref("art://ab/x.vsdx") and not I.is_ref("/tmp/x.vsdx") and not I.is_ref(None)
    assert I.split_page("art://ab/malaffi.vsdx#Shafafiya") == ("art://ab/malaffi.vsdx", "Shafafiya")
    assert I.split_page("/in/x.vsdx") == ("/in/x.vsdx", None)
    assert I.name_of("art://ab/malaffi.vsdx#Shafafiya") == "malaffi.vsdx"
    assert I.name_of("/in/sub/req.docx") == "req.docx" and I.name_of("art://ab/x.png/") == "x.png"
    assert I.kind is docparse.kind and I.media_type is docparse.media_type


def test_load_reads_a_path_and_refuses_a_ref():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "req.md"); open(p, "wb").write(b"# hello")
        assert I.load(p) == b"# hello" and I.load(p + "#Page 2") == b"# hello"
    try:
        I.load("art://ab/x.vsdx")
        raise AssertionError("a ref must be refused")
    except ValueError as e:
        assert "storage_mcp" in str(e)


def test_read_document_and_extract_images_for_a_text_document():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "req.md"); open(p, "w").write("# Requirements\n\nThe portal MUST log in users.")
        text = I.read_document(p)
        assert "The portal MUST log in users." in text
        assert I.extract_images(p) == []             # a markdown file embeds no figures


def test_read_vsdx_whole_file_and_one_page():
    d = I.read_vsdx(FIXTURE)
    assert d["file"] == "malaffi-application-solution-arch.vsdx" and d["page"] is None
    assert "Shafafiya" in d["pages"] and len(d["shapes"]) > 100
    one = I.read_vsdx(FIXTURE + "#Shafafiya")
    assert one["page"] == "Shafafiya" and 0 < len(one["shapes"]) < len(d["shapes"])
    assert all(s.get("page") in (None, "Shafafiya") for s in one["shapes"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
