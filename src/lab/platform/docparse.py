"""Deterministic parsing of a workload's INPUTS — bytes in, plain data out. No I/O, no egress.

Shared by two callers with different trust: `src/lab/substrate/mcp/storage/server.py` (the governed path — an
agent asks the gateway, the gateway asks storage-mcp, storage-mcp reads the bucket and parses here)
and `src/lab/workloads/visio_to_archimate/inputs.py` (local-dev paths only). Keeping the parsing here means
both produce byte-identical results and the sizing contract the visio-reader skill documents is
enforced in exactly one place.
"""
from __future__ import annotations

import io
import os
import re
import tempfile
from pathlib import Path

from lab.core.modelling.paragraphs import PDF_PAGE_SEPARATOR
from lab.platform import filetypes
from lab.platform.contracts import split_fragment  # noqa: F401  (re-exported: the ONE `#page` parser)

# Views of the ONE file-type table (lab.platform.filetypes.FILE_TYPES): which extensions are read with
# vision and which as requirements text. Extend the table there, not these.
IMAGE_TYPES = {"." + ext: ct for ext, (ct, k) in filetypes.FILE_TYPES.items() if k == "image"}
DOC_TYPES = {"." + ext for ext, (_ct, k) in filetypes.FILE_TYPES.items() if k == "document"}
MAX_DOC_CHARS = int(os.environ.get("BA_MAX_DOC_CHARS", "60000"))      # keeps one doc inside a turn
MAX_EMBEDDED_IMAGES = int(os.environ.get("BA_MAX_EMBEDDED_IMAGES", "8"))
MIN_IMAGE_BYTES = 2048            # below this it is a bullet/icon, not a figure
MIN_IMAGE_EDGE = 64
MAX_IMAGE_EDGE = 1600             # the sizing contract: no image reaches a model larger than this
# A WHOLE RENDERED PAGE is a deliberate exception to that default. A Visio page is ~16 in across with
# ~0.3 in icons, so 1600 px is ~100 dpi and a caption is a few pixels tall — unreadable, which would
# defeat the point of the second representation (containment and captions the parse cannot give).
# 2400 px keeps the same contract (PNG/JPEG, one bounded number) at a size a vision model can read.
RENDER_MAX_EDGE = 2400


def _base(name: str) -> str:
    """File name with any `#page` fragment removed, for extension detection."""
    return split_fragment(name)[0].rstrip("/").split("/")[-1]


def kind(name: str) -> str:
    """'vsdx' | 'image' | 'document' | 'unknown' — decided by the file name (ref or path alike;
    a `#page` fragment is ignored)."""
    ext = Path(_base(name)).suffix.lower()
    if ext == ".vsdx":
        return "vsdx"
    if ext in IMAGE_TYPES:
        return "image"
    if ext in DOC_TYPES:
        return "document"
    return "unknown"


def media_type(name: str) -> str:
    """The media type an IMAGE input is attached with (octet-stream for anything that is not one
    of IMAGE_TYPES — documents and .vsdx are never sent as inline media)."""
    return IMAGE_TYPES.get(Path(_base(name)).suffix.lower(), "application/octet-stream")


def ext_of(name: str) -> str:
    return Path(_base(name)).suffix.lower()


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_ALTERNATE = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
#: Containers whose text is not part of the body flow, or not part of the document as accepted.
_SKIP = {_W + "del", _W + "moveFrom", _W + "txbxContent", _MC_ALTERNATE}
_WS = re.compile(r"\s+")


def _skipped(node, stop) -> bool:
    """Is `node` inside a deletion, a move-away, a text box or an alternate-content shape (up to `stop`)?"""
    node = node.getparent()
    while node is not None and node is not stop:
        if node.tag in _SKIP:
            return True
        node = node.getparent()
    return False


def _para_text(p) -> str:
    """A w:p's text per DOCX_EXTRACTION: w:t in order (inline controls, hyperlinks and field results
    included; w:instrText is a different element, so a field code never is); a run's tab/br/cr is one
    space; whitespace collapsed, trimmed."""
    out = []
    for node in p.iter(_W + "t", _W + "tab", _W + "br", _W + "cr"):
        if node.tag != _W + "t" and node.getparent().tag != _W + "r":
            continue                                  # a tab STOP definition in pPr is not text
        if _skipped(node, p):
            continue
        out.append(node.text or "" if node.tag == _W + "t" else " ")
    return _WS.sub(" ", "".join(out)).strip()


def _unwrap(children):
    """Children with every w:sdt replaced by its w:sdtContent's children, in place."""
    for ch in children:
        if ch.tag == _W + "sdt":
            content = ch.find(_W + "sdtContent")
            if content is not None:
                yield from _unwrap(content)
        else:
            yield ch


def _cell_text(tc) -> str | None:
    """A cell's text, "" for a vertical-merge continuation, None for a legacy hMerge continuation
    (which is dropped: the merged cell appears once)."""
    props = tc.find(_W + "tcPr")
    if props is not None:
        hmerge, vmerge = props.find(_W + "hMerge"), props.find(_W + "vMerge")
        if hmerge is not None and hmerge.get(_W + "val") != "restart":
            return None
        if vmerge is not None and vmerge.get(_W + "val") != "restart":
            return ""
    texts = [_para_text(p) for p in _unwrap(tc) if p.tag == _W + "p"]      # a nested w:tbl is skipped
    return _WS.sub(" ", " ".join(t for t in texts if t)).strip()


def _row_line(tr) -> str | None:
    cells = [_cell_text(tc) for tc in _unwrap(tr) if tc.tag == _W + "tc"]
    cells = [c for c in cells if c is not None]
    return " | ".join(cells) if any(cells) else None


def docx_lines(data: bytes) -> list[str]:
    """A Word document's body as LINES, exactly as contract 1.4.0's DOCX_EXTRACTION states
    (`lab.core.modelling.paragraphs`): one per non-empty w:p, one per non-empty table row, in document
    order. Held byte for byte to contracts/goldens/paragraphs/."""
    import docx
    body = docx.Document(io.BytesIO(data)).element.body
    lines = []
    for el in _unwrap(body):
        if el.tag == _W + "p":
            line = _para_text(el)
            if line:
                lines.append(line)
        elif el.tag == _W + "tbl":
            for tr in el.findall(_W + "tr"):
                line = _row_line(tr)
                if line is not None:
                    lines.append(line)
    return lines


def document_text(data: bytes, ext: str, max_chars: int = MAX_DOC_CHARS) -> str:
    """Requirements document -> plain text. A .docx is its lines (`docx_lines`); a .pdf is its pages'
    text separated by a FORM FEED, because a page's own text can hold blank lines; anything else is
    UTF-8. The split into paragraphs is `lab.core.modelling.paragraphs`."""
    if ext == ".docx":
        text = "\n".join(docx_lines(data))
    elif ext == ".pdf":
        from pypdf import PdfReader
        text = PDF_PAGE_SEPARATOR.join((pg.extract_text() or "")
                                       for pg in PdfReader(io.BytesIO(data)).pages)
    else:
        # `utf-8-sig`, not `utf-8`: a UTF-8 BOM is an ENCODING mark, not content, and the meeting pipeline
        # writes one at the start of every delivered `.txt` so Arabic renders in SharePoint rather than as
        # mojibake. Carried through, U+FEFF sits at position 0 of the extracted text — zero-width, so
        # invisible in a log, a diff, a card and a review form, and able to stop a term matching with no
        # symptom but "the classifier found nothing". A BOM-less file decodes identically, which is what
        # makes this strictly safer than the alternative of asking the writer not to emit one.
        text = data.decode("utf-8-sig", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated: {len(text)} chars in total, first {max_chars} shown]"
    return text


def normalise_image(data: bytes, ctype: str, max_edge: int = MAX_IMAGE_EDGE):
    """Apply the sizing contract: reject decorations (< MIN_IMAGE_BYTES or < MIN_IMAGE_EDGE px),
    downscale to max_edge, emit PNG unless already PNG/JPEG within bounds.
    Returns (bytes, media_type, (w, h)) or None when the input is not a usable figure."""
    if len(data) < MIN_IMAGE_BYTES:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if min(im.size) < MIN_IMAGE_EDGE:
            return None
        if max(im.size) > max_edge or ctype not in ("image/png", "image/jpeg"):
            im.thumbnail((max_edge, max_edge))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
            return buf.getvalue(), "image/png", im.size
        return data, ctype, im.size
    except Exception:
        return None                  # emf/wmf and friends — PIL cannot read them; skip


def embedded_figures(data: bytes, ext: str, doc_name: str, max_images: int = MAX_EMBEDDED_IMAGES,
                     max_edge: int = MAX_IMAGE_EDGE) -> list[tuple[str, bytes, str]]:
    """Figures EMBEDDED in a document -> [(label, bytes, media_type)]: a .docx's image parts, a
    .pdf's page images — normalised so a vision model can read them as diagrams/screenshots."""
    out: list[tuple[str, bytes, str]] = []
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        for rel in d.part.rels.values():
            if "image" in rel.reltype and getattr(rel, "target_part", None) is not None:
                norm = normalise_image(rel.target_part.blob, rel.target_part.content_type, max_edge)
                if norm:
                    out.append((f"figure {len(out) + 1} embedded in {doc_name}", norm[0], norm[1]))
            if len(out) >= max_images:
                break
    elif ext == ".pdf":
        from pypdf import PdfReader
        for pno, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1):
            for img in page.images:
                norm = normalise_image(img.data, "image/" + (img.name.rsplit(".", 1)[-1].lower() or "png"), max_edge)
                if norm:
                    out.append((f"figure {len(out) + 1} embedded in {doc_name} (page {pno})", norm[0], norm[1]))
                if len(out) >= max_images:
                    return out
    return out


def vsdx_dict(data: bytes, name: str, page: str | None = None) -> dict:
    """Parse a .vsdx with the visio-reader skill script (it needs a real path -> temp file).
    `page` restricts the parse to one named page (a `#page` fragment on `name` is honoured too)."""
    from lab.core.visio.read_vsdx import read_vsdx as _rv   # local: the vsdx library loads only when a .vsdx is parsed
    base, frag = split_fragment(name)
    page = page or frag
    # A private directory per call: storage-mcp serves concurrent reads of the SAME workbook (one per
    # page), so a path keyed by pid + file name collided (truncated parses / FileNotFoundError).
    # The file keeps its own name inside the directory (the parser reports `file` from the path).
    with tempfile.TemporaryDirectory(prefix="vsdx-") as d:
        p = Path(d) / (base.rstrip("/").split("/")[-1] or "diagram.vsdx")
        p.write_bytes(data)
        return _rv(str(p), page=page)


def vsdx_page_image(data: bytes, name: str, page: str | None = None,
                    max_edge: int = RENDER_MAX_EDGE, render=None):
    """A .vsdx PAGE as a picture — the second representation of the same diagram, for a vision model.

    The page NAME (or a `#page` fragment on `name`, the same selector `vsdx_dict` honours) is resolved
    against the workbook's own page order and handed to the renderer as an index; the bitmap comes
    back already through `normalise_image`. Returns None when the page normalises below the sizing
    floor. Raises `ValueError` for an unknown page name and `RuntimeError` when this host has no
    LibreOffice / PDF rasteriser — the caller degrades to the structured parse alone.
    `render` injects the renderer (default `lab.platform.render_vsdx.render_page`)."""
    from lab.core.visio.read_vsdx import page_index, page_names   # local: vsdx loads only for a .vsdx
    base, frag = split_fragment(name)
    page = page or frag
    if render is None:
        from lab.platform import render_vsdx
        render = render_vsdx.render_page
    with tempfile.TemporaryDirectory(prefix="vsdx-") as d:
        p = Path(d) / (base.rstrip("/").split("/")[-1] or "diagram.vsdx")
        p.write_bytes(data)
        index = page_index(page_names(str(p)), page)
    return render(data, index, max_edge=max_edge)
