"""THE table of file types that cross a service boundary — extension -> (content type, kind) — and
the two lookups every uploader/parser uses. Lives in the platform kernel because BOTH the artifact
store (substrate) and the input parser (platform, used by workloads) derive from it.
"""
import mimetypes
import re
import unicodedata

# THE table of file types that cross a service boundary: extension -> (content type, kind).
# `kind` is how the lab reads the file — vsdx (structured OOXML, parsed deterministically), image
# (vision input), document (requirements text + embedded figures), artifact (renders/specs/exports
# the servers produce). src/lab/platform/docparse.py DERIVES its IMAGE_TYPES / DOC_TYPES views from this
# table, so the two can never disagree again; extend here, nowhere else.
FILE_TYPES: dict[str, tuple[str, str]] = {
    "vsdx": ("application/vnd.ms-visio.drawing.main+xml", "vsdx"),
    "png": ("image/png", "image"), "jpg": ("image/jpeg", "image"), "jpeg": ("image/jpeg", "image"),
    "gif": ("image/gif", "image"), "webp": ("image/webp", "image"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
    "pdf": ("application/pdf", "document"), "md": ("text/markdown", "document"),
    "markdown": ("text/markdown", "document"), "txt": ("text/plain", "document"),
    "rst": ("text/x-rst", "document"), "csv": ("text/csv", "document"),
    # Subtitle text, and the shape a meeting transcript arrives in: `collab_transcripts`
    # mints a `.vtt` ref, so without an entry here the lab hands out a reference that its
    # own readers refuse. Both decode as UTF-8 through the text branch of `docparse`.
    "vtt": ("text/vtt", "document"), "srt": ("text/plain", "document"),
    "xml": ("application/xml", "artifact"), "svg": ("image/svg+xml", "artifact"),
    # A draw.io solution view (`semantic_render_cafe`): mxGraph XML a person opens in diagrams.net.
    "drawio": ("application/vnd.jgraph.mxfile+xml", "artifact"),
    "json": ("application/json", "artifact"),
    # a rendered topology view: one self-contained page, typed so the provider serves it as a page
    # rather than offering an unknown blob, and kinded `artifact` so no reader tries to parse it
    "html": ("text/html", "artifact"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "artifact"),
}
CONTENT_TYPES = {ext: ct for ext, (ct, _kind) in FILE_TYPES.items()}     # extension -> content type

# The approval download's mime comes from `mimetypes` (contracts.ImportArtifact), which knows nothing
# of draw.io; teach it once, here, beside the table it would otherwise disagree with.
mimetypes.add_type(CONTENT_TYPES["drawio"], ".drawio")


def file_slug(text: str, default: str = "record", limit: int = 80) -> str:
    """A name as a SLUG: lowercase, ASCII (accents folded, the rest dropped), runs of anything else folded to
    one dash, no leading or trailing dash, capped at `limit`.

    Beside the type table because it is the same concern — what a thing is called when it leaves the lab — and
    THE one home for the rule: the projector's page, the topology beside it and a model's element id are the
    same transformation, and two copies of it disagree the first day one is fixed."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:limit] or default


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def content_type_for(name: str, default: str = "application/octet-stream") -> str:
    """Content type from a file name's extension — the one map every uploader uses."""
    return CONTENT_TYPES.get(_ext(name), default)


def kind_for(name: str, default: str = "unknown") -> str:
    """vsdx | image | document | artifact from a file name's extension (`default` when unknown)."""
    return FILE_TYPES[_ext(name)][1] if _ext(name) in FILE_TYPES else default


__all__ = ["FILE_TYPES", "CONTENT_TYPES", "content_type_for", "kind_for", "file_slug"]
