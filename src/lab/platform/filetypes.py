"""THE table of file types that cross a service boundary — extension -> (content type, kind) — and
the two lookups every uploader/parser uses. Lives in the platform kernel because BOTH the artifact
store (substrate) and the input parser (platform, used by workloads) derive from it.
"""
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
    "xml": ("application/xml", "artifact"), "svg": ("image/svg+xml", "artifact"),
    "json": ("application/json", "artifact"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "artifact"),
}
CONTENT_TYPES = {ext: ct for ext, (ct, _kind) in FILE_TYPES.items()}     # extension -> content type


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def content_type_for(name: str, default: str = "application/octet-stream") -> str:
    """Content type from a file name's extension — the one map every uploader uses."""
    return CONTENT_TYPES.get(_ext(name), default)


def kind_for(name: str, default: str = "unknown") -> str:
    """vsdx | image | document | artifact from a file name's extension (`default` when unknown)."""
    return FILE_TYPES[_ext(name)][1] if _ext(name) in FILE_TYPES else default


__all__ = ["FILE_TYPES", "CONTENT_TYPES", "content_type_for", "kind_for"]
