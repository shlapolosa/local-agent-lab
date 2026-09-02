"""Workload INPUTS — a system diagram plus optional requirements documents — by reference or path.

Where the BA reads from: a workload never touches the object store itself. Every input is an
`art://<id>/<name>` reference in the shared upload store, and a reference is read ONLY through
the gateway's `storage_mcp` tools (governed, metered, PII-scanned, traced; the bucket credentials
live in storage-mcp, not here). Plain filesystem paths are still accepted for local development
runs, parsed with the same shared helpers (`shared/docparse.py`) storage-mcp uses. Upload with
`python -m processes.visio_to_archimate.inputs upload <files...>` -> refs.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared import artifacts, docparse  # noqa: E402

kind, media_type = docparse.kind, docparse.media_type


def is_ref(src: str) -> bool:
    return isinstance(src, str) and src.startswith("art://")


def name_of(src: str) -> str:
    return src.rstrip("/").split("/")[-1]


def load(src: str) -> bytes:
    """Bytes of a local PATH. A ref is deliberately refused: refs are read through storage-mcp."""
    if is_ref(src):
        raise ValueError(f"{src} is a reference — read it through the gateway's storage_mcp tools")
    return Path(src).read_bytes()


def read_document(src: str) -> str:
    return docparse.document_text(load(src), docparse.ext_of(src))


def extract_images(src: str) -> list[tuple[str, bytes, str]]:
    return docparse.embedded_figures(load(src), docparse.ext_of(src), name_of(src))


def read_vsdx(src: str) -> dict:
    return docparse.vsdx_dict(load(src), name_of(src))


def upload(paths) -> list[str]:
    """Store local files in the UPLOAD store; returns their art:// refs (what a run is given)."""
    return [artifacts.put_file(p, content_type=artifacts.content_type_for(p), target=artifacts.uploads())
            for p in paths]


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "upload":
        for p, ref in zip(sys.argv[2:], upload(sys.argv[2:])):
            print(f"{ref}\t{p}")
    else:
        sys.exit("usage: python -m processes.visio_to_archimate.inputs upload <diagram|doc> ...")
