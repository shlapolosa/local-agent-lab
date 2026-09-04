"""src/lab/platform/docparse.py + the ONE content-type table in src/lab/substrate/artifacts.py. OFFLINE.
Includes the vsdx_dict concurrency case (review A-F7): four threads parsing the SAME bytes under
the SAME name must all succeed (the old pid+name temp path collided)."""
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lab.substrate import artifacts  # noqa: E402

from lab.platform import docparse

FIXTURE = os.path.join(ROOT, "var", "inputs", "visio_to_archimate", "malaffi-application-solution-arch.vsdx")


def test_split_fragment():
    assert docparse.split_fragment("malaffi.vsdx#Shafafiya") == ("malaffi.vsdx", "Shafafiya")
    assert docparse.split_fragment("art://ab12/malaffi.vsdx#P 1") == ("art://ab12/malaffi.vsdx", "P 1")
    assert docparse.split_fragment("x.vsdx") == ("x.vsdx", None)
    assert docparse.split_fragment("x.vsdx#") == ("x.vsdx", None)
    assert docparse.split_fragment("") == ("", None)


def test_kind_table():
    table = {
        "d.vsdx": "vsdx", "art://1/d.VSDX#Page": "vsdx",
        "a.png": "image", "a.jpg": "image", "a.JPEG": "image", "a.gif": "image", "a.webp": "image",
        "r.docx": "document", "r.pdf": "document", "r.md": "document", "r.markdown": "document",
        "r.txt": "document", "r.rst": "document", "r.csv": "document",
        "x.svg": "unknown", "x.xml": "unknown", "x.json": "unknown", "x.xlsx": "unknown", "noext": "unknown",
        "art://1/r.docx#frag": "document",
    }
    for name, want in table.items():
        assert docparse.kind(name) == want, (name, docparse.kind(name), want)


def test_media_type_and_ext():
    assert docparse.media_type("a.png") == "image/png"
    assert docparse.media_type("a.jpg") == docparse.media_type("a.JPEG") == "image/jpeg"
    assert docparse.media_type("a.webp") == "image/webp"
    assert docparse.media_type("art://1/a.gif#x") == "image/gif"
    assert docparse.media_type("r.docx") == "application/octet-stream"     # unchanged contract: images only
    assert docparse.media_type("noext") == "application/octet-stream"
    assert docparse.ext_of("art://1/R.DOCX#p") == ".docx"
    assert docparse.ext_of("noext") == ""


def test_tables_derive_from_artifacts():
    """docparse.IMAGE_TYPES / DOC_TYPES are VIEWS of artifacts.FILE_TYPES — they can no longer disagree."""
    ft = artifacts.FILE_TYPES
    assert docparse.IMAGE_TYPES == {"." + e: ct for e, (ct, k) in ft.items() if k == "image"}
    assert docparse.DOC_TYPES == {"." + e for e, (ct, k) in ft.items() if k == "document"}
    assert set(docparse.IMAGE_TYPES) == {".png", ".jpg", ".jpeg", ".gif", ".webp"}          # behaviour kept
    assert docparse.DOC_TYPES == {".docx", ".pdf", ".md", ".markdown", ".txt", ".rst", ".csv"}
    for ext, ct in docparse.IMAGE_TYPES.items():
        assert artifacts.content_type_for("f" + ext) == ct
    assert artifacts.CONTENT_TYPES == {e: ct for e, (ct, _) in ft.items()}
    assert artifacts.kind_for("a.png") == "image" and artifacts.kind_for("d.vsdx") == "vsdx"
    assert artifacts.kind_for("m.xml") == "artifact" and artifacts.kind_for("zzz.bin") == "unknown"


def test_content_type_for():
    assert artifacts.content_type_for("m.archimate.xml") == "application/xml"
    assert artifacts.content_type_for("v.svg") == "image/svg+xml"
    assert artifacts.content_type_for("s.spec.json") == "application/json"
    assert artifacts.content_type_for("d.vsdx") == "application/vnd.ms-visio.drawing.main+xml"
    assert artifacts.content_type_for("o.objects.xlsx") == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")   # was missing (octet-stream)
    assert artifacts.content_type_for("noext") == "application/octet-stream"
    assert artifacts.content_type_for("x.unknownext", "text/plain") == "text/plain"


def test_vsdx_dict_concurrent_same_name():
    if not os.path.exists(FIXTURE):
        print("  (skip: fixture .vsdx not present)"); return
    data = open(FIXTURE, "rb").read()
    single = docparse.vsdx_dict(data, "same-name.vsdx")
    assert single["shapes"], "fixture parsed to no shapes"
    results, errors = [None] * 4, []
    barrier = threading.Barrier(4)

    def work(i):
        try:
            barrier.wait(timeout=10)
            results[i] = docparse.vsdx_dict(data, "same-name.vsdx")
        except BaseException as e:           # noqa: BLE001 — collect, assert below
            errors.append((i, repr(e)))
    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in ts: t.start()
    for t in ts: t.join(60)
    assert not errors, errors
    for i, r in enumerate(results):
        assert r is not None, f"thread {i} produced nothing"
        assert len(r["shapes"]) == len(single["shapes"]) and len(r["connectors"]) == len(single["connectors"]), i
        assert r["file"] == "same-name.vsdx"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [PASS] {name}")
    print("test_docparse: ALL PASSED")
