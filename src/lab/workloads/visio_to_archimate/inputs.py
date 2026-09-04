"""Workload INPUTS — a system diagram plus optional requirements documents — by reference or path.

Where the BA reads from: a workload never touches the object store itself. Every input is an
`art://<id>/<name>` reference in the shared upload store, and a reference is read ONLY through
the gateway's `storage_mcp` tools (governed, metered, PII-scanned, traced; the bucket credentials
live in storage-mcp, not here). Plain filesystem paths are still accepted for local development
runs, parsed with the same shared helpers (`src/lab/platform/docparse.py`) storage-mcp uses. Upload with
`python -m lab.substrate.review.uploads upload <files...>` -> refs (substrate side: this package never opens the store).
"""
from pathlib import Path

from lab.platform import docparse
from lab.platform.contracts import ArtifactRef, StorageTools

kind, media_type = docparse.kind, docparse.media_type


is_ref = ArtifactRef.is_ref     # the contract's definition of "a reference, not a path"


def split_page(src: str) -> tuple[str, str | None]:
    """(base, page) — a `#<page>` fragment selects one page of a multi-page .vsdx."""
    return docparse.split_fragment(src)


def name_of(src: str) -> str:
    return split_page(src)[0].rstrip("/").split("/")[-1]


def load(src: str) -> bytes:
    """Bytes of a local PATH (a `#page` fragment is stripped). A ref is deliberately refused: refs
    are read through storage-mcp."""
    if is_ref(src):
        raise ValueError(f"{src} is a reference — read it through the gateway's {StorageTools.SERVER} tools")
    return Path(split_page(src)[0]).read_bytes()


def read_document(src: str) -> str:
    return docparse.document_text(load(src), docparse.ext_of(src))


def extract_images(src: str) -> list[tuple[str, bytes, str]]:
    return docparse.embedded_figures(load(src), docparse.ext_of(src), name_of(src))


def read_vsdx(src: str) -> dict:
    """Parse a .vsdx path; `path#Page` restricts to that one page (one view per run)."""
    base, page = split_page(src)
    return docparse.vsdx_dict(load(base), name_of(base), page=page)


def render_page(src: str):
    """Render a .vsdx PATH's page to an image — the local-dev twin of the governed
    `storage_render_vsdx`, returning the SAME triple it does: `(bytes, media_type, label)`, where
    the label names the page the picture actually shows. `path#Page` selects the page. None for a
    blank page; raises when this host has no LibreOffice / PDF rasteriser, which the caller treats
    as "no image representation", never as a failed run."""
    base, page = split_page(src)
    norm = docparse.vsdx_page_image(load(base), name_of(base), page=page)
    if not norm:
        return None
    data, mime, (w, h) = norm
    return data, mime, f"{name_of(base)} page {page or 1} {w}x{h} {mime}"
