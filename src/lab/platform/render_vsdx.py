"""Render a Visio `.vsdx` page to a PNG — the SECOND (image) representation of a diagram, which the BA
reconciles against the deterministic parse. Deterministic step: no LLM, no egress, no store access.

Why an image at all when the file parses: a `.vsdx` says WHAT the shapes are, the picture says how
they are ARRANGED. Containment/zoning (which boxes sit inside which grouping block or swim-lane) and
lines a foreign exporter never wrote as connectors are only legible visually — see the BA prompt's
RECONCILIATION rule for which representation wins on what.

Mechanism, in two hops, each replaceable:
  1. **LibreOffice headless** converts the whole workbook to ONE PDF (`soffice --convert-to pdf`).
  2. A **PDF rasteriser** draws page N (pypdfium2 preferred — small and non-AGPL; PyMuPDF accepted
     when it is what the host has), and the bitmap goes through `docparse.normalise_image`, the ONE
     place the <= 1600 px / PNG-JPEG sizing contract lives.

Both hops are HEAVY, host-level dependencies, so nothing here is imported at module load and
`available()` is the capability gate: a host without LibreOffice or a rasteriser must degrade to the
structured parse alone, never fail the run. `render_page(..., convert=, draw=)` injects either hop,
which is how this is tested with no LibreOffice anywhere near the suite.

Caveat, un-verifiable without LibreOffice on this host: the PDF's page ORDER is assumed to follow the
workbook's page order, and LibreOffice may drop or merge background pages. The caller resolves a page
NAME to an index from the parse (`read_vsdx.page_index`) and this module reports the real PDF page
count in its IndexError, so a mismatch surfaces loudly rather than silently rendering the wrong page.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

from lab.platform import config, docparse

# LibreOffice binary: `config.SOFFICE_BIN` overrides for an install off these standard paths.
CANDIDATES = ("soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice")
DEFAULT_ZOOM = 2.0                 # ~150 dpi: legible small type without an oversized bitmap
CONVERT_TIMEOUT = 120              # seconds; a big workbook takes tens of seconds to convert


def soffice_bin() -> str | None:
    """Path to the LibreOffice binary, or None when this host has none."""
    for c in (config.SOFFICE_BIN or "", *CANDIDATES):
        if c and (shutil.which(c) or os.path.exists(c)):
            return shutil.which(c) or c
    return None


def pdfium_png(pdf_path: str, page_index: int, zoom: float) -> bytes:
    """Rasterise one PDF page with pypdfium2."""
    import pypdfium2
    doc = pypdfium2.PdfDocument(pdf_path)
    if page_index >= len(doc):
        raise IndexError(f"page {page_index} out of range (the PDF has {len(doc)})")
    buf = io.BytesIO()
    doc[page_index].render(scale=zoom).to_pil().save(buf, "PNG")
    return buf.getvalue()


def pymupdf_png(pdf_path: str, page_index: int, zoom: float) -> bytes:
    """Rasterise one PDF page with PyMuPDF (fitz)."""
    import fitz
    with fitz.open(pdf_path) as doc:
        if page_index >= doc.page_count:
            raise IndexError(f"page {page_index} out of range (the PDF has {doc.page_count})")
        return doc.load_page(page_index).get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")


# Ordered backends: the first importable one wins. Extend by adding a row, not by editing callers.
BACKENDS = (("pypdfium2", pdfium_png), ("fitz", pymupdf_png))


def rasteriser():
    """The PDF-page rasteriser this host can use, or None when neither backend is installed."""
    import importlib
    for module, fn in BACKENDS:
        try:
            importlib.import_module(module)
            return fn
        except Exception:
            continue
    return None


def available() -> bool:
    """True iff this host can render a .vsdx page at all (LibreOffice AND a rasteriser). Callers
    use it to attach the image representation when possible and stay structure-only when not."""
    return bool(soffice_bin()) and rasteriser() is not None


def to_pdf(vsdx_bytes: bytes, workdir: str, timeout: int = CONVERT_TIMEOUT) -> str:
    """`soffice --headless --convert-to pdf` -> `<workdir>/in.pdf`. Raises with a clear cause when
    LibreOffice is missing or the conversion produced nothing."""
    exe = soffice_bin()
    if not exe:
        raise RuntimeError("LibreOffice (soffice) not found — install it (brew install --cask libreoffice) "
                           "or set SOFFICE_BIN; without it a .vsdx has no image representation.")
    src = os.path.join(workdir, "in.vsdx")
    with open(src, "wb") as f:
        f.write(vsdx_bytes)
    # A per-conversion user profile: never clash with an interactive LibreOffice on the same host.
    profile = f"-env:UserInstallation=file://{os.path.join(workdir, 'lo-profile')}"
    subprocess.run([exe, "--headless", profile, "--convert-to", "pdf", "--outdir", workdir, src],
                   check=True, capture_output=True, timeout=timeout)
    pdf = os.path.join(workdir, "in.pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("LibreOffice produced no PDF from the .vsdx (conversion failed / unsupported).")
    return pdf


def render_page(vsdx_bytes: bytes, page_index: int = 0, zoom: float = DEFAULT_ZOOM,
                max_edge: int = docparse.MAX_IMAGE_EDGE, *, convert=None, draw=None):
    """One .vsdx page -> `(png_bytes, media_type, (w, h))`, or None when the rendered page falls
    below the sizing floor (a blank/decorative page). `convert` and `draw` inject the two hops;
    they default to LibreOffice and the host's rasteriser. Raises when a hop is unavailable — the
    caller decides whether that degrades to structure-only (see `available()`)."""
    convert = convert or to_pdf
    if draw is None:
        draw = rasteriser()
        if draw is None:
            raise RuntimeError("no PDF rasteriser installed (pip install pypdfium2) — a .vsdx cannot "
                               "be rendered to an image on this host.")
    with tempfile.TemporaryDirectory(prefix="vsdx-render-") as wd:
        raw = draw(convert(vsdx_bytes, wd), page_index, zoom)
    # ONE place enforces the <= 1600 px / PNG-JPEG contract, shared with every other image path.
    return docparse.normalise_image(raw, "image/png", max_edge)
