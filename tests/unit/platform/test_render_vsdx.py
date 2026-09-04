"""src/lab/platform/render_vsdx.py — the SECOND (image) representation of a .vsdx page: LibreOffice
headless converts the workbook to PDF, a PDF rasteriser draws one page, and the result goes through
the ONE image-sizing contract (docparse.normalise_image).

OFFLINE by construction: LibreOffice is faked with a shell script that writes a real PDF (authored
with Pillow), and the rasteriser backends are faked as importable modules — no LibreOffice, no
pypdfium2/pymupdf, no gateway. That is also the point of the module's `available()` gate: on a host
without them the caller degrades to structure-only rather than failing a run.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_render_vsdx.py"""
import io
import os
import sys
import tempfile
import types

import pytest
from PIL import Image

from lab.platform import render_vsdx as RV


# ---------------------------------------------------------------- helpers
def a_pdf(w=2000, h=1200, pages=2) -> bytes:
    """A real multi-page PDF (Pillow writes PDFs natively) — no external tool involved."""
    imgs = [Image.new("RGB", (w, h), (30 + 40 * i, 60, 90)) for i in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def a_png(w=2000, h=1200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def fake_soffice(tmp: str, pdf: bytes | None) -> str:
    """An executable standing in for `soffice --headless --convert-to pdf`: it writes `in.pdf` into
    the --outdir it is given (or, with pdf=None, writes nothing, i.e. a failed conversion)."""
    path = os.path.join(tmp, "soffice-stub")
    data = os.path.join(tmp, "stub.pdf")
    if pdf is not None:
        with open(data, "wb") as f:
            f.write(pdf)
    body = ('#!/bin/sh\nfor a in "$@"; do case "$prev" in --outdir) out="$a";; esac; prev="$a"; done\n'
            + (f'cp "{data}" "$out/in.pdf"\n' if pdf is not None else "true\n"))
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


@pytest.fixture
def no_backends(monkeypatch):
    """Neither rasteriser importable, whatever the host happens to have installed."""
    for name in ("pypdfium2", "fitz"):
        monkeypatch.setitem(sys.modules, name, None)      # None in sys.modules -> ImportError
    yield


def fake_pdfium(monkeypatch, png: bytes, npages: int = 2):
    """A `pypdfium2` stand-in: PdfDocument(path)[i].render(scale=).to_pil() -> a PIL image."""
    mod = types.ModuleType("pypdfium2")

    class Bitmap:
        def to_pil(self):
            return Image.open(io.BytesIO(png))

    class Page:
        def render(self, scale=1.0):
            mod.seen_scale = scale
            return Bitmap()

    class Doc(list):
        def __init__(self, path):
            super().__init__(Page() for _ in range(npages))
            mod.seen_path = path

    mod.PdfDocument = Doc
    monkeypatch.setitem(sys.modules, "pypdfium2", mod)
    return mod


def fake_fitz(monkeypatch, png: bytes, npages: int = 2):
    """A PyMuPDF stand-in: fitz.open(path) -> doc.load_page(i).get_pixmap(matrix=).tobytes('png')."""
    mod = types.ModuleType("fitz")

    class Pixmap:
        def tobytes(self, fmt):
            return png

    class Page:
        def get_pixmap(self, matrix=None, alpha=False):
            return Pixmap()

    class Doc:
        def __init__(self, path):
            self.page_count, mod.seen_path = npages, path

        def load_page(self, i):
            if i >= self.page_count:
                raise IndexError(i)
            return Page()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    mod.open, mod.Matrix = Doc, lambda a, b: (a, b)
    monkeypatch.setitem(sys.modules, "fitz", mod)
    return mod


# ---------------------------------------------------------------- LibreOffice discovery
def test_soffice_bin_finds_the_override_and_returns_none_when_absent(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        exe = fake_soffice(tmp, a_pdf())
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", exe)
        assert RV.soffice_bin() == exe
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", os.path.join(tmp, "nope"))
        monkeypatch.setattr(RV, "CANDIDATES", ())          # nothing else on this host
        assert RV.soffice_bin() is None


# ---------------------------------------------------------------- rasteriser backends
def test_rasteriser_prefers_pdfium_then_pymupdf_then_none(monkeypatch, no_backends):
    assert RV.rasteriser() is None
    fake_fitz(monkeypatch, a_png())
    assert RV.rasteriser() is RV.pymupdf_png
    fake_pdfium(monkeypatch, a_png())
    assert RV.rasteriser() is RV.pdfium_png        # the lighter, non-AGPL backend wins


def test_pdfium_backend_renders_the_requested_page_at_the_zoom(monkeypatch):
    mod = fake_pdfium(monkeypatch, a_png())
    png = RV.pdfium_png("/x/in.pdf", 1, 2.0)
    assert Image.open(io.BytesIO(png)).size == (2000, 1200)
    assert mod.seen_path == "/x/in.pdf" and mod.seen_scale == 2.0
    with pytest.raises(IndexError, match="page 5 out of range"):
        RV.pdfium_png("/x/in.pdf", 5, 2.0)


def test_pymupdf_backend_renders_the_requested_page(monkeypatch):
    mod = fake_fitz(monkeypatch, a_png())
    assert RV.pymupdf_png("/x/in.pdf", 1, 2.0) == a_png() and mod.seen_path == "/x/in.pdf"
    with pytest.raises(IndexError, match="page 5 out of range"):
        RV.pymupdf_png("/x/in.pdf", 5, 2.0)


def test_available_needs_both_libreoffice_and_a_rasteriser(monkeypatch, no_backends):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", fake_soffice(tmp, a_pdf()))
        assert RV.available() is False                     # LibreOffice yes, rasteriser no
        fake_pdfium(monkeypatch, a_png())
        assert RV.available() is True
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", os.path.join(tmp, "nope"))
        monkeypatch.setattr(RV, "CANDIDATES", ())
        assert RV.available() is False                     # rasteriser yes, LibreOffice no


# ---------------------------------------------------------------- conversion
def test_to_pdf_runs_libreoffice_and_returns_the_pdf(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", fake_soffice(tmp, a_pdf()))
        with tempfile.TemporaryDirectory() as wd:
            pdf = RV.to_pdf(b"vsdx-bytes", wd)
            assert pdf == os.path.join(wd, "in.pdf") and os.path.getsize(pdf) > 0


def test_to_pdf_without_libreoffice_says_so(monkeypatch):
    monkeypatch.setattr(RV.config, "SOFFICE_BIN", None)
    monkeypatch.setattr(RV, "CANDIDATES", ())
    with tempfile.TemporaryDirectory() as wd, pytest.raises(RuntimeError, match="LibreOffice"):
        RV.to_pdf(b"x", wd)


def test_to_pdf_reports_a_conversion_that_produced_nothing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", fake_soffice(tmp, None))
        with tempfile.TemporaryDirectory() as wd, pytest.raises(RuntimeError, match="no PDF"):
            RV.to_pdf(b"x", wd)


# ---------------------------------------------------------------- the public entry point
def test_render_page_normalises_through_the_one_image_contract():
    seen = {}

    def convert(data, workdir, timeout=120):
        seen["data"] = data
        return os.path.join(workdir, "in.pdf")

    def draw(pdf, index, zoom):
        seen["pdf"], seen["index"], seen["zoom"] = pdf, index, zoom
        return a_png(4000, 2400)                          # deliberately over the sizing cap

    out = RV.render_page(b"vsdx", page_index=3, convert=convert, draw=draw)
    data, mime, (w, h) = out
    assert mime == "image/png" and max(w, h) == 1600       # the docparse contract, one place
    assert Image.open(io.BytesIO(data)).size == (w, h)
    assert seen["data"] == b"vsdx" and seen["index"] == 3 and seen["zoom"] == RV.DEFAULT_ZOOM


def test_render_page_returns_none_when_the_page_is_a_decoration():
    out = RV.render_page(b"vsdx", convert=lambda d, wd, timeout=120: "x.pdf",
                         draw=lambda *a: a_png(20, 20))    # below the sizing floor
    assert out is None


def test_render_page_defaults_to_libreoffice_and_the_host_rasteriser(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", fake_soffice(tmp, a_pdf(1800, 900)))
        fake_pdfium(monkeypatch, a_png(1800, 900))
        data, mime, (w, h) = RV.render_page(b"vsdx", page_index=1)
        assert mime == "image/png" and (w, h) == (1600, 800)


def test_render_page_without_a_rasteriser_says_so(monkeypatch, no_backends):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(RV.config, "SOFFICE_BIN", fake_soffice(tmp, a_pdf()))
        with pytest.raises(RuntimeError, match="rasteriser"):
            RV.render_page(b"vsdx")
