"""Render a Visio `.vsdx` page to a PNG — the SECOND (image) representation the BA reconciles against the
deterministic parse (and the only reliable way to recover Lucidchart connectors, whose geometry the parser
can't resolve). Deterministic step: no LLM, no egress.

Mechanism: LibreOffice headless converts the vsdx to a single PDF (`soffice --convert-to pdf`), then a page
is rasterised with PyMuPDF (fitz) and normalised through the shared image-sizing contract. LibreOffice is a
heavy dependency (installed on the host / in the container); if `soffice` is absent this raises a clear
error rather than guessing — callers fall back to the structured parse alone.

    render_page(vsdx_bytes, page_index=0) -> (png_bytes, media_type, (w, h)) | None
    render_all(vsdx_bytes)               -> [ (png_bytes, media_type, (w, h)), ... ]  (one per PDF page)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from lab.platform import docparse

# LibreOffice binary — overridable for odd install paths (e.g. macOS app bundle).
_SOFFICE_CANDIDATES = [
    os.environ.get("SOFFICE_BIN", ""),
    "soffice", "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def soffice_bin() -> str | None:
    for c in _SOFFICE_CANDIDATES:
        if c and (shutil.which(c) or os.path.exists(c)):
            return shutil.which(c) or c
    return None


def available() -> bool:
    """True iff both LibreOffice and PyMuPDF are present — lets a caller degrade gracefully."""
    if not soffice_bin():
        return False
    try:
        import fitz  # noqa: F401  (PyMuPDF)
        return True
    except Exception:
        return False


def _vsdx_to_pdf(vsdx_bytes: bytes, workdir: str, timeout: int = 120) -> str:
    """soffice --headless --convert-to pdf <in.vsdx> -> <workdir>/in.pdf. Returns the PDF path."""
    exe = soffice_bin()
    if not exe:
        raise RuntimeError("LibreOffice (soffice) not found — install it (brew install --cask libreoffice) "
                           "or set SOFFICE_BIN; without it a vsdx has no image representation.")
    src = os.path.join(workdir, "in.vsdx")
    with open(src, "wb") as f:
        f.write(vsdx_bytes)
    # A per-conversion user profile avoids clashing with any interactive LibreOffice instance.
    profile = f"-env:UserInstallation=file://{os.path.join(workdir, 'lo-profile')}"
    subprocess.run([exe, "--headless", profile, "--convert-to", "pdf", "--outdir", workdir, src],
                   check=True, capture_output=True, timeout=timeout)
    pdf = os.path.join(workdir, "in.pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("LibreOffice produced no PDF from the vsdx (conversion failed / unsupported).")
    return pdf


def _pdf_page_png(pdf_path: str, page_index: int, zoom: float = 2.0) -> bytes:
    """Rasterise one PDF page to PNG bytes at `zoom`× (150 dpi ≈ zoom 2.0)."""
    import fitz  # PyMuPDF
    with fitz.open(pdf_path) as doc:
        if page_index >= doc.page_count:
            raise IndexError(f"page {page_index} out of range (pdf has {doc.page_count})")
        pix = doc.load_page(page_index).get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")


def render_page(vsdx_bytes: bytes, page_index: int = 0, zoom: float = 2.0):
    """Render one vsdx page → normalised PNG. Returns (png_bytes, media_type, (w,h)) or None if the
    normalised image is below the sizing floor. Raises if LibreOffice/PyMuPDF are missing or conversion fails."""
    with tempfile.TemporaryDirectory(prefix="vsdx-render-") as wd:
        pdf = _vsdx_to_pdf(vsdx_bytes, wd)
        raw = _pdf_page_png(pdf, page_index, zoom)
    # one place enforces the ≤1600px / PNG-JPEG sizing contract (shared with every other image path)
    return docparse.normalise_image(raw, "image/png")


def render_all(vsdx_bytes: bytes, zoom: float = 2.0) -> list:
    """Render every page of the vsdx (one PNG per PDF page). Skips any page that normalises below the floor."""
    out = []
    with tempfile.TemporaryDirectory(prefix="vsdx-render-") as wd:
        pdf = _vsdx_to_pdf(vsdx_bytes, wd)
        import fitz
        with fitz.open(pdf) as doc:
            n = doc.page_count
        for i in range(n):
            png = _pdf_page_png(pdf, i, zoom)
            norm = docparse.normalise_image(png, "image/png")
            if norm:
                out.append(norm)
    return out
